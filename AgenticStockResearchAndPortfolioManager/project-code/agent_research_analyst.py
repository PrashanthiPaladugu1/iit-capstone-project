"""agent_research_analyst: answers a question that needs both views of a stock, by using the two specialist agents.

Steps (the analyst has no tools of its own, so it can never invent a number from a tool it did not call):
  1. split      one `chat` call turns the question into a technical question and a fundamental question
                (price, trend, indicators / statements, ratios, documents). If the reply cannot be read, both agents get the
                whole question plus a note to answer only their own half. That is what the app did before this agent existed.
  2. specialists agent_technical and agent_fundamental each answer their own question, one after the other, on ONE shared
                Budget. Their tool calls and numbers are untouched.
  3. synthesis  one `chat` call merges the two answers into one. Every number in the merged answer must appear in a
                specialist answer or in the question. If one does not, the merged answer is dropped and the two labelled
                specialist answers are shown instead, with a note.
If only one half is needed the analyst returns that specialist's answer as it is and makes no synthesis call.

    analyst = ResearchAnalyst(gateway, technical_agent, fundamental_agent)
    result = analyst.run("Revenue growth and RSI of ITC", session="s1")
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from agent_technical import TechnicalResult
from budget import Budget, BudgetExceeded
from gateway import GatewayError
from guardrail_rules import dedupe

AGENT = "agent_research_analyst"
MAX_ANSWER_CHARS = 6000

SPLIT_PROMPT = """You split one question about Nifty 50 stocks into two questions for two specialists.
- "technical": price, trend, returns, indicators (RSI, MACD, moving averages), volume, delivery, top movers.
- "fundamental": financial statements, growth, ratios, valuation, and what annual reports, earnings calls and presentations say.
Rules:
- Copy the stock names or symbols into each part, so each part makes sense on its own.
- Use an empty string for a part the question does not need.
- An open request such as "research TCS", "how is INFY doing", "is it a good buy" needs both parts.
  Ask the technical specialist for price, returns, trend and indicators.
  Ask the fundamental specialist for growth, margins, ROE, valuation and what management says in the latest documents.
- Do not answer the question. Reply with JSON only, in this form: {"technical": "...", "fundamental": "..."}"""

# Used instead of SPLIT_PROMPT when a news agent is connected. A news part is asked for only when the user asks about news.
SPLIT_PROMPT_NEWS = """You split one question about Nifty 50 stocks into questions for three specialists.
- "technical": price, trend, returns, indicators (RSI, MACD, moving averages), volume, delivery, top movers.
- "fundamental": financial statements, growth, ratios, valuation, and what annual reports, earnings calls and presentations say.
- "news": recent headlines, news, announcements, what is being reported, and the mood or sentiment of the news.
Rules:
- Copy the stock names or symbols into each part, so each part makes sense on its own.
- Use an empty string for a part the question does not need.
- Fill "news" only when the user asks about news, headlines, what is happening, or sentiment. An open request such as
  "research TCS" or "is it a good buy" does not need news.
- An open request such as "research TCS", "how is INFY doing", "is it a good buy" needs the technical and fundamental parts.
  Ask the technical specialist for price, returns, trend and indicators.
  Ask the fundamental specialist for growth, margins, ROE, valuation and what management says in the latest documents.
- Do not answer the question. Reply with JSON only, in this form: {"technical": "...", "fundamental": "...", "news": "..."}"""

NEWS_MERGE_RULES = """
- A news answer lists headlines with their source and date. Keep each headline's source and date next to it.
  Headlines show what was reported, not why a price moved: never say a headline caused a price move.
  A sentiment count is a rough guide from headlines only, not a forecast."""

SYNTHESIS_PROMPT = """You merge the answers of a technical analyst and a fundamental analyst into one answer for the user.
Rules:
- Use only facts and numbers that appear in the two answers below. Do not add, calculate, round or change any number.
- Keep each document citation (a file name and page, such as Transcript_Nov_2025.pdf, p. 5) next to the point it supports.
  Never write a page number or a source for the analysts themselves: price and statement figures have no page.
