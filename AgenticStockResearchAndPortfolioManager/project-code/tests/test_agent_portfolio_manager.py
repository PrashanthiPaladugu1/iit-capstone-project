"""agent_portfolio_manager: scripted gateway (no model) and the real portfolio MCP server on the real data."""
import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent_portfolio_manager import PortfolioManager  # noqa: E402
from mcp_client import McpServer  # noqa: E402
from providers import ChatResult  # noqa: E402
from router import route  # noqa: E402


class ScriptedGateway:
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
    with McpServer("portfolio", "mcp_portfolio.py") as s:
        yield s


def tool_message(gw, index):
    return gw.calls[index]["messages"][-1]


# ----------------------------------------------------------------------------------------------- the MCP server
def test_server_lists_the_four_portfolio_tools():
    import mcp_portfolio as server
    res = asyncio.run(server.mcp.list_tools())
    names = {t.name for t in (res.tools if hasattr(res, "tools") else res)}
    assert names == {"portfolio_scorecard", "portfolio_suggest", "portfolio_build", "portfolio_evaluate"}


def test_agent_offers_only_the_portfolio_tools(server):
    agent = PortfolioManager(ScriptedGateway(), server)
    assert {t.name for t in agent.tools} == {"portfolio_scorecard", "portfolio_suggest", "portfolio_build", "portfolio_evaluate"}
    assert agent.agent_name == "agent_portfolio_manager"


# ----------------------------------------------------------------------------------------------- the agent loop on real tools
def test_build_a_portfolio_the_model_sees_real_picks_weights_and_guardrails(server):
    gw = ScriptedGateway(tool_call("portfolio_build", strategy="low_risk", size=5, weighting="inverse_vol"),
                         say("Here is a 5-stock low-risk portfolio."))
    out = PortfolioManager(gw, server).run("Build a 5-stock low-risk portfolio", session="s1")
    assert out.answer == "Here is a 5-stock low-risk portfolio."
    assert [t["tool"] for t in out.tool_trace] == ["portfolio_build"]
    data = json.loads(tool_message(gw, 1)["content"])
    assert len(data["picks"]) == 5 and abs(sum(data["weights"].values()) - 100) < 0.05
    assert data["guardrails"]["ok"] is True and data["backtest"]["window"]["trading_days"] >= 200
    assert "not investment advice" in data["footer"].lower()
    assert all(c["role"] == "chat" and c["agent"] == "agent_portfolio_manager" for c in gw.calls)


def test_a_stock_outside_the_nifty_50_is_reported_to_the_model_not_added(server):
    gw = ScriptedGateway(tool_call("portfolio_evaluate", symbols=["TCS", "INFY", "TESLA", "ITC"]),
                         say("Tesla is not in the Nifty 50."))
    PortfolioManager(gw, server).run("Add Tesla and Infosys to my portfolio")
    data = json.loads(tool_message(gw, 1)["content"])
    assert data["guardrails"]["ok"] is False and data["backtest"] is None
    assert any("G1" in b and "TESLA" in b for b in data["guardrails"]["blocks"])


def test_a_size_outside_4_to_6_comes_back_as_an_error_message(server):
    gw = ScriptedGateway(tool_call("portfolio_suggest", strategy="balanced", size=8), say("A portfolio holds 4 to 6 stocks."))
    PortfolioManager(gw, server).run("Build a portfolio of 8 stocks")
    assert "4 to 6" in tool_message(gw, 1)["content"] and "error" in tool_message(gw, 1)["content"]


def test_scorecard_result_is_small_enough_for_the_tool_result_limit(server):
    from agent_technical import TOOL_RESULT_CHARS
    text = server.call("portfolio_scorecard", {"strategy": "balanced", "limit": 25})
    assert len(text) < TOOL_RESULT_CHARS and json.loads(text)["rows"]
    big = server.call("portfolio_scorecard", {"strategy": "balanced", "limit": 50})
    assert len(json.loads(big)["rows"]) <= 25                                  # capped so the model never gets cut-off JSON


def test_build_result_fits_the_tool_result_limit_for_six_stocks(server):
    from agent_technical import TOOL_RESULT_CHARS
    text = server.call("portfolio_build", {"strategy": "balanced", "size": 6, "weighting": "equal"})
    assert len(text) < TOOL_RESULT_CHARS and json.loads(text)["picks"]


def test_the_prompt_carries_the_rules_that_code_cannot_enforce(server):
    prompt = PortfolioManager(ScriptedGateway(), server).system_prompt.lower()
    for needle in ("4 to 6", "not investment advice", "past", "guardrail", "different strategy"):
        assert needle in prompt, needle


def test_no_tool_means_no_invented_portfolio(server):
    gw = ScriptedGateway(say("Buy TCS 40% and INFY 30%."), say("Buy TCS 40% and INFY 30%."))
    out = PortfolioManager(gw, server).run("Build a portfolio")
    assert "no tool data" in out.answer.lower() and out.stopped_early


# ----------------------------------------------------------------------------------------------- routing
@pytest.mark.parametrize("question", [
    "Make a 5-stock low-risk portfolio",
    "Give me 2 portfolio ideas for long term and short term",
    "Build a portfolio of 8 stocks",
    "Add Tesla and Infosys to my portfolio",
    "Give me 4 different portfolio ideas, 4 to 6 stocks each",
    "can you create portfolios of nifty 50 stocks",
])
def test_portfolio_questions_go_to_the_portfolio_route(question):
    assert route(question) == "portfolio"


@pytest.mark.parametrize("question,expected", [
    ("What did TCS management say about its portfolio of services?", "documents"),     # a document word still wins
    ("What is the RSI of TCS?", "technical"),
    ("Revenue growth and RSI of ITC", "both"),
])
def test_other_routes_are_unchanged(question, expected):
    assert route(question) == expected
