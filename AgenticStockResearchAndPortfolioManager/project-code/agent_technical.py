"""agent_technical: answers price, trend and indicator questions about Nifty 50 stocks.

How tool calling works here:
  1. Each market-data tool is declared below with LangChain's @tool (name, typed arguments, docstring).
     The body does no maths. It calls the `market-data` MCP server, which owns the data and the calculations.
  2. The model node sends the tool definitions to the gateway (role "chat"). The model replies with tool calls.
  3. LangGraph's ToolNode runs the requested tools and checks the arguments. An unknown tool name or a bad
     argument comes back to the model as an error message, not a crash.
  4. The loop repeats until the model answers in text or the shared Budget runs out.
An answer given without any tool call is rejected once, then replaced by a "no tool data" message, so numbers
in an answer always come from a tool.

    agent = TechnicalAgent(gateway, server)
    result = agent.run("How is TCS doing?", session="s1")
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool, tool
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from budget import Budget, BudgetExceeded
from guardrail_rules import alerts_from_tool_text, dedupe

AGENT = "agent_technical"
TOOL_RESULT_CHARS = 6000

SYSTEM_PROMPT = """You are the technical analysis agent in a Nifty 50 research app.
Rules:
- Use the tools to get every number. Never quote a price, return or indicator you did not get from a tool.
- Only Nifty 50 stocks are covered. If a tool says a stock is not covered, say so plainly.
- top_movers shows only the best and worst few stocks. It is NOT the list of available stocks: for "which stocks are
  available / covered" call list_stocks and report all of them.