- If the user asks whether to buy, sell or invest: say you cannot advise, then give the evidence for and the evidence
  against, using only the two answers. This is not a recommendation.
- If a part is "not available", say so once in a short sentence and do not guess it.
- Do not say buy or sell and do not predict. Do not mention the analysts, agents or tools.
- Keep it short: a few lines or a small table per section, not an essay."""

SECTION_HEADINGS = {"technical": "**Technical**", "fundamental": "**Fundamental**", "news": "**News**"}
SECTION_SUBJECT = {"technical": "the technical analyst's points", "fundamental": "the fundamental analyst's points",
                   "news": "the news answer"}


def section_rule(labels: list[str]) -> str:
    """The layout rule for one merge call. Only the parts that came back get a heading, in the order given.
    A prompt cannot force a model to obey, so the labelled fallback (same headings) is used when the merge fails."""
    heads = [(SECTION_HEADINGS[k], SECTION_SUBJECT[k]) for k in labels if k in SECTION_HEADINGS]
    lines = ["- Lay the answer out in sections. Use only these headings, in this order, each on its own line: "
             + ", ".join(h for h, _ in heads) + ". Do not add any other heading."]
    lines += [f"  Under {h} put {what}." for h, what in heads]
    lines.append("- Put every point under one of these headings. Nothing goes before the first heading. Document and "
                 "management points go under **Fundamental**, not under a new heading. If you give evidence for and "
                 "against, write it inside the sections, not as a block of its own.")
    lines.append("- Several stocks: keep the stocks inside each section. Use one table per section with one row per stock, "
                 "or short lines that name the stock. Do not make a section for each stock.")
    return "\n".join(lines)

# Used when the split fails: each specialist gets the whole question and is told which half is its own.
FALLBACK_FOCUS = {
    "technical": "The question may have two parts. Use your tools for the price, trend and indicator part and answer only "
                 "that. Another agent answers the financial-statement part: do not mention it.",
    "fundamental": "The question may have two parts. Use your tools for the financial-statement, growth, ratio and valuation "
                   "part and answer only that. Another agent answers the price and indicator part: do not mention it.",
}
SPLIT_FOCUS = ("Answer only the question you are given. Another agent answers the rest of the original request: "
               "do not mention it.")

_NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")
SMALL_WHOLE_NUMBER = 10          # list markers and counts such as "2." or "5 years" are not checked


# A citation in brackets: a file name with page, or an analyst label with a page.
_CITATION = re.compile(r"\s*\(([^()]*?\bp\.\s*\d+[^()]*)\)")


def strip_unsupported_citations(text: str, source: str) -> tuple[str, int]:
    """Removes bracketed page citations that no specialist gave. A real citation (a file name the specialists wrote)
    stays. Returns the cleaned text and the number removed."""
    removed = 0

    def check(match: re.Match) -> str:
        nonlocal removed
        if match.group(0).strip() in source:
            return match.group(0)
        removed += 1
        return ""

    return _CITATION.sub(check, text), removed


def numbers_in(text: str) -> set[float]:
    return {float(m.replace(",", "")) for m in _NUMBER.findall(text or "")}


def unsupported_numbers(answer: str, source: str) -> list[float]:
    """Numbers in `answer` that are not in `source`. Whole numbers up to 10 are ignored (list markers, "5 years")."""
    known = numbers_in(source)
    return sorted(n for n in numbers_in(answer) - known if not (n == int(n) and n <= SMALL_WHOLE_NUMBER))


@dataclass
class ResearchResult(TechnicalResult):
    note: str = ""                    # why the merged answer was replaced, empty when all is well


def parse_parts(text: str, keys: tuple[str, ...] = ("technical", "fundamental")) -> dict[str, str] | None:
    """One question per key from the model's reply, or None when it is unusable. Accepts ```json fences.
    "technical" and "fundamental" must be present as text; any other key (such as "news") may be missing."""
    body = (text or "").strip()
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(body[start:end + 1])
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    parts = {}
    for key in keys:
        value = data.get(key, "" if key not in ("technical", "fundamental") else None)
        if not isinstance(value, str):
            return None
        parts[key] = value.strip()
    return parts if any(parts.values()) else None


def parse_split(text: str) -> tuple[str, str] | None:
    """(technical, fundamental) from the model's reply, or None when it is unusable."""
    parts = parse_parts(text)
    return (parts["technical"], parts["fundamental"]) if parts else None


