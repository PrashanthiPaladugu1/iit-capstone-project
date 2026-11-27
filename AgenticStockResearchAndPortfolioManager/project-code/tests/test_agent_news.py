"""agent_news: scripted gateway (no model) and a fake MCP server, plus the real `news` MCP server's tool list."""
import json
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import agent_news  # noqa: E402
from agent_news import NewsAgent  # noqa: E402
from budget import Budget  # noqa: E402
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


class FakeServer:
    def __init__(self, reply='{"symbol": "INFY", "headlines": [], "fetched_at": "2026-11-26T14:30+05:30"}'):
        self.reply, self.calls = reply, []

    def call(self, tool, arguments=None):
        self.calls.append((tool, arguments))
        return self.reply


_ids = iter(range(1, 10_000))


def tool_call(name, **args):
    return ChatResult(text="", tool_calls=[{"id": f"call-{next(_ids)}", "name": name, "arguments": args}],
                      tokens_in=100, tokens_out=10)


def say(text):
    return ChatResult(text=text, tokens_in=120, tokens_out=40)


# ------------------------------------------------------------------------------------------ standalone
def test_news_agent_is_a_separate_class_not_a_subclass_of_the_other_agents():
    import agent_fundamental
    import agent_technical
    assert NewsAgent.__mro__ == (NewsAgent, object)
    assert not issubclass(NewsAgent, agent_technical.TechnicalAgent)
    assert not issubclass(NewsAgent, agent_fundamental.FundamentalAgent)
    source = Path(agent_news.__file__).read_text()
    assert "agent_technical" not in source.replace("agent_technical.py", "").split('"""', 2)[2]    # no import of it in the code


def test_agent_offers_exactly_the_three_news_tools():
    agent = NewsAgent(ScriptedGateway(), FakeServer())
    assert {t.name for t in agent.tools} == {"news_search", "news_sentiment", "news_market"}
    assert {d["function"]["name"] for d in agent.tool_definitions} == {"news_search", "news_sentiment", "news_market"}


def test_tool_names_can_limit_what_the_agent_offers():
    assert [t.name for t in NewsAgent(ScriptedGateway(), FakeServer(), ["news_search"]).tools] == ["news_search"]


# ------------------------------------------------------------------------------------------ the loop
def test_tool_call_then_answer_returns_text_trace_and_budget():
    gw = ScriptedGateway(tool_call("news_search", stock="INFY", days=7), say("Infosys: no headlines found in the checked feeds."))
    server = FakeServer()
    out = NewsAgent(gw, server).run("Any news on Infosys?", session="s1")
    assert out.answer.startswith("Infosys: no headlines") and out.stopped_early == "" and out.reminders == 0
    assert out.tool_trace == [{"tool": "news_search", "arguments": {"stock": "INFY", "days": 7}, "ok": True,
                               "result_chars": len(server.reply)}]
    assert server.calls == [("news_search", {"stock": "INFY", "days": 7, "limit": 10})]      # defaults filled in by the tool
    assert out.budget["model_calls"] == 2 and out.budget["tool_calls"] == 1 and out.call_ids == [1, 2]


def test_the_model_gets_the_tool_result_and_the_gateway_is_told_who_is_asking():
    gw = ScriptedGateway(tool_call("news_market", days=1), say("Market headlines are listed above."))
    NewsAgent(gw, FakeServer('{"headlines": []}')).run("What is the market news today?", session="s9", parent_call_id=77, route="research")
    first, second = gw.calls
    assert first["role"] == "chat" and first["agent"] == "agent_news" and first["session"] == "s9"
    assert first["parent_call_id"] == 77 and first["route"] == "research" and first["tools"]
    assert second["messages"][-1] == {"role": "tool", "tool_call_id": second["messages"][-2]["tool_calls"][0]["id"],
                                      "name": "news_market", "content": '{"headlines": []}'}


