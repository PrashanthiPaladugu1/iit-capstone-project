"""agent_news: answers news and headline-sentiment questions about Nifty 50 stocks.

A standalone agent. It does not inherit from agent_technical or agent_fundamental and has its own prompt, tools and loop.
It shares only the gateway, the Budget and the trace format with them, so the research analyst can call it like the others.

How it works:
  1. Three tools are declared below with LangChain's @tool (name, typed arguments, docstring). Each one calls the `news`
     MCP server, which reads the publisher RSS feeds and adds up the sentiment counts.
  2. The model (gateway role "chat") replies with tool calls. Each call is checked against the tool's arguments, charged to
     the shared Budget, run on the MCP server, and the result goes back to the model.
  3. The loop ends when the model answers in text, or the Budget runs out. An answer given with no tool call is
     rejected once, then replaced by a "no news data" message, so a headline or a count always comes from a tool.
A run keeps its state in local variables, so the same agent can answer two questions at once.

    agent = NewsAgent(gateway, server)
    result = agent.run("Any news on Infosys this week?", session="s1")
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from langchain_core.tools import BaseTool, tool
from langchain_core.utils.function_calling import convert_to_openai_tool

from budget import Budget, BudgetExceeded

AGENT = "agent_news"
TOOL_RESULT_CHARS = 6000
MAX_STEPS = 12                      # model calls in one run, a second guard next to the Budget

SYSTEM_PROMPT = """You are the news and sentiment agent in a Nifty 50 research app.
Rules:
- Use the tools for every headline and every count. Never write a headline, date, source or count you did not get from a tool.
- You read headlines only (title, source, date, link) from Economic Times, Mint, Business Standard, Hindu BusinessLine and
  NDTV Profit. You never read full articles. Say "headlines only" once, in plain words.
- Only Nifty 50 stocks are covered. If a tool says a stock is not covered, say so plainly.
- For a stock use news_search. For the mood or sentiment of a stock use news_sentiment. For general market news with no stock
  named use news_market. Usually one or two calls are enough.
- Give each headline with its source and date (day and month) and keep the link next to it. Use the exact words of the title.
- Sentiment: report the counts from the tool (positive, negative, neutral, unlabelled). Say it is a rough guide from headlines
  and the labels come from a model. A few headlines is not a trend: say so when fewer than 5 were checked.
- When no headline was found, say that none of the checked feeds mentioned the stock in that period. Do not say nothing happened,
  and do not fill the gap from memory.
