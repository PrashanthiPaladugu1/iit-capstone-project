"""agent_technical with a scripted gateway (no model) and the real market-data MCP server."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent_technical import TechnicalAgent  # noqa: E402
from budget import Budget, BudgetExceeded  # noqa: E402
from mcp_client import McpClientError, McpServer  # noqa: E402
from providers import ChatResult  # noqa: E402


class ScriptedGateway:
    """Returns the prepared ChatResults in order and records what it was asked."""

    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def chat(self, role, messages, tools=None, **kw):
        self.calls.append({"role": role, "messages": [dict(m) for m in messages], "tools": tools, **kw})
        res = self.results.pop(0)
        res.call_id = len(self.calls)
        return res


_ids = iter(range(1, 10_000))


def tool_call(name, **args):
    return ChatResult(text="", tool_calls=[{"id": f"call-{next(_ids)}", "name": name, "arguments": args}],
                      tokens_in=100, tokens_out=10)


def say(text):
    return ChatResult(text=text, tokens_in=120, tokens_out=40)


@pytest.fixture(scope="module")
def server():
    with McpServer("market-data", "mcp_market_data.py") as s:
        yield s


def test_tool_then_answer_uses_real_tool_output(server):
    gw = ScriptedGateway(tool_call("get_latest_quote", symbol="TCS"), say("TCS closed at 2407.5."))
    out = TechnicalAgent(gw, server).run("How is TCS?", session="s1")
    assert out.answer == "TCS closed at 2407.5."
    assert [t["tool"] for t in out.tool_trace] == ["get_latest_quote"]
    tool_msg = gw.calls[1]["messages"][-1]
    assert tool_msg["role"] == "tool" and "2407.5" in tool_msg["content"]
    assert out.budget == {"model_calls": 2, "tool_calls": 1, "tokens": 270, "cost": 0.0}
    assert all(c["role"] == "chat" and c["agent"] == "agent_technical" and c["session"] == "s1" for c in gw.calls)


def test_unknown_tool_and_non_nifty_symbol_are_reported_to_the_model(server):
    gw = ScriptedGateway(tool_call("get_latest_quote", symbol="AAPL"), tool_call("buy_stock", symbol="TCS"),
                         say("AAPL is not covered."))
    out = TechnicalAgent(gw, server).run("AAPL?")
    assert "not one of the Nifty 50" in gw.calls[1]["messages"][-1]["content"]
    assert "not a valid tool" in gw.calls[2]["messages"][-1]["content"]
    assert out.answer == "AAPL is not covered."


def test_tools_are_langchain_tools_with_typed_arguments(server):
    from langchain_core.tools import BaseTool
    agent = TechnicalAgent(ScriptedGateway(), server)
    assert all(isinstance(t, BaseTool) for t in agent.tools)
    names = [t.name for t in agent.tools]
    assert sorted(names) == sorted(server.tool_names())                       # one @tool per MCP tool, none missing or extra
    defs = {d["function"]["name"]: d["function"] for d in agent.tool_definitions}
    assert defs["get_ohlcv"]["parameters"]["properties"]["days"]["type"] == "integer"
    assert defs["compare_stocks"]["parameters"]["properties"]["symbols"]["type"] == "array"
    assert defs["get_returns"]["parameters"]["required"] == ["symbol"]
    assert "52-week high and low" in defs["get_52w_high_low"]["description"]


def test_bad_arguments_go_back_to_the_model_as_an_error(server):
    gw = ScriptedGateway(tool_call("get_returns"), tool_call("get_returns", symbol="TCS"), say("done"))
    out = TechnicalAgent(gw, server).run("x")
    assert "Field required" in gw.calls[1]["messages"][-1]["content"]
    assert [t["ok"] for t in out.tool_trace] == [False, True] and out.budget["tool_calls"] == 1


def test_only_listed_tools_are_offered(server):
    gw = ScriptedGateway(say("ok"), say("ok"))
    TechnicalAgent(gw, server, tool_names=["get_returns"]).run("x")
    assert [t["function"]["name"] for t in gw.calls[0]["tools"]] == ["get_returns"]


def test_model_call_limit_stops_the_loop(server):
    gw = ScriptedGateway(*[tool_call("get_returns", symbol="TCS") for _ in range(5)])
    out = TechnicalAgent(gw, server).run("loop", budget=Budget(max_model_calls=2))
    assert "model call limit" in out.stopped_early and out.budget["model_calls"] == 2
    assert out.answer.startswith("I could not finish")


def test_tool_call_limit_stops_the_loop(server):
    gw = ScriptedGateway(*[tool_call("get_returns", symbol="TCS") for _ in range(5)])
    out = TechnicalAgent(gw, server).run("loop", budget=Budget(max_tool_calls=1))
    assert "tool call limit" in out.stopped_early and out.budget["tool_calls"] == 1


def test_token_limit_stops_before_the_next_model_call(server):
    gw = ScriptedGateway(tool_call("get_returns", symbol="TCS"), say("never reached"))
    out = TechnicalAgent(gw, server).run("x", budget=Budget(max_tokens=50))
    assert "token limit" in out.stopped_early and len(gw.calls) == 1


def test_answer_without_any_tool_call_is_not_accepted(server):
    """mistral:7b answered with invented numbers and no tool call. One reminder, then a refusal to answer."""
    gw = ScriptedGateway(say("TCS closed at 9999 [close_price]"), tool_call("get_latest_quote", symbol="TCS"),
                         say("TCS closed at 2407.5."))
    out = TechnicalAgent(gw, server).run("How is TCS?")
    assert out.answer == "TCS closed at 2407.5." and out.reminders == 1
    assert "must call" in gw.calls[1]["messages"][-1]["content"]
    assert "9999" not in out.answer

    gw = ScriptedGateway(say("made up"), say("still made up"))
    out = TechnicalAgent(gw, server).run("How is TCS?")
    assert "no tool data" in out.answer.lower() and "made up" not in out.answer
    assert out.tool_trace == [] and "without tool data" in out.stopped_early


def test_depth_limit_and_budget_is_shared_across_agents():
    b = Budget(max_depth=1)
    b.enter_agent("agent_a")
    with pytest.raises(BudgetExceeded):
        b.enter_agent("agent_b")
    b.leave_agent()
    b.enter_agent("agent_b")


def test_server_start_and_call_errors():
    with McpServer("market-data", "mcp_market_data.py") as s:
        with pytest.raises(McpClientError):
            s.call("no_such_tool", {})
        assert "error" in s.call("get_ohlcv", {"symbol": "TCS", "days": "abc"})
    bad = McpServer("broken", "does_not_exist.py")
    with pytest.raises(McpClientError):
        bad.start()