class ResearchAnalyst:
    agent_name = AGENT
    extra_rules = ""             # lines the Admin Guardrails tab adds to the merge prompt (the specialists get their own copy)

    def __init__(self, gateway, technical, fundamental, parallel: bool = False, news=None):
        self.gateway = gateway
        self.technical = technical
        self.fundamental = fundamental
        self.news = news                     # optional third specialist, asked only when the question is about news
        self.parallel = parallel             # True: run the specialists at the same time, one thread each

    @staticmethod
    def new_budget() -> Budget:
        """Two specialist runs plus a split and a synthesis call need more room than one agent does."""
        return Budget(max_model_calls=24, max_tool_calls=40, max_tokens=80000)

    # ------------------------------------------------------------------ public
    def run(self, question: str, *, session: str = "", parent_call_id: int | None = None,
            budget: Budget | None = None, route: str = "research") -> ResearchResult:
        budget = budget or self.new_budget()
        call_ids: list[int] = []
        trace: list[dict] = []
        stops: list[str] = []
        budget.enter_agent(self.agent_name)
        try:
            return self._run(question, session, parent_call_id, budget, route, call_ids, trace, stops)
        except BudgetExceeded as exc:
            stops.append(str(exc))
            return ResearchResult(answer=f"I could not finish this: {exc}.", tool_trace=trace, budget=budget.summary(),
                                  stopped_early="; ".join(stops), call_ids=call_ids)
        finally:
            budget.leave_agent()

    # ------------------------------------------------------------------ steps
    def _run(self, question, session, parent, budget, route, call_ids, trace, stops) -> ResearchResult:
        split_id, parts = self._split(question, session, parent, budget, call_ids)
        if parts is None:                                        # unreadable split: both agents, whole question
            plan = [("technical", self.technical, question, FALLBACK_FOCUS["technical"]),
                    ("fundamental", self.fundamental, question, FALLBACK_FOCUS["fundamental"])]
        else:
            specialists = [("technical", self.technical), ("fundamental", self.fundamental)]
            if self.news is not None:
                specialists.append(("news", self.news))
            plan = [(label, agent, parts[label], SPLIT_FOCUS) for label, agent in specialists if parts.get(label)]
        answers: dict[str, str] = {}
        alerts: list[str] = []
        results = self._run_specialists(plan, session, split_id or parent, budget, route)
        for (label, agent, text, _), res in zip(plan, results):   # always in plan order, whichever finished first
            # What the analyst handed to this specialist, shown in the chat's "Tools used" list before the specialist's own calls.
            trace.append({"agent": "research", "tool": f"invoke_{getattr(agent, 'agent_name', label)}",
                          "arguments": {"question": text}})
            call_ids.extend(res.call_ids)
            alerts.extend(getattr(res, "alerts", None) or [])
            trace.extend({"agent": label, **t} for t in res.tool_trace)
            if res.stopped_early:
                stops.append(f"{getattr(agent, 'agent_name', label)}: {res.stopped_early}")
            answers[label] = (res.answer or "").strip() or f"Not available: {res.stopped_early or 'no answer'}."
        stopped = "; ".join(stops)
        if len(answers) == 1:                                    # only one half was needed: its answer is the answer
            only = next(iter(answers.values()))
            return ResearchResult(answer=only, tool_trace=trace, budget=budget.summary(), stopped_early=stopped,
                                  call_ids=call_ids, alerts=dedupe(alerts))
        merged, note = self._synthesise(question, answers, session, split_id or parent, budget, call_ids, stops)
        return ResearchResult(answer=merged, tool_trace=trace, budget=budget.summary(),
                              stopped_early="; ".join(stops), call_ids=call_ids, note=note, alerts=dedupe(alerts))

    def _run_specialists(self, plan, session, parent, budget, route) -> list:
        """One result per plan item, in plan order. With two items and parallel=True they run in two threads."""
        def one(item, depth=None):
            _, agent, text, focus = item
            call = lambda: agent.run(text, session=session, parent_call_id=parent, budget=budget, route=route, focus=focus)
            if depth is None:
                return call()
            with budget.branch(depth):                           # each thread counts agent depth on its own branch
                return call()

        if not self.parallel or len(plan) < 2:
            return [one(item) for item in plan]
        depth = budget.current_depth()
        with ThreadPoolExecutor(max_workers=len(plan), thread_name_prefix="specialist") as pool:
            futures = [pool.submit(one, item, depth) for item in plan]
        return [f.result() for f in futures]                    # the pool has waited for both; the first error is raised

    def _split(self, question, session, parent, budget, call_ids):
        """(id of the split call, {specialist: question} or None)."""
        budget.before_model_call()                               # BudgetExceeded here ends the run cleanly
        prompt = SPLIT_PROMPT if self.news is None else SPLIT_PROMPT_NEWS
        try:
            res = self.gateway.chat(
                "chat", [{"role": "system", "content": prompt}, {"role": "user", "content": question}], None,
                params={"temperature": 0}, session=session, agent=AGENT, node="split", route="research",
                parent_call_id=parent, preview=question)
        except GatewayError:
            return None, None
        budget.after_model_call(res.tokens_in, res.tokens_out, getattr(res, "cost", None))
        if res.call_id:
            call_ids.append(res.call_id)
        keys = ("technical", "fundamental") if self.news is None else ("technical", "fundamental", "news")
        return res.call_id, parse_parts(res.text, keys)

    def _synthesise(self, question, answers, session, parent, budget, call_ids, stops) -> tuple[str, str]:
        labelled = "\n\n".join(f"{SECTION_HEADINGS[label]}\n\n{text}" for label, text in answers.items())
        sections = "\n\n".join(f"{label.capitalize()} analyst answer:\n{text[:MAX_ANSWER_CHARS]}"
                               for label, text in answers.items())
        try:
            budget.before_model_call()
            res = self.gateway.chat(
                "chat", [{"role": "system", "content": SYNTHESIS_PROMPT + "\n" + section_rule(list(answers))
                          + (NEWS_MERGE_RULES if "news" in answers else "") + self.extra_rules},
                         {"role": "user", "content": f"Question: {question}\n\n{sections}"}], None,
                params={"temperature": 0}, session=session, agent=AGENT, node="synthesis", route="research",
                parent_call_id=parent, preview=question)
        except (GatewayError, BudgetExceeded) as exc:
            stops.append(f"synthesis: {exc}")
            return labelled, "The merged answer could not be written, so the two analyst answers are shown as they are."
        budget.after_model_call(res.tokens_in, res.tokens_out, getattr(res, "cost", None))
        if res.call_id:
            call_ids.append(res.call_id)
        merged = (res.text or "").strip()
        if not merged:
            return labelled, "The merged answer was empty, so the two analyst answers are shown as they are."
        source = question + "\n" + "\n".join(answers.values())
        merged, removed = strip_unsupported_citations(merged, source)
        citation_note = f"{removed} citation(s) the analysts did not give were removed." if removed else ""
        extra = unsupported_numbers(merged, source)
        if extra:
            shown = ", ".join(f"{n:g}" for n in extra)
            return labelled, (f"The merged answer contained numbers that neither analyst gave ({shown}), so it was "
                              f"dropped and the two analyst answers are shown as they are.")
        return merged, citation_note
