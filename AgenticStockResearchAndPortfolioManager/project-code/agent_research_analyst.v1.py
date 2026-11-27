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
from dataclasses import dataclass

from agent_technical import TechnicalResult
from budget import Budget, BudgetExceeded
from gateway import GatewayError

AGENT = "agent_research_analyst"
MAX_ANSWER_CHARS = 6000

SPLIT_PROMPT = """You split one question about Nifty 50 stocks into two questions for two specialists.
- "technical": price, trend, returns, indicators (RSI, MACD, moving averages), volume, delivery, top movers.
- "fundamental": financial statements, growth, ratios, valuation, and what annual reports, earnings calls and presentations say.
Rules:
- Copy the stock names or symbols into each part, so each part makes sense on its own.
- Use an empty string for a part the question does not need.
- A request such as "research TCS" or "full analysis of INFY" needs both parts.
- Do not answer the question. Reply with JSON only, in this form: {"technical": "...", "fundamental": "..."}"""

SYNTHESIS_PROMPT = """You merge the answers of a technical analyst and a fundamental analyst into one answer for the user.
Rules:
- Use only facts and numbers that appear in the two answers below. Do not add, calculate, round or change any number.
- Keep each source citation (file and page) next to the point it supports.
- If a part is "not available", say so once in a short sentence and do not guess it.
- Do not say buy or sell and do not predict. Do not mention the analysts, agents or tools.
- Several stocks: group the points by stock. Keep it short: a few lines or a small table, not an essay."""

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


def numbers_in(text: str) -> set[float]:
    return {float(m.replace(",", "")) for m in _NUMBER.findall(text or "")}


def unsupported_numbers(answer: str, source: str) -> list[float]:
    """Numbers in `answer` that are not in `source`. Whole numbers up to 10 are ignored (list markers, "5 years")."""
    known = numbers_in(source)
    return sorted(n for n in numbers_in(answer) - known if not (n == int(n) and n <= SMALL_WHOLE_NUMBER))


@dataclass
class ResearchResult(TechnicalResult):
    note: str = ""                    # why the merged answer was replaced, empty when all is well


def parse_split(text: str) -> tuple[str, str] | None:
    """(technical, fundamental) from the model's reply, or None when it is unusable. Accepts ```json fences."""
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
    technical, fundamental = data.get("technical"), data.get("fundamental")
    if not isinstance(technical, str) or not isinstance(fundamental, str):
        return None
    technical, fundamental = technical.strip(), fundamental.strip()
    return (technical, fundamental) if technical or fundamental else None


class ResearchAnalyst:
    agent_name = AGENT

    def __init__(self, gateway, technical, fundamental):
        self.gateway = gateway
        self.technical = technical
        self.fundamental = fundamental

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
            plan = [(label, agent, text, SPLIT_FOCUS) for label, agent, text in
                    (("technical", self.technical, parts[0]), ("fundamental", self.fundamental, parts[1])) if text]
        answers: dict[str, str] = {}
        for label, agent, text, focus in plan:
            res = agent.run(text, session=session, parent_call_id=split_id or parent, budget=budget, route=route, focus=focus)
            call_ids.extend(res.call_ids)
            trace.extend({"agent": label, **t} for t in res.tool_trace)
            if res.stopped_early:
                stops.append(f"{getattr(agent, 'agent_name', label)}: {res.stopped_early}")
            answers[label] = (res.answer or "").strip() or f"Not available: {res.stopped_early or 'no answer'}."
        stopped = "; ".join(stops)
        if len(answers) == 1:                                    # only one half was needed: its answer is the answer
            only = next(iter(answers.values()))
            return ResearchResult(answer=only, tool_trace=trace, budget=budget.summary(), stopped_early=stopped,
                                  call_ids=call_ids)
        merged, note = self._synthesise(question, answers, session, split_id or parent, budget, call_ids, stops)
        return ResearchResult(answer=merged, tool_trace=trace, budget=budget.summary(),
                              stopped_early="; ".join(stops), call_ids=call_ids, note=note)

    def _split(self, question, session, parent, budget, call_ids):
        """(id of the split call, (technical, fundamental) or None)."""
        budget.before_model_call()                               # BudgetExceeded here ends the run cleanly
        try:
            res = self.gateway.chat(
                "chat", [{"role": "system", "content": SPLIT_PROMPT}, {"role": "user", "content": question}], None,
                params={"temperature": 0}, session=session, agent=AGENT, node="split", route="research",
                parent_call_id=parent, preview=question)
        except GatewayError:
            return None, None
        budget.after_model_call(res.tokens_in, res.tokens_out, getattr(res, "cost", None))
        if res.call_id:
            call_ids.append(res.call_id)
        return res.call_id, parse_split(res.text)

    def _synthesise(self, question, answers, session, parent, budget, call_ids, stops) -> tuple[str, str]:
        labelled = "\n\n".join(f"**{label.capitalize()}**\n\n{text}" for label, text in answers.items())
        sections = "\n\n".join(f"{label.capitalize()} analyst answer:\n{text[:MAX_ANSWER_CHARS]}"
                               for label, text in answers.items())
        try:
            budget.before_model_call()
            res = self.gateway.chat(
                "chat", [{"role": "system", "content": SYNTHESIS_PROMPT},
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
        extra = unsupported_numbers(merged, question + "\n" + "\n".join(answers.values()))
        if extra:
            shown = ", ".join(f"{n:g}" for n in extra)
            return labelled, (f"The merged answer contained numbers that neither analyst gave ({shown}), so it was "
                              f"dropped and the two analyst answers are shown as they are.")
        return merged, ""
