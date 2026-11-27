"""agent_research_analyst: splits a question, runs the technical and fundamental agents on their own halves, and merges.

No model and no MCP server here: a scripted gateway and fake specialists.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent_research_analyst import ResearchAnalyst, numbers_in, unsupported_numbers  # noqa: E402
from agent_technical import TechnicalResult  # noqa: E402
from budget import Budget  # noqa: E402
from gateway import GatewayError  # noqa: E402
from providers import ChatResult  # noqa: E402


class ScriptedGateway:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def chat(self, role, messages, tools=None, **kw):
        self.calls.append({"role": role, "messages": messages, "tools": tools, **kw})
        item = self.results.pop(0)
        if isinstance(item, Exception):
            raise item
        item.call_id = 100 + len(self.calls)
        item.cost = None
        return item


def say(text, tokens_in=50, tokens_out=20):
    return ChatResult(text=text, tokens_in=tokens_in, tokens_out=tokens_out)


class FakeSpecialist:
    def __init__(self, name, answer, stopped="", trace=None):
        self.agent_name, self.answer, self.stopped, self.trace = name, answer, stopped, trace or []
        self.calls = []

    def run(self, question, *, session="", parent_call_id=None, budget=None, route="", focus="", **kw):
        self.calls.append({"question": question, "session": session, "parent": parent_call_id,
                           "budget": budget, "focus": focus, "depth_seen": budget.depth})
        budget.after_model_call(100, 10)
        return TechnicalResult(answer=self.answer, tool_trace=list(self.trace),
                               budget=budget.summary(), stopped_early=self.stopped, call_ids=[7, 8])


SPLIT_OK = '{"technical": "What is the RSI of ITC?", "fundamental": "What is the revenue growth of ITC?"}'


def build(*gateway_results, tech_answer="ITC RSI is 55.2 (data to 13 Nov 2026).",
          fund_answer="ITC revenue grew 8.7% a year over 5 years.", **kw):
    gw = ScriptedGateway(*gateway_results)
    tech = FakeSpecialist("agent_technical", tech_answer, trace=[{"tool": "get_indicators", "arguments": {"symbol": "ITC"}}])
    fund = FakeSpecialist("agent_fundamental", fund_answer, trace=[{"tool": "fsa_compute_growth", "arguments": {}}])
    return ResearchAnalyst(gw, tech, fund, **kw), gw, tech, fund


GOOD_NOTE = "ITC: RSI is 55.2. Revenue grew 8.7% a year over 5 years."


# ----------------------------------------------------------------------------------- the normal path
def test_split_then_each_agent_gets_only_its_own_half_then_one_merged_answer():
    analyst, gw, tech, fund = build(say(SPLIT_OK), say(GOOD_NOTE))
    out = analyst.run("Revenue growth and RSI of ITC", session="s1")
    assert tech.calls[0]["question"] == "What is the RSI of ITC?"
    assert fund.calls[0]["question"] == "What is the revenue growth of ITC?"
    assert out.answer == GOOD_NOTE
    assert [c["node"] for c in gw.calls] == ["split", "synthesis"]
    assert all(c["role"] == "chat" and c["agent"] == "agent_research_analyst" and c["tools"] is None for c in gw.calls)


def test_synthesis_sees_both_specialist_answers_and_the_question():
    analyst, gw, *_ = build(say(SPLIT_OK), say(GOOD_NOTE))
    analyst.run("Revenue growth and RSI of ITC")
    text = " ".join(m["content"] for m in gw.calls[1]["messages"])
    assert "Revenue growth and RSI of ITC" in text and "RSI is 55.2" in text and "grew 8.7%" in text


def test_tool_trace_keeps_the_specialist_that_made_each_call():
    analyst, *_ = build(say(SPLIT_OK), say(GOOD_NOTE))
    out = analyst.run("q")
    assert [(t["agent"], t["tool"]) for t in out.tool_trace] == [
        ("research", "invoke_agent_technical"), ("technical", "get_indicators"),
        ("research", "invoke_agent_fundamental"), ("fundamental", "fsa_compute_growth")]


def test_trace_shows_the_question_the_analyst_handed_to_each_specialist():
    analyst, *_ = build(say(SPLIT_OK), say(GOOD_NOTE))
    out = analyst.run("q")
    invokes = {t["tool"]: t["arguments"] for t in out.tool_trace if t["agent"] == "research"}
    assert invokes == {"invoke_agent_technical": {"question": "What is the RSI of ITC?"},
                       "invoke_agent_fundamental": {"question": "What is the revenue growth of ITC?"}}


def test_only_the_specialist_that_ran_is_shown_as_invoked():
    analyst, *_ = build(say('{"technical": "RSI of ITC?", "fundamental": ""}'))
    out = analyst.run("q")
    assert [t["tool"] for t in out.tool_trace if t["agent"] == "research"] == ["invoke_agent_technical"]


def test_one_shared_budget_and_the_specialists_run_one_level_below_the_analyst():
    analyst, gw, tech, fund = build(say(SPLIT_OK), say(GOOD_NOTE))
    out = analyst.run("q")
    assert tech.calls[0]["budget"] is fund.calls[0]["budget"]
    assert tech.calls[0]["depth_seen"] == 1                         # the analyst already entered
    assert out.budget["model_calls"] == 4                           # split + 2 specialists + synthesis
    assert out.budget["tokens"] == 70 + 110 + 110 + 70


def test_default_budget_is_larger_than_a_single_agents():
    analyst, *_ = build(say(SPLIT_OK), say(GOOD_NOTE))
    assert analyst.new_budget().max_model_calls > Budget().max_model_calls


def test_specialists_are_children_of_the_split_call_and_call_ids_are_collected():
    analyst, gw, tech, fund = build(say(SPLIT_OK), say(GOOD_NOTE))
    out = analyst.run("q")
    assert tech.calls[0]["parent"] == fund.calls[0]["parent"] == 101          # id of the split call
    assert gw.calls[1]["parent_call_id"] == 101
    assert set(out.call_ids) >= {101, 102, 7, 8}


def test_specialists_are_told_to_answer_only_their_own_question():
    analyst, gw, tech, fund = build(say(SPLIT_OK), say(GOOD_NOTE))
    analyst.run("q")
    assert "only the question" in tech.calls[0]["focus"].lower()


# ----------------------------------------------------------------------------------- split problems
def test_split_json_inside_code_fences_is_accepted():
    analyst, gw, tech, fund = build(say("```json\n" + SPLIT_OK + "\n```"), say(GOOD_NOTE))
    analyst.run("q")
    assert tech.calls[0]["question"] == "What is the RSI of ITC?"


def test_unreadable_split_falls_back_to_the_whole_question_for_both():
    analyst, gw, tech, fund = build(say("sorry, I cannot"), say(GOOD_NOTE))
    analyst.run("Revenue growth and RSI of ITC")
    assert tech.calls[0]["question"] == fund.calls[0]["question"] == "Revenue growth and RSI of ITC"
    assert "price, trend and indicator" in tech.calls[0]["focus"]
    assert "financial-statement" in fund.calls[0]["focus"]


def test_split_gateway_error_falls_back_to_the_whole_question():
    analyst, gw, tech, fund = build(GatewayError("down"), say(GOOD_NOTE))
    out = analyst.run("Revenue growth and RSI of ITC")
    assert tech.calls and fund.calls and out.answer == GOOD_NOTE


def test_split_with_both_parts_empty_falls_back():
    analyst, gw, tech, fund = build(say('{"technical": "", "fundamental": ""}'), say(GOOD_NOTE))
    analyst.run("q")
    assert tech.calls and fund.calls


def test_split_with_wrong_types_falls_back():
    analyst, gw, tech, fund = build(say('{"technical": 5, "fundamental": ["x"]}'), say(GOOD_NOTE))
    analyst.run("q")
    assert tech.calls[0]["question"] == "q"


def test_only_one_part_needed_runs_one_specialist_and_skips_synthesis():
    analyst, gw, tech, fund = build(say('{"technical": "RSI of ITC?", "fundamental": ""}'))
    out = analyst.run("RSI of ITC?")
    assert tech.calls and not fund.calls
    assert out.answer == "ITC RSI is 55.2 (data to 13 Nov 2026)." and len(gw.calls) == 1


# ----------------------------------------------------------------------------------- numbers come from the specialists
def test_a_number_the_specialists_never_gave_is_rejected_and_the_labelled_answers_are_returned():
    analyst, *_ = build(say(SPLIT_OK), say("ITC RSI is 55.2 and revenue grew 12.5% a year."))
    out = analyst.run("q")
    assert "12.5" not in out.answer
    assert "**Technical**" in out.answer and "**Fundamental**" in out.answer
    assert "RSI is 55.2" in out.answer and "grew 8.7%" in out.answer
    assert "12.5" in out.note


def test_rounding_style_differences_are_not_flagged():
    analyst, *_ = build(say(SPLIT_OK), say("RSI 55.20, growth 8.70% per year, 1,234 crore."),
                        fund_answer="Revenue grew 8.7% a year. Sales were 1234 crore.")
    out = analyst.run("q")
    assert out.answer.startswith("RSI 55.20") and out.note == ""


def test_small_whole_numbers_such_as_list_markers_are_ignored():
    assert unsupported_numbers("1. First point\n2. Second, over 5 years", "nothing numeric here") == []


def test_numbers_in_reads_commas_percent_and_decimals():
    assert numbers_in("Sales 1,234.50 crore, up 8.7% and 12%.") == {1234.5, 8.7, 12.0}


def test_unsupported_numbers_lists_only_the_new_ones():
    assert unsupported_numbers("RSI 55.2, price 999", "RSI is 55.2") == [999.0]


# ----------------------------------------------------------------------------------- failures of one part
def test_a_stopped_specialist_is_reported_and_the_other_part_still_answers():
    analyst, gw, tech, fund = build(say(SPLIT_OK), say(GOOD_NOTE))
    fund.stopped, fund.answer = "tool call limit reached (20)", ""
    out = analyst.run("q")
    assert "agent_fundamental" in out.stopped_early and "tool call limit" in out.stopped_early
    text = " ".join(m["content"] for m in gw.calls[1]["messages"])
    assert "not available" in text.lower() and "tool call limit" in text


def test_synthesis_gateway_error_returns_the_labelled_answers():
    analyst, *_ = build(say(SPLIT_OK), GatewayError("down"))
    out = analyst.run("q")
    assert "**Technical**" in out.answer and "RSI is 55.2" in out.answer
    assert "synthesis" in out.stopped_early.lower()


def test_empty_synthesis_returns_the_labelled_answers():
    analyst, *_ = build(say(SPLIT_OK), say("   "))
    out = analyst.run("q")
    assert "**Technical**" in out.answer


def test_budget_exhausted_before_the_split_still_returns_something():
    analyst, gw, tech, fund = build(say(SPLIT_OK), say(GOOD_NOTE))
    out = analyst.run("q", budget=Budget(max_model_calls=0))
    assert gw.calls == [] and "limit" in out.stopped_early
    assert out.answer


# ----------------------------------------------------------------------------------- citations must come from the specialists
def test_invented_page_citations_are_removed_from_the_merged_answer():
    from agent_research_analyst import strip_unsupported_citations
    text = "RSI is 55.2 (Technical Analyst, p. 1). Growth is 8.7% (Fundamental Analyst, p. 1)."
    cleaned, removed = strip_unsupported_citations(text, "RSI is 55.2. Growth is 8.7%.")
    assert "Analyst" not in cleaned and "p. 1" not in cleaned and removed == 2
    assert cleaned.startswith("RSI is 55.2.") and "Growth is 8.7%." in cleaned


def test_a_real_document_citation_that_a_specialist_gave_is_kept():
    from agent_research_analyst import strip_unsupported_citations
    source = "Management expects capex to rise (Transcript_Nov_2025.pdf, p. 5)."
    text = "ONGC expects higher capex (Transcript_Nov_2025.pdf, p. 5)."
    cleaned, removed = strip_unsupported_citations(text, source)
    assert cleaned == text and removed == 0


def test_a_document_citation_the_specialists_never_gave_is_removed():
    from agent_research_analyst import strip_unsupported_citations
    cleaned, removed = strip_unsupported_citations("Capex rises (Transcript_Nov_2025.pdf, p. 9).", "no citations here")
    assert "Transcript" not in cleaned and removed == 1


def test_synthesis_removes_invented_citations_and_says_so_in_the_note():
    analyst, *_ = build(say(SPLIT_OK), say("ITC: RSI is 55.2 (Technical Analyst, p. 1). Revenue grew 8.7% a year."))
    out = analyst.run("q")
    assert "Analyst" not in out.answer and "RSI is 55.2" in out.answer
    assert "1 citation" in out.note


def test_synthesis_prompt_forbids_page_citations_that_are_not_in_the_answers():
    from agent_research_analyst import SYNTHESIS_PROMPT, SPLIT_PROMPT
    assert "Never write a page number or a source for the analysts themselves" in SYNTHESIS_PROMPT
    assert "not a recommendation" in SYNTHESIS_PROMPT.lower() or "cannot advise" in SYNTHESIS_PROMPT.lower()
    assert "growth" in SPLIT_PROMPT and "valuation" in SPLIT_PROMPT and "open request" in SPLIT_PROMPT.lower()


# ----------------------------------------------------------------------------------- section headings in the merged answer
# The merge is a model call, so a test can only check what the prompt ASKS for. It cannot prove the model obeys.
def merge_prompt(gw):
    return gw.calls[1]["messages"][0]["content"]


def test_the_merge_prompt_asks_for_a_technical_and_a_fundamental_heading():
    analyst, gw, *_ = build(say(SPLIT_OK), say(GOOD_NOTE))
    analyst.run("Revenue growth and RSI of ITC")
    prompt = merge_prompt(gw)
    assert "**Technical**" in prompt and "**Fundamental**" in prompt
    assert prompt.index("**Technical**") < prompt.index("**Fundamental**")


def test_the_merge_prompt_does_not_ask_for_a_news_heading_when_news_did_not_run():
    analyst, gw, *_ = build(say(SPLIT_OK), say(GOOD_NOTE))
    analyst.run("Revenue growth and RSI of ITC")
    assert "**News**" not in merge_prompt(gw)


def test_the_merge_prompt_says_to_use_only_the_headings_for_parts_that_were_answered():
    analyst, gw, *_ = build(say(SPLIT_OK), say(GOOD_NOTE))
    analyst.run("Revenue growth and RSI of ITC")
    prompt = merge_prompt(gw)
    assert "only these headings" in prompt and "do not add any other heading" in prompt.lower()


def test_the_merge_prompt_keeps_stocks_inside_each_section_not_a_section_per_stock():
    analyst, gw, *_ = build(say(SPLIT_OK), say(GOOD_NOTE))
    analyst.run("Compare TCS and INFY")
    prompt = merge_prompt(gw)
    assert "inside each section" in prompt and "one row per stock" in prompt
    assert "group the points by stock." not in prompt        # the old rule, which gave one block per stock and no sections


def test_the_base_prompt_no_longer_sends_the_headings_for_a_news_part_it_was_not_given():
    from agent_research_analyst import SYNTHESIS_PROMPT
    assert "**News**" not in SYNTHESIS_PROMPT and "**Technical**" not in SYNTHESIS_PROMPT   # headings are added per call


def test_the_headings_follow_the_order_of_the_answers_that_came_back():
    from agent_research_analyst import section_rule
    assert section_rule(["technical", "fundamental"]).index("**Technical**") < section_rule(["technical", "fundamental"]).index("**Fundamental**")
    rule = section_rule(["technical", "fundamental", "news"])
    assert rule.index("**Fundamental**") < rule.index("**News**")
    assert "**Technical**" not in section_rule(["fundamental", "news"]) and "**News**" in section_rule(["fundamental", "news"])


def test_the_labelled_fallback_still_uses_the_same_headings():
    analyst, gw, *_ = build(say(SPLIT_OK), GatewayError("down"))
    out = analyst.run("Revenue growth and RSI of ITC")
    assert "**Technical**" in out.answer and "**Fundamental**" in out.answer


def test_the_merge_prompt_puts_every_point_under_a_heading_and_nothing_before_the_first():
    analyst, gw, *_ = build(say(SPLIT_OK), say(GOOD_NOTE))
    analyst.run("Compare TCS and INFY")
    prompt = merge_prompt(gw)
    assert "Put every point under one of these headings" in prompt
    assert "Nothing goes before the first heading" in prompt


def test_document_and_management_points_go_under_the_fundamental_heading_not_a_new_one():
    from agent_research_analyst import section_rule
    rule = section_rule(["technical", "fundamental"])
    assert "management" in rule.lower() and "under **Fundamental**" in rule
    assert "evidence for and against" in rule.lower() and "inside the sections" in rule.lower()