def test_system_prompt_forbids_prediction_and_requires_tool_data():
    gw = ScriptedGateway(tool_call("news_search", stock="TCS"), say("ok"))
    NewsAgent(gw, FakeServer()).run("TCS news", focus="Answer only the news part.")
    system = gw.calls[0]["messages"][0]["content"]
    assert "Never write a headline" in system and "Do not predict" in system and "buy, sell or hold" in system
    assert "headlines only" in system.lower() and system.endswith("- Answer only the news part.")

def test_system_prompt_asks_for_one_tool_and_the_fetched_time_copied_exactly():
    system = agent_news.SYSTEM_PROMPT
    assert "one tool" in system and "not both" in system
    assert "copy fetched_at exactly" in system.lower()




def test_an_answer_with_no_tool_call_gets_one_reminder_then_a_refusal():
    gw = ScriptedGateway(say("Infosys is up 3% on great news!"), say("Still from memory."))
    out = NewsAgent(gw, FakeServer()).run("Any news on Infosys?")
    assert out.answer == agent_news.NO_DATA_ANSWER and out.stopped_early == "model answered without tool data"
    assert out.reminders == 1 and out.tool_trace == [] and len(gw.calls) == 2
    assert gw.calls[1]["messages"][-1]["content"] == agent_news.REMINDER


def test_a_reminder_that_works_leads_to_a_normal_answer():
    gw = ScriptedGateway(say("From memory."), tool_call("news_search", stock="INFY"), say("No headlines found."))
    out = NewsAgent(gw, FakeServer()).run("Any news on Infosys?")
    assert out.answer == "No headlines found." and out.reminders == 1 and out.stopped_early == ""


def test_a_bad_argument_goes_back_to_the_model_as_an_error_and_it_can_retry():
    gw = ScriptedGateway(tool_call("news_search", stock="INFY", days="lots"), tool_call("news_search", stock="INFY", days=7),
                         say("No headlines found."))
    server = FakeServer()
    out = NewsAgent(gw, server).run("Any news on Infosys?")
    assert [t["ok"] for t in out.tool_trace] == [False, True] and len(server.calls) == 1
    assert "days" in gw.calls[1]["messages"][-1]["content"] and out.answer == "No headlines found."


def test_an_unknown_tool_name_is_an_error_message_not_a_crash():
    gw = ScriptedGateway(tool_call("get_stock_tweets", stock="INFY"), tool_call("news_search", stock="INFY"), say("Done."))
    out = NewsAgent(gw, FakeServer()).run("q")
    assert "unknown tool 'get_stock_tweets'" in gw.calls[1]["messages"][-1]["content"] and out.answer == "Done."


def test_a_tool_that_returns_an_error_is_marked_not_ok():
    gw = ScriptedGateway(tool_call("news_search", stock="Wipro"), say("Wipro is not a Nifty 50 stock."))
    out = NewsAgent(gw, FakeServer('{"error": "\'Wipro\' is not a Nifty 50 stock this app covers"}')).run("news on Wipro")
    assert out.tool_trace[0]["ok"] is False


def test_a_server_failure_is_returned_to_the_model_and_the_run_goes_on():
    class Broken(FakeServer):
        def call(self, tool, arguments=None):
            raise RuntimeError("news server went away")

    gw = ScriptedGateway(tool_call("news_search", stock="TCS"), say("The news source is not available."))
    out = NewsAgent(gw, Broken()).run("TCS news")
    assert out.tool_trace[0]["ok"] is False and "news server went away" in gw.calls[1]["messages"][-1]["content"]


def test_long_tool_results_are_cut_to_6000_characters():
    gw = ScriptedGateway(tool_call("news_market"), say("ok"))
    NewsAgent(gw, FakeServer("x" * 20_000)).run("market news")
    assert len(gw.calls[1]["messages"][-1]["content"]) == 6000