- If a tool lists failed feeds, name them in one short sentence. Show when the headlines were fetched (fetched_at).
- Do not predict the share price. Do not say buy, sell or hold. Do not claim a headline caused a price move.
- Keep it short: a small list, not an essay."""

REMINDER = ("You must call at least one tool to get the headlines before you answer. "
            "Do not write headlines or counts from memory. Call the right tool now.")
NO_DATA_ANSWER = ("I have no news data for this question, so I will not make up headlines. "
                  "Try naming one of the Nifty 50 stocks, for example: 'Any news on Infosys this week?'")


@dataclass
class NewsResult:
    answer: str
    tool_trace: list[dict] = field(default_factory=list)
    budget: dict = field(default_factory=dict)
    stopped_early: str = ""
    call_ids: list[int] = field(default_factory=list)
    reminders: int = 0


# ---------------------------------------------------------------------------------------------- the tools
def make_tools(call) -> list[BaseTool]:
    """The tools this agent may use. `call(name, arguments)` runs one tool on the MCP server and returns text."""

    @tool
    def news_search(stock: str, days: int = 7, limit: int = 10) -> str:
        """Recent headlines that name one Nifty 50 stock, newest first: source, date, title, link. stock is a symbol or a company name (TCS, INFY, Infosys). days is 1 to 30. Headlines only. No headlines can mean the stock was not in the checked feeds."""
        return call("news_search", {"stock": stock, "days": days, "limit": limit})

    @tool
    def news_sentiment(stock: str, days: int = 7) -> str:
        """Counts of positive, negative and neutral headlines for one Nifty 50 stock over the last `days` days (1 to 30), with the labelled headlines. A rough guide from headlines only."""
        return call("news_sentiment", {"stock": stock, "days": days})

    @tool
    def news_market(days: int = 1, limit: int = 10) -> str:
        """Latest general Indian market headlines (indices, rupee, economy, sectors). Use only when no stock is named."""
        return call("news_market", {"days": days, "limit": limit})

    return [news_search, news_sentiment, news_market]


# ---------------------------------------------------------------------------------------------- the agent
class NewsAgent:
    agent_name = AGENT
    system_prompt = SYSTEM_PROMPT
    reminder = REMINDER
    no_data_answer = NO_DATA_ANSWER

    def __init__(self, gateway, server, tool_names: list[str] | None = None):
        self.gateway = gateway
        self.server = server
        tools = make_tools(self._call)
        self.tools = [t for t in tools if tool_names is None or t.name in tool_names]
        self._by_name = {t.name: t for t in self.tools}
        self.tool_definitions = [convert_to_openai_tool(t) for t in self.tools]

    def _call(self, name: str, arguments: dict) -> str:
        return self.server.call(name, arguments)

    # ------------------------------------------------------------------ public
    def run(self, question: str, *, session: str = "", parent_call_id: int | None = None,
            budget: Budget | None = None, route: str = "news", focus: str = "") -> NewsResult:
        """`focus` is one extra rule for the system prompt, used when another agent answers the rest of the question."""
        budget = budget or Budget()
        system = self.system_prompt + (f"\n- {focus}" if focus else "")
        messages: list[dict] = [{"role": "system", "content": system}, {"role": "user", "content": question}]
        trace: list[dict] = []
        call_ids: list[int] = []
        stop, reminders, used_tools, final = "", 0, False, ""
        budget.enter_agent(self.agent_name)
        try:
            for _ in range(MAX_STEPS):
                try:
                    budget.before_model_call()
                except BudgetExceeded as exc:
                    stop = str(exc)
                    break
                result = self.gateway.chat("chat", messages, self.tool_definitions, session=session, agent=self.agent_name,
                                           node="model", route=route, parent_call_id=parent_call_id, preview=question)
                budget.after_model_call(result.tokens_in, result.tokens_out, getattr(result, "cost", None))
                if result.call_id:
                    call_ids.append(result.call_id)
                if result.tool_calls:
                    messages.append({"role": "assistant", "content": result.text or "", "tool_calls": [
                        {"id": c["id"], "name": c["name"], "arguments": c.get("arguments") or {}} for c in result.tool_calls]})
                    for c in result.tool_calls:
                        text, ok, stop = self._run_tool(c["name"], c.get("arguments") or {}, budget)
                        trace.append({"tool": c["name"], "arguments": c.get("arguments") or {}, "ok": ok,
                                      "result_chars": len(text)})
                        messages.append({"role": "tool", "tool_call_id": c["id"], "name": c["name"], "content": text})
                        used_tools = True
                        if stop:
                            break
                    if stop:
                        break
                    continue
                if used_tools:
                    final = (result.text or "").strip()               # answered after using tools
                    break
                if reminders < 1:                                     # answered with no data at all: one reminder, then refuse
                    reminders += 1
                    messages.append({"role": "assistant", "content": result.text or ""})
                    messages.append({"role": "user", "content": self.reminder})
                    continue
                final, stop = self.no_data_answer, "model answered without tool data"
                break
            else:
                stop = f"step limit reached ({MAX_STEPS})"
        finally:
            budget.leave_agent()
        if not final:
            final = self._last_text(messages)
        if stop and not final:
            final = f"I could not finish this: {stop}."
        return NewsResult(answer=final, tool_trace=trace, budget=budget.summary(), stopped_early=stop,
                          call_ids=call_ids, reminders=reminders)

    # ------------------------------------------------------------------ tool execution
    def _run_tool(self, name: str, arguments: dict, budget: Budget) -> tuple[str, bool, str]:
        """Returns (text for the model, ok, stop reason). A wrong tool name or argument goes back to the model as an error."""
        try:
            budget.before_tool_call()
        except BudgetExceeded as exc:
            return json.dumps({"error": str(exc)}), False, str(exc)
        tool_ = self._by_name.get(name)
        if tool_ is None:
            return json.dumps({"error": f"unknown tool '{name}'. Use one of: {', '.join(self._by_name)}"}), False, ""
        try:
            text = str(tool_.invoke(arguments))
        except Exception as exc:                                      # bad argument, or the server failed: the model can retry
            return json.dumps({"error": f"{type(exc).__name__}: {exc}"[:500]}), False, ""
        return text[:TOOL_RESULT_CHARS], '"error"' not in text[:40], ""

    @staticmethod
    def _last_text(messages: list[dict]) -> str:
        for m in reversed(messages):
            if m["role"] == "assistant" and str(m.get("content") or "").strip() and not m.get("tool_calls"):
                return str(m["content"]).strip()
        return ""
