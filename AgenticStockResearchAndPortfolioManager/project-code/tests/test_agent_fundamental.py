"""agent_fundamental with a scripted gateway (no model) and the real fundamentals MCP server."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent_fundamental import FundamentalAgent  # noqa: E402
from budget import Budget  # noqa: E402
from mcp_client import McpServer  # noqa: E402
from providers import ChatResult  # noqa: E402


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
    with McpServer("fundamentals", "mcp_fundamentals.py") as s:
        yield s


def test_tools_match_the_mcp_server_exactly(server):
    from langchain_core.tools import BaseTool
    agent = FundamentalAgent(ScriptedGateway(), server)
    assert all(isinstance(t, BaseTool) for t in agent.tools)
    assert sorted(t.name for t in agent.tools) == sorted(server.tool_names())
    names = sorted(t.name for t in agent.tools)
    assert names == ["fsa_compute_growth", "fsa_compute_ratios", "fsa_coverage", "fsa_get_financials",
                     "fsa_get_quarterly", "fsa_get_valuation", "fsa_list_line_items", "rag_search_documents",
                     "screener_get_history", "screener_get_snapshot", "screener_get_table"]
    defs = {d["function"]["name"]: d["function"] for d in agent.tool_definitions}
    assert defs["fsa_get_financials"]["parameters"]["required"] == ["symbol", "section"]
    assert defs["fsa_compute_growth"]["parameters"]["properties"]["years"]["type"] == "integer"
    assert "cagr_pct" in defs["fsa_compute_growth"]["description"]


def test_tool_then_answer_uses_real_workbook_numbers(server):
    gw = ScriptedGateway(tool_call("fsa_get_financials", symbol="TCS", section="profit_loss", labels=["Sales"], periods=2),
                         say("TCS sales were ..."))
    out = FundamentalAgent(gw, server).run("TCS sales?", session="s1")
    tool_msg = gw.calls[1]["messages"][-1]
    assert tool_msg["role"] == "tool" and "Sales" in tool_msg["content"] and "error" not in tool_msg["content"]
    data = json.loads(tool_msg["content"])
    assert data                                         # real rows came back from fundamentals.duckdb
    assert [t["tool"] for t in out.tool_trace] == ["fsa_get_financials"] and out.tool_trace[0]["ok"]
    assert out.budget == {"model_calls": 2, "tool_calls": 1, "tokens": 270, "cost": 0.0}


def test_gateway_is_called_with_role_chat_and_this_agents_name(server):
    gw = ScriptedGateway(tool_call("fsa_coverage"), say("SBILIFE has no workbook."))
    out = FundamentalAgent(gw, server).run("Which stocks lack data?", session="s9")
    assert "SBILIFE" in gw.calls[1]["messages"][-1]["content"]
    assert all(c["role"] == "chat" and c["agent"] == "agent_fundamental" and c["route"] == "fundamental"
               and c["session"] == "s9" for c in gw.calls)
    assert "fundamental analysis agent" in gw.calls[0]["messages"][0]["content"]
    assert out.answer == "SBILIFE has no workbook."


def test_missing_workbook_and_non_nifty_symbol_come_back_as_errors(server):
    gw = ScriptedGateway(tool_call("fsa_get_valuation", symbol="SBILIFE"), tool_call("fsa_get_valuation", symbol="AAPL"),
                         say("not available"))
    FundamentalAgent(gw, server).run("valuation?")
    assert "error" in gw.calls[1]["messages"][-1]["content"]
    assert "error" in gw.calls[2]["messages"][-1]["content"]


def test_bank_ratios_carry_the_warning_and_no_industrial_measures(server):
    gw = ScriptedGateway(tool_call("fsa_compute_ratios", symbol="HDFCBANK", periods=3), say("ok"))
    FundamentalAgent(gw, server).run("HDFC Bank ratios?")
    content = gw.calls[1]["messages"][-1]["content"].lower()
    assert "warning" in content or "bank" in content
    assert "interest_cover" not in content and "debt_to_equity" not in content


def test_bad_arguments_and_unknown_tool_go_back_to_the_model(server):
    gw = ScriptedGateway(tool_call("fsa_get_valuation"), tool_call("get_latest_quote", symbol="TCS"), say("done"))
    FundamentalAgent(gw, server).run("x")
    assert "Field required" in gw.calls[1]["messages"][-1]["content"]
    assert "not a valid tool" in gw.calls[2]["messages"][-1]["content"]      # technical tools are not offered here


def test_answer_without_tool_data_is_rejected_once_then_refused(server):
    gw = ScriptedGateway(say("TCS profit is 99999"), say("still invented"))
    out = FundamentalAgent(gw, server).run("TCS profit?")
    assert "no tool data" in out.answer.lower() and "99999" not in out.answer
    assert "must call" in gw.calls[1]["messages"][-1]["content"] and out.reminders == 1


def test_budget_limit_applies(server):
    gw = ScriptedGateway(*[tool_call("fsa_coverage") for _ in range(5)])
    out = FundamentalAgent(gw, server).run("loop", budget=Budget(max_tool_calls=1))
    assert "tool call limit" in out.stopped_early and out.budget["tool_calls"] == 1


def test_parallel_tool_calls_do_not_collide_on_the_database(server):
    """The model can ask for several tools in one turn; ToolNode runs them in parallel threads."""
    import threading
    results = []

    def go(section):
        results.append(server.call("fsa_get_financials", {"symbol": "TCS", "section": section, "periods": 3}))

    for _ in range(5):
        results.clear()
        threads = [threading.Thread(target=go, args=(s,)) for s in ["profit_loss", "balance_sheet", "cash_flow", "derived"]]
        [t.start() for t in threads]
        [t.join() for t in threads]
        assert len(results) == 4 and all('"rows": [{' in r for r in results), results


def test_rag_search_documents_is_offered_and_checks_its_arguments(server):
    agent = FundamentalAgent(ScriptedGateway(), server)
    assert "rag_search_documents" in [t.name for t in agent.tools]
    gw = ScriptedGateway(tool_call("rag_search_documents"), tool_call("rag_search_documents", query="risks", doc_type="tweet"),
                         say("done"))
    FundamentalAgent(gw, server).run("risks?")
    assert "Field required" in gw.calls[1]["messages"][-1]["content"]
    assert "doc_type" in gw.calls[2]["messages"][-1]["content"]            # rejected before any model call is made


def test_screener_table_question_gets_pe_rsi_opm_npm_from_the_snapshot_data(server):
    gw = ScriptedGateway(tool_call("screener_get_table", metrics=["pe", "rsi", "opm", "npm"], sort_by="pe", descending=False, limit=3),
                         say("done"))
    agent = FundamentalAgent(gw, server)
    res = agent.run("show me Nifty 50 stocks with PE RSI OPM NPM", session="s")
    reply = json.loads(gw.calls[1]["messages"][-1]["content"])
    assert reply["columns"] == ["symbol", "price_to_earning", "rsi", "opm_latest_quarter", "npm_latest_quarter"]
    assert reply["count"] == 3 and reply["as_of"] and "snapshot" in reply["caveat"].lower()
    assert res.tool_trace[0]["tool"] == "screener_get_table"


def test_screener_tools_return_errors_as_text_not_crashes(server):
    gw = ScriptedGateway(tool_call("screener_get_table", metrics=["magic"]), tool_call("screener_get_snapshot", symbol="TESLA"),
                         tool_call("screener_get_history", symbol="TCS", metric="industry_group"), say("ok"))
    agent = FundamentalAgent(gw, server)
    agent.run("x", session="s")
    texts = [m["content"] for c in gw.calls[1:] for m in c["messages"] if m.get("role") == "tool"]
    assert any("Unknown metric" in t for t in texts) and any("Nifty 50" in t for t in texts)


def test_screener_snapshot_and_history_use_real_data(server):
    gw = ScriptedGateway(tool_call("screener_get_snapshot", symbol="SBILIFE"), tool_call("screener_get_history", symbol="TCS", metric="pe"),
                         say("ok"))
    agent = FundamentalAgent(gw, server)
    agent.run("x", session="s")
    tool_msgs = [json.loads(m["content"]) for m in gw.calls[-1]["messages"] if m.get("role") == "tool"]
    snap = next(t for t in tool_msgs if "values" in t)
    assert snap["symbol"] == "SBILIFE" and snap["values"]["price_to_earning"] is not None        # no workbook, but the CSV has it
    hist = next(t for t in tool_msgs if t.get("metric"))
    assert hist["metric"] == "price_to_earning" and hist["count"] > 10