def test_several_tool_calls_in_one_reply_are_all_run_and_all_traced():
    two = ChatResult(text="", tool_calls=[{"id": "a", "name": "news_search", "arguments": {"stock": "INFY"}},
                                          {"id": "b", "name": "news_search", "arguments": {"stock": "TCS"}}],
                     tokens_in=100, tokens_out=10)
    out = NewsAgent(ScriptedGateway(two, say("Both listed.")), FakeServer()).run("INFY and TCS news")
    assert [t["arguments"]["stock"] for t in out.tool_trace] == ["INFY", "TCS"] and out.budget["tool_calls"] == 2


# ------------------------------------------------------------------------------------------ the shared budget
def test_tool_call_limit_stops_the_run_and_says_what_stopped_it():
    gw = ScriptedGateway(tool_call("news_search", stock="INFY"), tool_call("news_search", stock="TCS"))
    out = NewsAgent(gw, FakeServer()).run("q", budget=Budget(max_tool_calls=1))
    assert "tool call limit" in out.stopped_early and out.answer.startswith("I could not finish this")


def test_model_call_limit_stops_the_run():
    out = NewsAgent(ScriptedGateway(), FakeServer()).run("q", budget=Budget(max_model_calls=0))
    assert "model call limit" in out.stopped_early and out.tool_trace == []


def test_the_agent_counts_as_one_level_of_depth_and_leaves_it_after_the_run():
    b = Budget(max_depth=3)
    b.enter_agent("agent_research_analyst")
    NewsAgent(ScriptedGateway(tool_call("news_market"), say("ok")), FakeServer()).run("q", budget=b)
    assert b.depth == 1                                                        # back to the analyst's level
    with pytest.raises(Exception, match="depth limit"):
        b2 = Budget(max_depth=1)
        b2.enter_agent("analyst")
        NewsAgent(ScriptedGateway(), FakeServer()).run("q", budget=b2)


def test_a_looping_model_is_stopped_by_the_step_limit():
    gw = ScriptedGateway(*[tool_call("news_market") for _ in range(agent_news.MAX_STEPS + 2)])
    out = NewsAgent(gw, FakeServer()).run("q", budget=Budget(max_model_calls=100, max_tool_calls=100, max_tokens=10**7))
    assert out.stopped_early.startswith("step limit reached") and len(gw.calls) == agent_news.MAX_STEPS


# ------------------------------------------------------------------------------------------ thread safety
def test_one_agent_can_answer_two_questions_at_the_same_time():
    both_inside = threading.Barrier(2, timeout=5)

    class Waiting(ScriptedGateway):
        def chat(self, role, messages, tools=None, **kw):
            both_inside.wait()                                                 # both runs are inside the model call together
            question = messages[1]["content"]
            return ChatResult(text="", tool_calls=[{"id": "t", "name": "news_search", "arguments": {"stock": question}}],
                              tokens_in=1, tokens_out=1) if len(messages) == 2 else ChatResult(text=f"answer to {question}",
                                                                                              tokens_in=1, tokens_out=1)

    agent = NewsAgent(Waiting(), FakeServer())
    out = {}

    def ask(q):
        out[q] = agent.run(q)

    threads = [threading.Thread(target=ask, args=(q,)) for q in ("INFY", "TCS")]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert out["INFY"].answer == "answer to INFY" and out["TCS"].answer == "answer to TCS"
    assert out["INFY"].tool_trace[0]["arguments"] == {"stock": "INFY"} and out["TCS"].tool_trace[0]["arguments"] == {"stock": "TCS"}


# ------------------------------------------------------------------------------------------ the real MCP server
def test_agent_works_against_the_real_news_server_for_a_bad_stock_name():
    from mcp_client import McpServer
    with McpServer("news", "mcp_news.py") as server:
        assert set(server.tool_names()) == {"news_search", "news_sentiment", "news_market"}
        gw = ScriptedGateway(tool_call("news_search", stock="Wipro"), say("Wipro is not covered."))
        out = NewsAgent(gw, server).run("news on Wipro")
        assert "not a Nifty 50 stock" in gw.calls[1]["messages"][-1]["content"] and out.tool_trace[0]["ok"] is False
        assert json.loads(server.call("news_search", {"stock": "TCS", "days": 99}))["error"].startswith("days must be")
