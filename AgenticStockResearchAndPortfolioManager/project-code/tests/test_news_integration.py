"""The research analyst calling agent_news as an optional third specialist, and the news route.

Scripted gateway and fake specialists: no model, no network.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ui_app  # noqa: E402
from agent_research_analyst import ResearchAnalyst, SPLIT_PROMPT, SPLIT_PROMPT_NEWS, parse_parts, parse_split  # noqa: E402
from router import route  # noqa: E402
from test_agent_research_analyst import FakeSpecialist, ScriptedGateway, say  # noqa: E402
from test_ui_app import FakeAgent, FakeAnalyst, make  # noqa: E402

SPLIT_3 = ('{"technical": "RSI of TCS?", "fundamental": "Revenue growth of TCS?", '
           '"news": "Latest headlines on TCS?"}')
SPLIT_NEWS_ONLY = '{"technical": "", "fundamental": "", "news": "Latest headlines on TCS?"}'
NEWS_TEXT = "TCS: 2 headlines. Economic Times, 25 Nov: TCS wins a large deal."
MERGED = "TCS: RSI is 55.2. Revenue grew 8.7% a year over 5 years. Economic Times, 25 Nov: TCS wins a large deal."


def build_with_news(*gateway_results, parallel=False):
    gw = ScriptedGateway(*gateway_results)
    tech = FakeSpecialist("agent_technical", "TCS RSI is 55.2.", trace=[{"tool": "get_indicators", "arguments": {"symbol": "TCS"}}])
    fund = FakeSpecialist("agent_fundamental", "TCS revenue grew 8.7% a year over 5 years.",
                          trace=[{"tool": "fsa_compute_growth", "arguments": {}}])
    news = FakeSpecialist("agent_news", NEWS_TEXT, trace=[{"tool": "news_search", "arguments": {"stock": "TCS"}}])
    return ResearchAnalyst(gw, tech, fund, parallel=parallel, news=news), gw, tech, fund, news


# ------------------------------------------------------------------------------------------ the split
def test_without_a_news_agent_the_analyst_works_exactly_as_before():
    analyst = ResearchAnalyst(ScriptedGateway(say('{"technical": "RSI?", "fundamental": "growth?"}'), say("merged 55.2")),
                              FakeSpecialist("agent_technical", "RSI is 55.2."), FakeSpecialist("agent_fundamental", "growth"))
    analyst.run("q")
    assert analyst.news is None and analyst.gateway.calls[0]["messages"][0]["content"] == SPLIT_PROMPT


def test_with_a_news_agent_the_split_prompt_offers_a_news_part_only_for_news_questions():
    analyst, gw, *_ = build_with_news(say(SPLIT_3), say(MERGED))
    analyst.run("TCS price, growth and news")
    prompt = gw.calls[0]["messages"][0]["content"]
    assert prompt == SPLIT_PROMPT_NEWS and '"news"' in prompt and "does not need news" in prompt


def test_three_parts_run_three_specialists_in_order_and_one_merge():
    analyst, gw, tech, fund, news = build_with_news(say(SPLIT_3), say(MERGED))
    out = analyst.run("TCS price, growth and news", session="s1")
    assert [len(x.calls) for x in (tech, fund, news)] == [1, 1, 1]
    assert news.calls[0]["question"] == "Latest headlines on TCS?"
    assert [c["node"] for c in gw.calls] == ["split", "synthesis"]
    assert out.answer == MERGED


def test_trace_lists_each_invoke_then_that_agents_tools_with_the_news_label():
    analyst, *_ = build_with_news(say(SPLIT_3), say(MERGED))
    out = analyst.run("q")
    assert [(t["agent"], t["tool"]) for t in out.tool_trace] == [
        ("research", "invoke_agent_technical"), ("technical", "get_indicators"),
        ("research", "invoke_agent_fundamental"), ("fundamental", "fsa_compute_growth"),
        ("research", "invoke_agent_news"), ("news", "news_search")]


def test_a_news_only_question_runs_only_the_news_agent_and_skips_the_merge():
    analyst, gw, tech, fund, news = build_with_news(say(SPLIT_NEWS_ONLY))
    out = analyst.run("Any news on TCS?")
    assert tech.calls == [] and fund.calls == [] and len(news.calls) == 1
    assert out.answer == NEWS_TEXT and [c["node"] for c in gw.calls] == ["split"]


def test_a_missing_news_key_in_the_split_means_no_news_part():
    analyst, _, _, _, news = build_with_news(say('{"technical": "RSI?", "fundamental": "growth?"}'), say("merged 55.2 and 8.7"))
    analyst.run("research TCS")
    assert news.calls == []


def test_an_open_request_does_not_call_the_news_agent():
    analyst, _, tech, fund, news = build_with_news(say('{"technical": "RSI?", "fundamental": "growth?", "news": ""}'),
                                                   say("merged 55.2 and 8.7"))
    analyst.run("Is TCS a good stock to buy?")
    assert len(tech.calls) == len(fund.calls) == 1 and news.calls == []


def test_an_unreadable_split_falls_back_to_technical_and_fundamental_only():
    analyst, _, tech, fund, news = build_with_news(say("not json"), say("merged 55.2 and 8.7"))
    analyst.run("q")
    assert len(tech.calls) == len(fund.calls) == 1 and news.calls == []


def test_the_merge_for_a_news_answer_keeps_source_and_date_and_forbids_cause_claims():
    analyst, gw, *_ = build_with_news(say(SPLIT_3), say(MERGED))
    analyst.run("q")
    system = gw.calls[1]["messages"][0]["content"]
    assert "never say a headline caused a price move" in system and "source and date" in system
    assert "Headlines" not in gw.calls[1]["messages"][0]["content"].split("Rules:")[0]


def test_the_merge_for_no_news_does_not_carry_the_news_rules():
    analyst, gw, *_ = build_with_news(say('{"technical": "RSI?", "fundamental": "growth?"}'), say("merged 55.2 and 8.7"))
    analyst.run("q")
    assert "caused a price move" not in gw.calls[1]["messages"][0]["content"]


def test_a_headline_date_or_number_not_in_a_specialist_answer_drops_the_merge():
    bad = "TCS: Economic Times, 25 Nov: TCS wins a deal worth 4,500 crore."          # 4,500 is in no answer
    analyst, *_ = build_with_news(say(SPLIT_3), say(bad))
    out = analyst.run("q")
    assert "4500" in out.note and "News" in out.answer and "wins a large deal" in out.answer


def test_a_stopped_news_agent_is_named_and_the_others_still_answer():
    analyst, gw, tech, fund, news = build_with_news(say(SPLIT_3), say(MERGED))
    news.stopped, news.answer = "step limit reached (12)", ""
    out = analyst.run("q")
    assert "agent_news: step limit reached (12)" in out.stopped_early
    assert "Not available: step limit reached (12)." in gw.calls[1]["messages"][1]["content"]


def test_one_shared_budget_and_the_news_agent_runs_one_level_below_the_analyst():
    analyst, _, tech, fund, news = build_with_news(say(SPLIT_3), say(MERGED))
    analyst.run("q")
    assert tech.calls[0]["budget"] is fund.calls[0]["budget"] is news.calls[0]["budget"]
    assert {c.calls[0]["depth_seen"] for c in (tech, fund, news)} == {1}


def test_three_specialists_run_at_the_same_time_in_parallel_mode():
    import threading
    meet = threading.Barrier(3, timeout=5)                     # fails unless all three are inside together

    class Meeting(FakeSpecialist):
        def run(self, question, **kw):
            meet.wait()
            return super().run(question, **kw)

    analyst, gw, *_ = build_with_news(say(SPLIT_3), say(MERGED), parallel=True)
    analyst.technical = Meeting("agent_technical", "TCS RSI is 55.2.")
    analyst.fundamental = Meeting("agent_fundamental", "TCS revenue grew 8.7% a year over 5 years.")
    analyst.news = Meeting("agent_news", NEWS_TEXT)
    out = analyst.run("q")
    assert out.answer == MERGED and not out.stopped_early


def test_the_default_budget_has_room_for_three_specialists():
    b = ResearchAnalyst.new_budget()
    assert b.max_model_calls >= 24 and b.max_tool_calls >= 40


# ------------------------------------------------------------------------------------------ parse_parts
def test_parse_parts_keeps_news_optional_and_the_old_parse_split_unchanged():
    keys = ("technical", "fundamental", "news")
    assert parse_parts('{"technical": "a", "fundamental": "b"}', keys) == {"technical": "a", "fundamental": "b", "news": ""}
    assert parse_parts(SPLIT_NEWS_ONLY, keys) == {"technical": "", "fundamental": "", "news": "Latest headlines on TCS?"}
    assert parse_parts('{"technical": "", "fundamental": "", "news": ""}', keys) is None
    assert parse_parts('{"technical": "a", "fundamental": "b", "news": 5}', keys) is None
    assert parse_parts('{"technical": "a"}', keys) is None                      # the two old keys must still be text
    assert parse_split('{"technical": "a", "fundamental": "b"}') == ("a", "b")
    assert parse_split("nope") is None


# ------------------------------------------------------------------------------------------ the router
@pytest.mark.parametrize("question,expected", [
    ("Any news on Infosys?", "news"),
    ("Latest headlines on TCS", "news"),
    ("What is the sentiment around HDFC Bank?", "news"),
    ("What's happening with Reliance?", "news"),
    ("Is there any announcement from ITC?", "news"),
    ("market news today", "news"),
    ("TCS share price and news", "both"),
    ("Revenue growth of Infosys and any news", "both"),
    ("What is the RSI of TCS?", "technical"),
    ("TCS net profit", "fundamental"),
    ("What did TCS management say on the earnings call?", "documents"),
    ("Make a 5-stock low-risk portfolio with news sentiment", "portfolio"),
    ("newsletter subscription", "technical"),                                   # 'news' is not a whole word here
])
def test_news_routing(question, expected):
    assert route(question) == expected


# ------------------------------------------------------------------------------------------ the chat page
def test_news_question_goes_to_the_news_agent_and_shows_the_invoke_line(monkeypatch, tmp_path):
    at, _, agent = make(monkeypatch, tmp_path)
    reporter = FakeAgent("Infosys: no headlines found in the checked feeds.")
    monkeypatch.setattr(ui_app, "get_agents", lambda: {"technical": agent, "fundamental": agent.fundamental, "news": reporter})
    at.run()
    at.chat_input[0].set_value("Any news on Infosys?").run()
    assert not at.exception
    assert reporter.questions == ["Any news on Infosys?"] and agent.questions == [] and agent.fundamental.questions == []
    assert any("no headlines found" in m.value for m in at.markdown)
    shown = [c.value for c in at.code]
    assert shown[0].startswith('[guardrail] input_check(') and '"result": "passed"' in shown[0]
    shown = shown[1:]
    assert shown[0] == '[router] invoke_agent_news({"question": "Any news on Infosys?"})'
    assert shown[1] == '[news] get_indicators({"symbol": "TCS"})'


def test_news_question_without_a_news_agent_says_so_and_does_not_use_other_agents(monkeypatch, tmp_path):
    at, _, agent = make(monkeypatch, tmp_path)
    at.run()
    at.chat_input[0].set_value("Any news on Infosys?").run()
    assert not at.exception and agent.questions == [] and agent.fundamental.questions == []
    assert any("news agent is not available" in m.value.lower() for m in at.markdown)


def test_a_mixed_question_with_news_goes_through_the_analyst(monkeypatch, tmp_path):
    at, _, agent = make(monkeypatch, tmp_path)
    analyst = FakeAnalyst()
    reporter = FakeAgent("news")
    monkeypatch.setattr(ui_app, "get_agents", lambda: {"technical": agent, "fundamental": agent.fundamental,
                                                       "news": reporter, "research": analyst})
    at.run()
    at.chat_input[0].set_value("TCS share price and news").run()
    assert analyst.questions == ["TCS share price and news"] and reporter.questions == []


def test_the_welcome_scope_mentions_news():
    assert "news" in ui_app.CHAT_SCOPE.lower()


def test_get_agents_builds_the_news_agent_with_its_own_server_and_gives_it_to_the_analyst(monkeypatch):
    started = []

    class Server:
        def __init__(self, name, script):
            self.name, self.script = name, script

        def start(self):
            started.append(self.script)
            return self

        def openai_tools(self, *a, **k):
            return []

    import mcp_client
    monkeypatch.setattr(mcp_client, "McpServer", Server)
    monkeypatch.setattr(ui_app, "get_gateway", lambda: ScriptedGateway())
    agents = ui_app.get_agents.__wrapped__() if hasattr(ui_app.get_agents, "__wrapped__") else ui_app.get_agents()
    assert "mcp_news.py" in started and set(agents) == {"technical", "fundamental", "news", "research", "portfolio"}
    assert agents["research"].news is agents["news"]
    assert agents["news"].server is not agents["technical"].server and agents["news"].server.script == "mcp_news.py"


def test_the_merge_prompt_asks_for_a_news_heading_after_technical_and_fundamental_when_news_ran():
    analyst, gw, *_ = build_with_news(say(SPLIT_3), say(MERGED))
    analyst.run("q")
    prompt = gw.calls[1]["messages"][0]["content"]
    assert prompt.index("**Technical**") < prompt.index("**Fundamental**") < prompt.index("**News**")
