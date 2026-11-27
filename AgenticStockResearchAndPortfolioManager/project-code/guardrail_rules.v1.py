"""guardrail_rules: what the Admin Guardrails tab shows and what a custom rule does.

Three kinds of row:
  built-in   the catalog below. Read-only here: code enforces them, and this version has no on/off switch for any of them.
  keyword    a custom rule: words or phrases looked for in the QUESTION, before routing. Action: block or warn. Hard (plain code),
             but it only matches the words typed in.
  prompt     a custom rule: one sentence added to the agents' system prompts. SOFT: the model can ignore it.

Custom rules live in the settings store (key "guardrails"), so a change applies to the next question with no restart.
The event log (settings store) records every time a custom rule fires.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from model_settings import SettingsError

TIMINGS = ("input", "prompt", "tool", "output")     # when the rule acts: before the prompt, in it, inside a tool, on the finished answer
STRENGTHS = ("hard", "soft")                         # hard = plain code, cannot be talked out of; soft = a request to the model
STATES = ("built", "planned")
RULE_TYPES = ("keyword", "prompt")
KEYWORD_ACTIONS = ("block", "warn")
MAX_RULES = 30
MAX_TEXT = 300
MAX_WORDS = 20
MAX_WORD_CHARS = 60
SUMMARY_CHARS = 120                                  # how much of a question the event log keeps


def _row(rid, name, what, layer, timing, strength, state, locked=False):
    return {"id": rid, "name": name, "what": what, "layer": layer, "timing": timing, "strength": strength,
            "state": state, "locked": locked, "switchable": False}


# G1 to G8 are the original guardrails. A1 to A7 are checks that already exist in code or prompts. P1 to P18 are the review of
# 26 Nov 2026 (P6, the event log, is built with this tab). "assumed" marks a threshold nobody has confirmed.
CATALOG = [
    _row("G1", "Nifty 50 only", "A stock outside the Nifty 50 is refused by every tool, and a portfolio that names one is blocked. "
         "There is no up-front block yet (see P1).", "universe", "tool", "hard", "built", locked=True),
    _row("G2", "Portfolio size: at most 6", "A portfolio of 7 or more stocks is blocked.", "portfolio", "tool", "hard", "built"),
    _row("G3", "Portfolio size: at least 4", "A portfolio of fewer than 4 stocks is blocked. The minimum is assumed.",
         "portfolio", "tool", "hard", "built"),
    _row("G4", "Weights 5% to 40%, sum 100%", "Weights that do not add up to 100%, or fall outside 5% to 40%, are blocked. "
         "The range is assumed.", "portfolio", "tool", "hard", "built"),
    _row("G5", "One industry group over 50%", "A portfolio with more than half in one industry group gets a warning.",
         "portfolio", "tool", "hard", "built"),
    _row("G6", "Under one year of prices", "A stock with fewer than 252 trading days of prices gets a warning.",
         "portfolio", "tool", "hard", "built"),
    _row("G7", "Disclaimer footer", "Every portfolio answer ends with: not investment advice, the data date and the "
         "unadjusted-price note. The tool adds it, so the model cannot leave it out.", "output", "output", "hard", "built",
         locked=True),
    _row("G8", "Budget caps", "Model calls, tool calls, tokens and agent depth are capped for each question. "
         "A question that reaches a cap stops and says so.", "agent", "tool", "hard", "built", locked=True),
    _row("A1", "Invented citations removed", "The research analyst removes a page citation that no specialist gave.",
         "output", "output", "hard", "built"),
    _row("A2", "Invented numbers rejected", "The research analyst drops a merged answer that contains a number no specialist "
         "gave, and shows the specialist answers instead.", "output", "output", "hard", "built"),
    _row("A3", "Document match cutoff", "A document passage below the minimum score is treated as not found.",
         "documents", "tool", "hard", "built"),
    _row("A4", "No buy, sell or prediction", "The agent prompts say not to give buy or sell advice or predict prices.",
         "agent", "prompt", "soft", "built"),
    _row("A5", "Numbers only from tools", "The agent prompts say never to quote a figure that no tool returned.",
         "agent", "prompt", "soft", "built"),
    _row("A6", "News: headlines only", "The news prompt says to report headlines only and not to claim a price move from one.",
         "news", "prompt", "soft", "built"),
    _row("A7", "Unlabelled stays unlabelled", "A headline the model gave no label is counted as unlabelled, never guessed. "
         "Code adds up the counts.", "news", "tool", "hard", "built"),
    _row("P1", "Universe check before routing", "Refuse a non-Nifty 50 stock before any agent or model call, with an "
         "out-of-scope route.", "universe", "input", "hard", "planned"),
    _row("P2", "One name-to-symbol resolver", "One shared lookup for company names, de-duplication and renamed stocks "
         "such as TMPV.", "universe", "input", "hard", "planned"),
    _row("P3", "Time limit per question", "Stop a question that runs past a total time, not only past a count of calls.",
         "agent", "tool", "hard", "planned"),
    _row("P4", "Fence untrusted text", "Mark headlines and document passages as data, not instructions, in the prompts.",
         "agent", "prompt", "soft", "planned"),
    _row("P5", "Answer grounding on every route", "Check numbers, links and headlines in every answer against the tool "
         "output, not only in the analyst merge.", "output", "output", "hard", "planned"),
    _row("P6", "Guardrail event log", "Record each time a custom rule fires: rule, action, a short question summary, "
         "session and time. Shown in the Guardrails tab.", "audit", "output", "hard", "built"),
    _row("P7", "Company-scoped document search", "Code, not the prompt, requires a stock symbol on a document search.",
         "documents", "tool", "hard", "planned"),
    _row("P8", "Weak-evidence flag", "Flag an answer built on one passage or on low scores.",
         "documents", "tool", "hard", "planned"),
    _row("P9", "Document coverage from the index", "Take 'which stock has no documents' from the index, not from the prompt text.",
         "documents", "tool", "hard", "planned"),
    _row("P10", "Data freshness flag", "Compare the data date with today and warn when prices are old.",
         "data", "tool", "hard", "planned"),
    _row("P11", "Price-jump detector", "Flag a one-day move that looks like a split, bonus or demerger.",
         "data", "tool", "hard", "planned"),
    _row("P12", "Standalone or consolidated label", "Name the basis of every financial figure. The basis of the workbooks "
         "is not known yet.", "data", "tool", "hard", "planned"),
    _row("P13", "Price-history audit", "Check for gaps and duplicate dates in the price data.",
         "data", "tool", "hard", "planned"),
    _row("P14", "Correlation concentration", "Warn when the chosen stocks move together.",
         "portfolio", "tool", "hard", "planned"),
    _row("P15", "Backtest honesty note", "State that a replay uses today's constituents only and has no benchmark.",
         "portfolio", "output", "hard", "planned"),
    _row("P16", "Advice and guarantee filter", "Catch advice, prediction and guarantee phrases in the finished answer.",
         "output", "output", "hard", "planned"),
    _row("P17", "Tool argument validation audit", "Check that every tool rejects out-of-range arguments.",
         "agent", "tool", "hard", "planned"),
    _row("P18", "Tool allow-list per agent", "Each agent is given only the tools it needs, by name.",
         "agent", "tool", "hard", "planned"),
]


# ---------------------------------------------------------------------------------------------- custom rule values
def split_words(text: str) -> list[str]:
    """'a b, ,c' -> ['a b', 'c']."""
    return [w.strip() for w in (text or "").split(",") if w.strip()]


def validate(value) -> dict:
    """The stored value must be exactly {"custom": [rule, ...], "next": n}. Raises SettingsError with a plain message."""
    if not isinstance(value, dict) or set(value) != {"custom", "next"}:
        raise SettingsError('guardrails setting must be {"custom": [...], "next": number}')
    custom, nxt = value["custom"], value["next"]
    if not isinstance(custom, list):
        raise SettingsError("custom guardrails must be a list")
    if not (isinstance(nxt, int) and not isinstance(nxt, bool) and nxt >= 1):
        raise SettingsError("next must be a whole number of 1 or more")
    if len(custom) > MAX_RULES:
        raise SettingsError(f"at most {MAX_RULES} custom guardrails")
    seen, highest = set(), 0
    for rule in custom:
        if not isinstance(rule, dict) or set(rule) != {"id", "type", "text", "words", "action", "enabled"}:
            raise SettingsError("each custom guardrail needs id, type, text, words, action and enabled")
        match = re.fullmatch(r"C(\d+)", rule["id"]) if isinstance(rule["id"], str) else None
        if not match or rule["id"] in seen:
            raise SettingsError(f"guardrail id {rule['id']!r} must be C and a number, and used once")
        seen.add(rule["id"])
        highest = max(highest, int(match.group(1)))
        if rule["type"] not in RULE_TYPES:
            raise SettingsError(f"{rule['id']}: type must be keyword or prompt")
        if not (isinstance(rule["text"], str) and rule["text"].strip()) or len(rule["text"]) > MAX_TEXT:
            raise SettingsError(f"{rule['id']}: the text must be 1 to {MAX_TEXT} characters")
        if not isinstance(rule["enabled"], bool):
            raise SettingsError(f"{rule['id']}: enabled must be true or false")
        words = rule["words"]
        if rule["type"] == "keyword":
            if not (isinstance(words, list) and 1 <= len(words) <= MAX_WORDS):
                raise SettingsError(f"{rule['id']}: a keyword rule needs 1 to {MAX_WORDS} words or phrases")
            if not all(isinstance(w, str) and 1 <= len(w.strip()) <= MAX_WORD_CHARS for w in words):
                raise SettingsError(f"{rule['id']}: each word or phrase must be 1 to {MAX_WORD_CHARS} characters")
            if rule["action"] not in KEYWORD_ACTIONS:
                raise SettingsError(f"{rule['id']}: action must be block or warn")
        else:
            if words != [] or rule["action"] != "prompt":
                raise SettingsError(f"{rule['id']}: a prompt rule has no words and the action 'prompt'")
    if nxt <= highest:
        raise SettingsError("next must be above every id already used")
    return value


def add_rule(value: dict, rule_type: str, text: str, words_text: str, action: str) -> dict:
    """A new value with one more enabled rule. The old value is not changed."""
    rule = {"id": f"C{value['next']}", "type": rule_type, "text": (text or "").strip(),
            "words": split_words(words_text) if rule_type == "keyword" else [],
            "action": action if rule_type == "keyword" else "prompt", "enabled": True}
    return validate({"custom": [*value["custom"], rule], "next": value["next"] + 1})


def remove_rule(value: dict, rule_id: str) -> dict:
    """A new value without the rule. Its id is never used again, because `next` only goes up."""
    if rule_id not in {r["id"] for r in value["custom"]}:
        raise SettingsError(f"there is no custom guardrail {rule_id}")
    return validate({"custom": [r for r in value["custom"] if r["id"] != rule_id], "next": value["next"]})


def set_enabled(value: dict, rule_id: str, enabled: bool) -> dict:
    if rule_id not in {r["id"] for r in value["custom"]}:
        raise SettingsError(f"there is no custom guardrail {rule_id}")
    return validate({"custom": [{**r, "enabled": bool(enabled)} if r["id"] == rule_id else r for r in value["custom"]],
                     "next": value["next"]})


# ---------------------------------------------------------------------------------------------- the input check
@dataclass
class Decision:
    blocked: bool = False
    message: str = ""                                   # what to show the user instead of an answer (only when blocked)
    hits: list[dict] = field(default_factory=list)      # every match: {"id", "word", "action"}
    notes: list[str] = field(default_factory=list)      # one line per warn rule that matched, to show with the answer


def _found(word: str, question: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(word.strip())}(?!\w)", question, re.IGNORECASE) is not None


def check_question(question: str, rules: list[dict]) -> Decision:
    """Look for the words of every enabled keyword rule in the question. A block wins over a warn."""
    decision = Decision()
    blocking = []
    for rule in rules:
        if rule["type"] != "keyword" or not rule["enabled"]:
            continue
        word = next((w for w in rule["words"] if _found(w, question or "")), None)
        if word is None:
            continue
        decision.hits.append({"id": rule["id"], "word": word, "action": rule["action"]})
        if rule["action"] == "block":
            blocking.append(rule)
        else:
            decision.notes.append(f"Guardrail {rule['id']}: {rule['text']}")
    if blocking:
        decision.blocked = True
        lines = "; ".join(f"{r['id']}: {r['text']}" for r in blocking)
        decision.message = f"This question was not answered because of a guardrail ({lines})."
        decision.notes = []
    return decision


def prompt_block(rules: list[dict]) -> str:
    """Extra lines for a system prompt, one per enabled prompt rule. Empty when there are none."""
    lines = [f"- {r['text']}" for r in rules if r["type"] == "prompt" and r["enabled"]]
    if not lines:
        return ""
    return "\nExtra rules set by the administrator (follow them):\n" + "\n".join(lines)
