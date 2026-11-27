"""guardrail_rules: the guardrail catalog, custom keyword and prompt rules, the input check, and the event log.

No model and no MCP server here. The settings store is a temporary SQLite file.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import guardrail_rules as gr  # noqa: E402
from model_settings import SettingsError, SettingsStore  # noqa: E402


@pytest.fixture
def store(tmp_path):
    return SettingsStore(tmp_path / "s.sqlite")


def keyword(rid="C1", words=("price target",), action="block", text="No price targets here.", enabled=True):
    return {"id": rid, "type": "keyword", "text": text, "words": list(words), "action": action, "enabled": enabled}


def prompt(rid="C2", text="Always say the data date.", enabled=True):
    return {"id": rid, "type": "prompt", "text": text, "words": [], "action": "prompt", "enabled": enabled}


# ----------------------------------------------------------------------------------------------- the catalog
def test_catalog_ids_are_unique_and_every_field_is_an_allowed_value():
    ids = [r["id"] for r in gr.CATALOG]
    assert len(ids) == len(set(ids))
    for r in gr.CATALOG:
        assert r["timing"] in gr.TIMINGS and r["strength"] in gr.STRENGTHS and r["state"] in gr.STATES
        assert r["name"] and r["what"] and r["layer"]


def test_g1_g7_and_g8_are_built_and_locked():
    by_id = {r["id"]: r for r in gr.CATALOG}
    for rid in ("G1", "G7", "G8"):
        assert by_id[rid]["state"] == "built" and by_id[rid]["locked"] is True


def test_all_eight_original_guardrails_are_listed_as_built():
    by_id = {r["id"]: r for r in gr.CATALOG}
    assert all(by_id[f"G{n}"]["state"] == "built" for n in range(1, 9))


def test_the_review_listed_eighteen_rules_and_the_event_log_p6_is_built_with_this_tab():
    review = [r for r in gr.CATALOG if r["id"].startswith("P")]
    assert [r["id"] for r in review] == [f"P{n}" for n in range(1, 19)]
    planned = [r for r in review if r["state"] == "planned"]
    assert len(planned) == 17 and "P6" not in {r["id"] for r in planned}
    assert {r["id"]: r for r in gr.CATALOG}["P6"]["state"] == "built"


def test_prompt_only_rules_are_labelled_soft_and_code_rules_hard():
    by_id = {r["id"]: r for r in gr.CATALOG}
    assert by_id["A4"]["timing"] == "prompt" and by_id["A4"]["strength"] == "soft"
    assert all(r["strength"] == "hard" for r in gr.CATALOG if r["timing"] in ("input", "output", "tool"))


def test_no_built_in_rule_is_switchable_in_this_version():
    assert all(r["switchable"] is False for r in gr.CATALOG)


# ----------------------------------------------------------------------------------------------- the input check
def test_a_keyword_rule_blocks_a_matching_question_and_names_the_rule_and_word():
    decision = gr.check_question("What is the PRICE TARGET for TCS?", [keyword()])
    assert decision.blocked and decision.hits[0]["id"] == "C1" and decision.hits[0]["word"] == "price target"
    assert "C1" in decision.message and "No price targets here." in decision.message
    assert "not answered" in decision.message and not decision.message.startswith("GUARDRAIL")   # the label is added once, by the caller


def test_matching_is_case_insensitive_and_whole_word():
    rules = [keyword(words=("tip",))]
    assert gr.check_question("Give me a TIP on ITC", rules).blocked
    assert not gr.check_question("Is tipping a risk for ITC?", rules).blocked           # inside a longer word
    assert not gr.check_question("RSI of ITC", rules).hits


def test_a_phrase_with_punctuation_is_matched_literally():
    rules = [keyword(words=("buy/sell",))]
    assert gr.check_question("Is it a buy/sell for INFY?", rules).blocked
    assert not gr.check_question("Is it a buyXsell for INFY?", rules).blocked


def test_a_disabled_rule_does_nothing():
    assert gr.check_question("price target of TCS", [keyword(enabled=False)]).hits == []


def test_a_warn_rule_does_not_block_and_gives_a_note_for_the_answer():
    decision = gr.check_question("Will TCS go up tomorrow?", [keyword(words=("tomorrow",), action="warn", text="Not a forecast.")])
    assert not decision.blocked and decision.message == ""
    assert decision.notes == ["C1: Not a forecast."]


def test_a_block_wins_over_a_warn_when_both_match():
    rules = [keyword("C1", ("tomorrow",), "warn"), keyword("C2", ("price target",), "block", "No targets.")]
    decision = gr.check_question("price target tomorrow", rules)
    assert decision.blocked and {h["id"] for h in decision.hits} == {"C1", "C2"}


def test_prompt_rules_are_not_part_of_the_input_check():
    assert gr.check_question("anything at all", [prompt()]).hits == []


def test_an_empty_question_and_no_rules_are_allowed():
    assert not gr.check_question("", []).blocked and not gr.check_question("RSI of TCS", []).hits


# ----------------------------------------------------------------------------------------------- prompt rules
def test_prompt_block_lists_only_enabled_prompt_rules():
    rules = [prompt("C2", "Always say the data date."), prompt("C3", "Never use the word safe.", enabled=False),
             keyword("C1")]
    text = gr.prompt_block(rules)
    assert "Always say the data date." in text and "never use the word safe" not in text.lower() and "price target" not in text
    assert text.startswith("\n")


def test_prompt_block_is_empty_when_no_prompt_rule_is_on():
    assert gr.prompt_block([]) == "" and gr.prompt_block([keyword(), prompt(enabled=False)]) == ""


# ----------------------------------------------------------------------------------------------- add and remove helpers
def test_add_rule_gives_the_next_id_and_does_not_change_the_old_value():
    old = {"custom": [], "next": 1}
    new = gr.add_rule(old, "keyword", "No targets.", "price target, target price", "block")
    assert old == {"custom": [], "next": 1}
    assert new["next"] == 2 and new["custom"][0] == {
        "id": "C1", "type": "keyword", "text": "No targets.", "words": ["price target", "target price"],
        "action": "block", "enabled": True}
    assert gr.add_rule(new, "prompt", "Say the data date.", "", "prompt")["custom"][1]["id"] == "C2"


def test_a_removed_id_is_not_used_again():
    value = gr.add_rule({"custom": [], "next": 1}, "prompt", "One.", "", "prompt")
    value = gr.remove_rule(value, "C1")
    assert value["custom"] == [] and gr.add_rule(value, "prompt", "Two.", "", "prompt")["custom"][0]["id"] == "C2"


def test_remove_rule_rejects_an_unknown_id():
    with pytest.raises(SettingsError):
        gr.remove_rule({"custom": [], "next": 1}, "C9")


def test_words_are_split_on_commas_trimmed_and_empty_ones_dropped():
    assert gr.split_words(" a b , ,c,  ") == ["a b", "c"]


# ----------------------------------------------------------------------------------------------- settings validation
def test_the_default_is_no_custom_rules(store):
    assert store.get_value("guardrails") == {"custom": [], "next": 1}


def test_a_valid_value_is_saved_and_audited(store):
    value = {"custom": [keyword(), prompt()], "next": 3}
    store.set_value("guardrails", value)
    assert store.get_value("guardrails") == value
    assert store.audit_log(1)[0]["item"] == "value:guardrails"


@pytest.mark.parametrize("bad", [
    [],                                                                            # not a dict
    {"custom": []},                                                                # next missing
    {"custom": [], "next": 0},
    {"custom": [], "next": "1"},
    {"custom": "x", "next": 1},
    {"custom": [], "next": 1, "extra": 1},
    {"custom": [keyword("C1"), keyword("C1", ("x",))], "next": 3},                 # duplicate id
    {"custom": [keyword("X1")], "next": 2},                                        # id not C<number>
    {"custom": [{**keyword(), "type": "regex"}], "next": 2},
    {"custom": [{**keyword(), "text": "  "}], "next": 2},
    {"custom": [{**keyword(), "text": "x" * 301}], "next": 2},
    {"custom": [{**keyword(), "words": []}], "next": 2},                            # keyword rule needs words
    {"custom": [{**keyword(), "words": [""]}], "next": 2},
    {"custom": [{**keyword(), "words": ["w"] * 21}], "next": 2},
    {"custom": [{**keyword(), "words": ["x" * 61]}], "next": 2},
    {"custom": [{**keyword(), "action": "stop"}], "next": 2},
    {"custom": [{**keyword(), "enabled": "yes"}], "next": 2},
    {"custom": [{**prompt(), "words": ["x"]}], "next": 3},                          # prompt rule has no words
    {"custom": [{**prompt(), "action": "block"}], "next": 3},
    {"custom": [{**keyword(), "id": "C1"}], "next": 1},                             # next not above the used ids
    {"custom": [keyword(f"C{n}", (f"w{n}",)) for n in range(1, 32)], "next": 32},   # more than 30 rules
    {"custom": [{**keyword(), "extra": 1}], "next": 2},
])
def test_invalid_guardrail_values_are_rejected_and_nothing_is_saved(store, bad):
    with pytest.raises(SettingsError):
        store.set_value("guardrails", bad)
    assert store.get_value("guardrails") == {"custom": [], "next": 1}


def test_thirty_rules_are_allowed(store):
    store.set_value("guardrails", {"custom": [keyword(f"C{n}", (f"w{n}",)) for n in range(1, 31)], "next": 31})
    assert len(store.get_value("guardrails")["custom"]) == 30


# ----------------------------------------------------------------------------------------------- the event log
def test_an_event_is_stored_with_a_short_summary_not_the_whole_question(store):
    store.log_guardrail_event("C1", "block", "x" * 500, session="s1", route="guardrail")
    row = store.guardrail_events(10)[0]
    assert row["rule_id"] == "C1" and row["action"] == "block" and row["session"] == "s1" and row["route"] == "guardrail"
    assert len(row["summary"]) <= gr.SUMMARY_CHARS and row["ts"] > 0


def test_events_come_back_newest_first_and_the_limit_applies(store):
    for n in range(5):
        store.log_guardrail_event("C1", "warn", f"q{n}")
    rows = store.guardrail_events(3)
    assert [r["summary"] for r in rows] == ["q4", "q3", "q2"]


def test_stats_count_each_rule_and_remember_the_last_time(store):
    store.log_guardrail_event("C1", "block", "a")
    store.log_guardrail_event("C1", "block", "b")
    store.log_guardrail_event("C2", "warn", "c")
    stats = store.guardrail_stats()
    assert stats["C1"]["count"] == 2 and stats["C2"]["count"] == 1 and stats["C1"]["last_ts"] >= stats["C2"]["last_ts"] - 5
    assert "C3" not in stats


def test_an_unknown_action_is_not_logged(store):
    with pytest.raises(SettingsError):
        store.log_guardrail_event("C1", "explode", "a")
    assert store.guardrail_events(10) == []


# ----------------------------------------------------------------------------------------------- the GUARDRAIL ALERT label
def test_the_label_is_fixed_text_and_alert_block_puts_one_line_per_alert():
    assert gr.ALERT_LABEL == "GUARDRAIL ALERT:"
    block = gr.alert_block(["G1: ADANIGAS is not in the Nifty 50.", "G5: 80% in one group."])
    assert block.splitlines() == ["**GUARDRAIL ALERT:** G1: ADANIGAS is not in the Nifty 50.",
                                  "**GUARDRAIL ALERT:** G5: 80% in one group."]
    assert gr.alert_block([]) == ""


def test_with_alerts_puts_the_alerts_above_the_answer_and_leaves_a_clean_answer_alone():
    assert gr.with_alerts("The answer.", ["C1: Not a forecast."]) == "**GUARDRAIL ALERT:** C1: Not a forecast.\n\nThe answer."
    assert gr.with_alerts("The answer.", []) == "The answer."
    assert gr.with_alerts("", ["C1: x"]) == "**GUARDRAIL ALERT:** C1: x"


def test_portfolio_blocks_and_warnings_in_a_tool_result_become_alerts_in_order():
    text = ('{"symbols": ["A"], "guardrails": {"ok": false, "blocks": ["G1: WIPRO is not in the Nifty 50.", "G2: 7 stocks."], '
            '"warnings": ["G5: 80% in one group."]}, "footer": "x"}')
    assert gr.alerts_from_tool_text(text) == ["G1: WIPRO is not in the Nifty 50.", "G2: 7 stocks.", "G5: 80% in one group."]


def test_a_clean_guardrail_result_gives_no_alert():
    assert gr.alerts_from_tool_text('{"guardrails": {"ok": true, "blocks": [], "warnings": []}, "footer": "x"}') == []


@pytest.mark.parametrize("error, expected", [
    ("'ADANIGAS' is not one of the Nifty 50 stocks in the price data.", "G1: 'ADANIGAS' is not one of the Nifty 50 stocks in the price data."),
    ("'XYZ' is not one of the Nifty 50 stocks.", "G1: 'XYZ' is not one of the Nifty 50 stocks."),
    ("'Tesla' is not a Nifty 50 stock this app covers", "G1: 'Tesla' is not a Nifty 50 stock this app covers"),
    ("TSLA is not one of the Nifty 50 (include). This app covers only those 50 stocks.",
     "G1: TSLA is not one of the Nifty 50 (include). This app covers only those 50 stocks."),
    ("A portfolio holds 4 to 6 stocks (4 to 6). You asked for 10.", "G2/G3: A portfolio holds 4 to 6 stocks (4 to 6). You asked for 10."),
])
def test_a_guardrail_refusal_in_a_tool_error_becomes_an_alert(error, expected):
    import json
    assert gr.alerts_from_tool_text(json.dumps({"error": error})) == [expected]


@pytest.mark.parametrize("text", [
    '{"error": "tool failed"}', '{"error": "timed out after 180 s"}', '{"symbol": "TCS", "rsi": 55.2}', "plain text, not json", "",
    '{"error": 5}', "[1, 2]", "null",
])
def test_ordinary_errors_and_other_results_are_not_alerts(text):
    assert gr.alerts_from_tool_text(text) == []


def test_the_same_alert_is_listed_once():
    assert gr.dedupe(["a", "b", "a", "c", "b"]) == ["a", "b", "c"]


def test_the_catalog_lists_the_alert_label_as_a_built_hard_output_rule():
    row = {r["id"]: r for r in gr.CATALOG}["A8"]
    assert row["state"] == "built" and row["timing"] == "output" and row["strength"] == "hard" and "GUARDRAIL ALERT" in row["what"]
