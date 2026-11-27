"""Guardrail wiring: prompt rules reach every agent prompt, answer() applies keyword rules before routing and logs them,
and the Admin Guardrails tab shows the catalog and edits the custom rules."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import guardrail_rules as gr  # noqa: E402
import ui_app  # noqa: E402
from agent_news import NewsAgent  # noqa: E402
from agent_research_analyst import ResearchAnalyst  # noqa: E402
from agent_technical import TechnicalAgent  # noqa: E402
from mcp_client import McpServer  # noqa: E402
from providers import ChatResult  # noqa: E402
from test_ui_app import FakeAnalyst, make, open_admin  # noqa: E402

RULE = "Always say the data date."


class ScriptedGateway:
    def __init__(self, *results):
        self.results, self.calls = list(results), []

    def chat(self, role, messages, tools=None, **kw):
        self.calls.append({"role": role, "messages": [dict(m) for m in messages], "tools": tools, **kw})
        res = self.results.pop(0)
        res.call_id, res.cost = len(self.calls), None
        return res


def say(text):
    return ChatResult(text=text, tokens_in=50, tokens_out=20)


def tool_call(name, **args):
    return ChatResult(text="", tool_calls=[{"id": "c1", "name": name, "arguments": args}], tokens_in=50, tokens_out=10)


class OkServer:
    def call(self, tool, arguments=None):
        return '{"symbol": "INFY", "headlines": [], "fetched_at": "2026-11-26T14:30+05:30"}'


# ----------------------------------------------------------------------------------------------- prompt rules reach the agents
def test_agents_add_the_extra_rules_to_the_system_prompt_only_when_set():
    gw = ScriptedGateway(tool_call("news_search", stock="INFY"), say("No headline found."))
    agent = NewsAgent(gw, OkServer())
    assert agent.extra_rules == ""
    agent.extra_rules = gr.prompt_block([{"id": "C2", "type": "prompt", "text": RULE, "words": [], "action": "prompt", "enabled": True}])
    agent.run("news on Infosys")
    system = gw.calls[0]["messages"][0]["content"]
    assert system.startswith(agent.system_prompt) and RULE in system


def test_the_news_agent_without_extra_rules_sends_its_normal_prompt():
    gw = ScriptedGateway(tool_call("news_search", stock="INFY"), say("No headline found."))
    NewsAgent(gw, OkServer()).run("news on Infosys")
    assert gw.calls[0]["messages"][0]["content"] == NewsAgent.system_prompt


def test_the_technical_agent_adds_the_extra_rules_too():
    with McpServer("market-data", "mcp_market_data.py") as server:
        gw = ScriptedGateway(tool_call("get_latest_quote", symbol="TCS"), say("TCS closed at 1."))
        agent = TechnicalAgent(gw, server)
        agent.extra_rules = "\n- " + RULE
        agent.run("How is TCS?", focus="Answer the price part only.")
    system = gw.calls[0]["messages"][0]["content"]
    assert RULE in system and "Answer the price part only." in system
    assert system.index(RULE) < system.index("Answer the price part only.")


class Specialist:
    def __init__(self):
        self.agent_name = "x"

    def run(self, *a, budget=None, **kw):
        budget.after_model_call(1, 1)
        return type("R", (), {"answer": "ITC RSI is 55.2.", "tool_trace": [], "budget": budget.summary(),
                              "stopped_early": "", "call_ids": []})()


def test_the_research_analyst_adds_the_extra_rules_to_the_merge_prompt():
    split = '{"technical": "RSI of ITC?", "fundamental": "Growth of ITC?"}'
    gw = ScriptedGateway(say(split), say("ITC RSI is 55.2."))
    analyst = ResearchAnalyst(gw, Specialist(), Specialist())
    analyst.extra_rules = "\n- " + RULE
    analyst.run("RSI and growth of ITC")
    assert RULE in gw.calls[1]["messages"][0]["content"] and RULE not in gw.calls[0]["messages"][0]["content"]


# ----------------------------------------------------------------------------------------------- answer(): the input check
def with_rules(store, *rules):
    highest = max((int(r["id"][1:]) for r in rules), default=0)
    store.set_value("guardrails", {"custom": list(rules), "next": highest + 1})


def kw(rid="C1", words=("price target",), action="block", text="No price targets here."):
    return {"id": rid, "type": "keyword", "text": text, "words": list(words), "action": action, "enabled": True}


def pr(rid="C2", text=RULE):
    return {"id": rid, "type": "prompt", "text": text, "words": [], "action": "prompt", "enabled": True}


def test_a_blocked_question_never_reaches_an_agent_and_is_logged(monkeypatch, tmp_path):
    at, store, agent = make(monkeypatch, tmp_path)
    with_rules(store, kw())
    seen = []
    monkeypatch.setattr(ui_app, "get_agents", lambda: seen.append(1) or {"technical": agent})
    out = ui_app.answer("What is the price target of TCS?", "s1")
    assert out["route"] == "guardrail" and "C1" in out["text"] and "No price targets here." in out["text"]
    assert out["trace"] == [{"agent": "guardrail", "tool": "block_question", "arguments": {"rule": "C1", "word": "price target"}}]
    assert agent.questions == [] and seen == []                               # agents were not even built
    row = store.guardrail_events(1)[0]
    assert (row["rule_id"], row["action"], row["session"], row["route"]) == ("C1", "block", "s1", "guardrail")
    assert "price target" in row["summary"]


def test_a_warn_rule_lets_the_question_through_and_adds_a_note_to_the_answer(monkeypatch, tmp_path):
    at, store, agent = make(monkeypatch, tmp_path)
    with_rules(store, kw("C1", ("tomorrow",), "warn", "Not a forecast."))
    out = ui_app.answer("RSI of TCS tomorrow", "s1")
    assert agent.questions == ["RSI of TCS tomorrow"]
    assert out["text"].startswith("TCS RSI is 55.") and "Guardrail C1: Not a forecast." in out["text"]
    assert store.guardrail_events(1)[0]["action"] == "warn"


def test_no_rules_means_no_change_and_no_event(monkeypatch, tmp_path):
    at, store, agent = make(monkeypatch, tmp_path)
    out = ui_app.answer("RSI of TCS?", "s1")
    assert out["text"] == "TCS RSI is 55." and store.guardrail_events(10) == []


def test_a_rule_changed_in_admin_applies_to_the_next_question_without_a_restart(monkeypatch, tmp_path):
    at, store, agent = make(monkeypatch, tmp_path)
    assert ui_app.answer("price target of TCS", "s")["route"] != "guardrail"
    with_rules(store, kw())
    assert ui_app.answer("price target of TCS", "s")["route"] == "guardrail"
    store.set_value("guardrails", gr.set_enabled(store.get_value("guardrails"), "C1", False))
    assert ui_app.answer("price target of TCS", "s")["route"] != "guardrail"


def test_prompt_rules_are_pushed_to_every_agent_before_the_run(monkeypatch, tmp_path):
    at, store, agent = make(monkeypatch, tmp_path)
    analyst = FakeAnalyst()
    monkeypatch.setattr(ui_app, "get_agents", lambda: {"technical": agent, "fundamental": agent.fundamental, "research": analyst})
    with_rules(store, pr())
    ui_app.answer("RSI of TCS?", "s")
    assert RULE in agent.extra_rules and RULE in agent.fundamental.extra_rules and RULE in analyst.extra_rules
    store.set_value("guardrails", gr.remove_rule(store.get_value("guardrails"), "C2"))
    ui_app.answer("RSI of TCS?", "s")
    assert agent.extra_rules == "" and analyst.extra_rules == ""


def test_an_event_log_failure_does_not_stop_the_answer(monkeypatch, tmp_path):
    at, store, agent = make(monkeypatch, tmp_path)
    with_rules(store, kw("C1", ("tomorrow",), "warn"))
    monkeypatch.setattr(store, "log_guardrail_event", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk full")))
    assert "TCS RSI is 55." in ui_app.answer("RSI of TCS tomorrow", "s")["text"]


# ----------------------------------------------------------------------------------------------- the Admin Guardrails tab
def sign_in(at):
    open_admin(at)
    at.text_input(key="admin_pw").set_value("secret")
    at.button(key="admin_login").click().run()
    return at


def test_the_guardrails_tab_lists_every_built_in_rule_with_timing_strength_and_state(monkeypatch, tmp_path):
    at, store, _ = make(monkeypatch, tmp_path)
    sign_in(at)
    assert not at.exception
    assert "Guardrails" in [t.label for t in at.tabs]
    table = next(df for df in at.dataframe if "Timing" in df.value.columns)
    shown = table.value
    assert list(shown["ID"]) == [r["id"] for r in gr.CATALOG]
    assert set(shown["Timing"]) <= set(gr.TIMINGS) and set(shown["Strength"]) <= set(gr.STRENGTHS)
    g8 = shown[shown["ID"] == "G8"].iloc[0]
    assert g8["Locked"] == "yes" and g8["State"] == "built"
    assert shown[shown["ID"] == "P1"].iloc[0]["State"] == "planned"


def test_the_tab_says_that_built_in_rules_cannot_be_switched_and_prompt_rules_are_soft(monkeypatch, tmp_path):
    at, _, _ = make(monkeypatch, tmp_path)
    sign_in(at)
    text = " ".join(c.value for c in at.caption) + " " + " ".join(m.value for m in at.markdown)
    assert "cannot be switched" in text and "soft" in text.lower()


def test_adding_a_keyword_rule_saves_it_audits_it_and_it_then_blocks(monkeypatch, tmp_path):
    at, store, agent = make(monkeypatch, tmp_path)
    sign_in(at)
    at.selectbox(key="gr_new_type").select("keyword")
    at.text_input(key="gr_new_text").set_value("No price targets here.")
    at.text_input(key="gr_new_words").set_value("price target, target price")
    at.selectbox(key="gr_new_action").select("block")
    at.button(key="gr_add").click().run()
    assert not at.exception
    rule = store.get_value("guardrails")["custom"][0]
    assert rule["id"] == "C1" and rule["words"] == ["price target", "target price"] and rule["enabled"] is True
    assert store.audit_log(1)[0]["item"] == "value:guardrails"
    assert ui_app.answer("What is the target price of TCS?", "s")["route"] == "guardrail"


def test_adding_a_rule_with_no_text_or_no_words_shows_an_error_and_saves_nothing(monkeypatch, tmp_path):
    at, store, _ = make(monkeypatch, tmp_path)
    sign_in(at)
    at.selectbox(key="gr_new_type").select("keyword")
    at.text_input(key="gr_new_text").set_value("")
    at.text_input(key="gr_new_words").set_value("tip")
    at.button(key="gr_add").click().run()
    assert at.error and store.get_value("guardrails")["custom"] == []
    at.text_input(key="gr_new_text").set_value("No tips.")
    at.text_input(key="gr_new_words").set_value(" , ")
    at.button(key="gr_add").click().run()
    assert at.error and store.get_value("guardrails")["custom"] == []


def test_adding_a_prompt_rule_ignores_the_words_and_action_fields(monkeypatch, tmp_path):
    at, store, _ = make(monkeypatch, tmp_path)
    sign_in(at)
    at.selectbox(key="gr_new_type").select("prompt")
    at.text_input(key="gr_new_text").set_value(RULE)
    at.text_input(key="gr_new_words").set_value("ignored")
    at.button(key="gr_add").click().run()
    rule = store.get_value("guardrails")["custom"][0]
    assert rule["type"] == "prompt" and rule["words"] == [] and rule["action"] == "prompt"


def test_the_checkbox_turns_a_custom_rule_off_and_on_and_both_changes_are_audited(monkeypatch, tmp_path):
    at, store, _ = make(monkeypatch, tmp_path)
    with_rules(store, kw())
    sign_in(at)
    assert at.checkbox(key="gr_on_C1").value is True
    at.checkbox(key="gr_on_C1").uncheck()
    at.button(key="gr_save").click().run()
    assert store.get_value("guardrails")["custom"][0]["enabled"] is False
    at.checkbox(key="gr_on_C1").check()
    at.button(key="gr_save").click().run()
    assert store.get_value("guardrails")["custom"][0]["enabled"] is True
    assert [a["item"] for a in store.audit_log(2)] == ["value:guardrails", "value:guardrails"]


def test_removing_a_custom_rule_works_and_its_id_is_not_reused(monkeypatch, tmp_path):
    at, store, _ = make(monkeypatch, tmp_path)
    with_rules(store, kw())
    sign_in(at)
    at.button(key="gr_remove_C1").click().run()
    assert store.get_value("guardrails") == {"custom": [], "next": 2}
    at.selectbox(key="gr_new_type").select("prompt")
    at.text_input(key="gr_new_text").set_value(RULE)
    at.button(key="gr_add").click().run()
    assert store.get_value("guardrails")["custom"][0]["id"] == "C2"


def test_built_in_rules_have_no_checkbox_and_no_remove_button(monkeypatch, tmp_path):
    at, store, _ = make(monkeypatch, tmp_path)
    with_rules(store, kw())
    sign_in(at)
    keys = {c.key for c in at.checkbox} | {b.key for b in at.button}
    assert not any(k and k.startswith(("gr_on_G", "gr_on_A", "gr_on_P", "gr_remove_G", "gr_remove_A", "gr_remove_P")) for k in keys)
    assert {"gr_on_C1", "gr_remove_C1"} <= keys


def test_the_tab_shows_how_often_a_custom_rule_fired_and_the_recent_events(monkeypatch, tmp_path):
    at, store, _ = make(monkeypatch, tmp_path)
    with_rules(store, kw())
    ui_app.answer("price target of TCS", "s9")
    ui_app.answer("price target of INFY", "s9")
    sign_in(at)
    custom = next(df for df in at.dataframe if "Fired" in df.value.columns).value
    assert custom.iloc[0]["ID"] == "C1" and custom.iloc[0]["Fired"] == 2
    events = next(df for df in at.dataframe if "Summary" in df.value.columns).value
    assert len(events) == 2 and set(events["Rule"]) == {"C1"}


def test_the_tab_works_with_no_custom_rules_and_no_events(monkeypatch, tmp_path):
    at, _, _ = make(monkeypatch, tmp_path)
    sign_in(at)
    assert not at.exception
    assert any("No custom guardrails" in i.value for i in at.info)


def test_every_old_admin_tab_is_still_there(monkeypatch, tmp_path):
    at, _, _ = make(monkeypatch, tmp_path)
    sign_in(at)
    assert [t.label for t in at.tabs] == ["Models", "Providers", "Chunking and RAG", "Agents", "Guardrails", "Usage log", "Change log"]