- Call only the tools you need. Usually one to three calls are enough.
- State the data date (as_of) once. If a tool returns a caveat or note, pass it on in one short sentence.
- Describe what the indicators show (trend, momentum, volatility). Do not promise returns. Do not say buy or sell.
- Keep the answer short: a few lines or a small list, not an essay."""

REMINDER = ("You must call at least one tool to get the data before you answer. "
            "Do not write numbers from memory or placeholders. Call the right tool now.")
NO_DATA_ANSWER = ("I have no tool data for this question, so I will not guess numbers. "
                  "Try naming one of the Nifty 50 stocks, for example: 'How is TCS doing technically?'")


class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    stop: str
    reminders: int


@dataclass
class TechnicalResult:
    answer: str
    tool_trace: list[dict] = field(default_factory=list)
    budget: dict = field(default_factory=dict)
    stopped_early: str = ""
    call_ids: list[int] = field(default_factory=list)
    reminders: int = 0
    alerts: list[str] = field(default_factory=list)       # guardrail alerts read from tool results, shown as GUARDRAIL ALERT


# ---------------------------------------------------------------------------------------------- the tools
def make_tools(call) -> list[BaseTool]:
    """The tools this agent may use. `call(name, arguments)` runs one tool on the MCP server and returns text."""

    @tool
    def get_latest_quote(symbol: str) -> str:
        """Latest close, previous close, percent change, volume and delivery percent for one Nifty 50 stock."""
        return call("get_latest_quote", {"symbol": symbol})

    @tool
    def get_ohlcv(symbol: str, days: int = 30) -> str:
        """Daily open, high, low, close, volume and delivery percent for the last `days` trading days (maximum 260)."""
        return call("get_ohlcv", {"symbol": symbol, "days": days})

    @tool
    def get_returns(symbol: str) -> str:
        """Percent return over 1 day, 1 week, 1 month, 3 months, 6 months and 1 year."""
        return call("get_returns", {"symbol": symbol})

    @tool
    def get_52w_high_low(symbol: str) -> str:
        """52-week high and low and how far the latest close is from each."""
        return call("get_52w_high_low", {"symbol": symbol})

    @tool
    def get_delivery_pct(symbol: str, days: int = 20) -> str:
        """Average and latest delivery percent over the last `days` trading days."""
        return call("get_delivery_pct", {"symbol": symbol, "days": days})

    @tool
    def get_indicators(symbol: str) -> str:
        """Latest SMA 20/50/200, EMA 20, RSI 14, MACD, Bollinger bands and ATR 14."""
        return call("get_indicators", {"symbol": symbol})

    @tool
    def compare_stocks(symbols: list[str]) -> str:
        """Compare 2 to 6 stocks side by side: close, returns, RSI and distance from the 52-week high."""
        return call("compare_stocks", {"symbols": symbols})

    @tool
    def top_movers(period: str = "1M", n: int = 5) -> str:
        """Best and worst `n` Nifty 50 stocks by return. period is one of 1D, 1W, 1M, 3M, 6M, 1Y."""
        return call("top_movers", {"period": period, "n": n})

    @tool
    def data_status() -> str:
        """Date range, row count and build time of the price data, plus the price caveat."""
        return call("data_status", {})

    @tool
    def list_stocks() -> str:
        """All Nifty 50 stocks this app has data for: symbol, company name and industry group. Use for 'which stocks are available'."""
        return call("list_stocks", {})

    return [get_latest_quote, get_ohlcv, get_returns, get_52w_high_low, get_delivery_pct,
            get_indicators, compare_stocks, top_movers, data_status, list_stocks]


# ---------------------------------------------------------------------------------------------- the agent
class TechnicalAgent:
    # Overridden by agent_fundamental.py, which reuses this loop with other tools and another prompt.
    agent_name = AGENT
    system_prompt = SYSTEM_PROMPT
    extra_rules = ""             # lines the Admin Guardrails tab adds to the prompt (see guardrail_rules.prompt_block)
    reminder = REMINDER
    no_data_answer = NO_DATA_ANSWER

    def __init__(self, gateway, server, tool_names: list[str] | None = None):
        self.gateway = gateway
        self.server = server
        self._lock = threading.Lock()
        tools = self._make_tools()
        self.tools = [t for t in tools if tool_names is None or t.name in tool_names]
        self.tool_definitions = [convert_to_openai_tool(t) for t in self.tools]
        self._graph = self._build()

    def _make_tools(self) -> list[BaseTool]:
        return make_tools(self._run_tool)

    # ------------------------------------------------------------------ public
    def run(self, question: str, *, session: str = "", parent_call_id: int | None = None,
            budget: Budget | None = None, route: str = "technical", focus: str = "") -> TechnicalResult:
        """`focus` is one extra rule for the system prompt, used when another agent answers the other half of the question."""
        budget = budget or Budget()
        self._ctx = {"session": session, "parent": parent_call_id, "budget": budget, "route": route,
                     "question": question, "call_ids": [], "stop": "", "alerts": []}
        system = self.system_prompt + self.extra_rules + (f"\n- {focus}" if focus else "")
        budget.enter_agent(self.agent_name)
        try:
            state = self._graph.invoke(
                {"messages": [SystemMessage(system), HumanMessage(question)], "stop": "", "reminders": 0},
                config={"recursion_limit": 60})
        finally:
            budget.leave_agent()
        stop = state["stop"] or self._ctx["stop"]
        final = self._last_text(state["messages"])
        if stop and not final:
            final = f"I could not finish this: {stop}."
        return TechnicalResult(answer=final, tool_trace=self._trace(state["messages"]), budget=budget.summary(),
                               stopped_early=stop, call_ids=self._ctx["call_ids"], reminders=state["reminders"],
                               alerts=dedupe(self._ctx["alerts"]))

    # ------------------------------------------------------------------ graph
    def _build(self):
        g = StateGraph(State)
        g.add_node("model", self._model_node)
        g.add_node("tools", ToolNode(self.tools))
        g.add_node("remind", self._remind_node)
        g.add_node("refuse", self._refuse_node)
        g.set_entry_point("model")
        g.add_conditional_edges("model", self._after_model,
                                {"tools": "tools", "remind": "remind", "refuse": "refuse", "end": END})
        g.add_conditional_edges("tools", lambda s: "end" if self._ctx["stop"] else "model",
                                {"model": "model", "end": END})
        g.add_edge("remind", "model")
        g.add_edge("refuse", END)
        return g.compile()

    def _model_node(self, state: State) -> dict:
        ctx = self._ctx
        try:
            ctx["budget"].before_model_call()
        except BudgetExceeded as exc:
            return {"stop": str(exc)}
        result = self.gateway.chat(
            "chat", self._neutral(state["messages"]), self.tool_definitions, session=ctx["session"], agent=self.agent_name,
            node="model", route=ctx["route"], parent_call_id=ctx["parent"], preview=ctx["question"])
        ctx["budget"].after_model_call(result.tokens_in, result.tokens_out, getattr(result, "cost", None))
        if result.call_id:
            ctx["call_ids"].append(result.call_id)
        calls = [{"id": c["id"], "name": c["name"], "args": c.get("arguments") or {}, "type": "tool_call"}
                 for c in result.tool_calls]
        return {"messages": [AIMessage(content=result.text or "", tool_calls=calls)]}

    def _after_model(self, state: State) -> str:
        if state["stop"]:
            return "end"
        if state["messages"][-1].tool_calls:
            return "tools"
        if any(isinstance(m, ToolMessage) for m in state["messages"]):
            return "end"                                          # answered after using tools
        return "remind" if state["reminders"] < 1 else "refuse"   # answered with no data at all

    def _remind_node(self, state: State) -> dict:
        return {"messages": [HumanMessage(self.reminder)], "reminders": state["reminders"] + 1}

    def _refuse_node(self, state: State) -> dict:
        return {"messages": [AIMessage(self.no_data_answer)], "stop": "model answered without tool data"}

    # ------------------------------------------------------------------ tool execution and conversions
    def _run_tool(self, name: str, arguments: dict) -> str:
        """Runs inside ToolNode. Checks the shared budget, then calls the MCP server."""
        with self._lock:
            try:
                self._ctx["budget"].before_tool_call()
            except BudgetExceeded as exc:
                self._ctx["stop"] = str(exc)
                return '{"error": "' + str(exc) + '"}'
        text = self._call(name, arguments)
        with self._lock:                                   # read the whole result: the cut below could drop the guardrail part
            self._ctx["alerts"] += alerts_from_tool_text(text)
        return text[:TOOL_RESULT_CHARS]

    def _call(self, name: str, arguments: dict) -> str:
        return self.server.call(name, arguments)

    @staticmethod
    def _neutral(messages: list) -> list[dict]:
        """LangChain messages -> the neutral message format the gateway takes."""
        out = []
        for m in messages:
            if isinstance(m, SystemMessage):
                out.append({"role": "system", "content": m.content})
            elif isinstance(m, HumanMessage):
                out.append({"role": "user", "content": m.content})
            elif isinstance(m, ToolMessage):
                out.append({"role": "tool", "tool_call_id": m.tool_call_id, "name": m.name, "content": m.content})
            elif isinstance(m, AIMessage):
                msg = {"role": "assistant", "content": m.content}
                if m.tool_calls:
                    msg["tool_calls"] = [{"id": c["id"], "name": c["name"], "arguments": c["args"]}
                                         for c in m.tool_calls]
                out.append(msg)
        return out

    @staticmethod
    def _trace(messages: list) -> list[dict]:
        results = {m.tool_call_id: m for m in messages if isinstance(m, ToolMessage)}
        return [{"tool": c["name"], "arguments": c["args"], "ok": results[c["id"]].status != "error"
                 if c["id"] in results else False, "result_chars": len(str(results[c["id"]].content))
                 if c["id"] in results else 0}
                for m in messages if isinstance(m, AIMessage) for c in m.tool_calls]

    @staticmethod
    def _last_text(messages: list) -> str:
        for m in reversed(messages):
            if isinstance(m, AIMessage) and str(m.content).strip():
                return str(m.content).strip()
        return ""
