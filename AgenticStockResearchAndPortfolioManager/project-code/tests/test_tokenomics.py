"""Tokenomics: price per million tokens per provider and model, cost written with every call, cost limit in Budget.

Rules: a rate is never invented. No rate set means cost is None (unknown), not zero. Local Ollama is free by default.
"""
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from budget import Budget, BudgetExceeded  # noqa: E402
from gateway import Gateway  # noqa: E402
from model_settings import SettingsError, SettingsStore  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_gateway import MSG, Recorder  # noqa: E402


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "http://ollama.test:11434")
    monkeypatch.setenv("EXTERNAL_API_KEY", "ext_secret_456")
    store = SettingsStore(tmp_path / "settings.sqlite")
    fake = Recorder()
    gw = Gateway(store, tmp_path / "usage.sqlite", transport=httpx.MockTransport(fake), retries=0)
    return store, gw


# ----------------------------------------------------------------------------------- rates in settings
def test_local_ollama_is_free_by_default(env):
    store, _ = env
    assert store.get_rate("ollama_local", "gemma4:12b") == (0.0, 0.0)


def test_no_rate_for_an_external_provider_means_unknown_not_zero(env):
    store, _ = env
    assert store.get_rate("external_api", "some-model") is None


def test_set_and_read_a_rate_and_it_is_audited(env):
    store, _ = env
    store.set_rate("external_api", "m1", 0.5, 1.5)
    assert store.get_rate("external_api", "m1") == (0.5, 1.5)
    assert any(r["item"] == "rate:external_api:m1" for r in store.audit_log(10))


def test_a_negative_or_non_numeric_rate_is_rejected(env):
    store, _ = env
    with pytest.raises(SettingsError):
        store.set_rate("external_api", "m1", -1, 1)
    with pytest.raises(SettingsError):
        store.set_rate("external_api", "m1", "x", 1)


def test_rates_can_be_listed(env):
    store, _ = env
    store.set_rate("external_api", "m1", 1, 2)
    assert {"provider": "external_api", "model": "m1", "per_m_in": 1.0, "per_m_out": 2.0} in store.list_rates()


# ----------------------------------------------------------------------------------- cost in the usage log
def test_local_call_costs_zero(env):
    _, gw = env
    gw.chat("chat", MSG)
    row = gw.usage_rows(1)[0]
    assert row["cost_total"] == 0.0 and row["cost_known"] == 1


def test_external_call_cost_matches_a_hand_calculation(env):
    store, gw = env
    store.update_provider("external_api", base_url="http://api.test/v1", enabled=True)
    store.set_role("chat", "external_api", "m1")
    store.set_rate("external_api", "m1", 2.0, 10.0)          # per 1M tokens
    gw.chat("chat", MSG)                                       # the fake API reports 7 in, 3 out
    row = gw.usage_rows(1)[0]
    assert row["cost_in"] == pytest.approx(7 * 2.0 / 1_000_000)
    assert row["cost_out"] == pytest.approx(3 * 10.0 / 1_000_000)
    assert row["cost_total"] == pytest.approx(row["cost_in"] + row["cost_out"]) and row["cost_known"] == 1


def test_external_call_without_a_rate_is_flagged_unknown(env):
    store, gw = env
    store.update_provider("external_api", base_url="http://api.test/v1", enabled=True)
    store.set_role("chat", "external_api", "unpriced")
    gw.chat("chat", MSG)
    row = gw.usage_rows(1)[0]
    assert row["cost_total"] is None and row["cost_known"] == 0


def test_switching_provider_changes_the_cost_with_no_code_change(env):
    store, gw = env
    gw.chat("chat", MSG)
    store.update_provider("external_api", base_url="http://api.test/v1", enabled=True)
    store.set_role("chat", "external_api", "m1")
    store.set_rate("external_api", "m1", 1.0, 1.0)
    gw.chat("chat", MSG)
    first, second = gw.usage_rows(2)[1], gw.usage_rows(2)[0]
    assert first["cost_total"] == 0.0 and second["cost_total"] > 0


def test_embedding_calls_are_costed_on_input_tokens_only(env):
    store, gw = env
    store.update_provider("external_api", base_url="http://api.test/v1", enabled=True)
    store.set_role("embedding", "external_api", "emb1")
    store.set_rate("external_api", "emb1", 4.0, 99.0)
    gw.embed(["a", "b"])                                       # fake API reports 9 prompt tokens
    row = gw.usage_rows(1)[0]
    assert row["cost_in"] == pytest.approx(9 * 4.0 / 1_000_000) and row["cost_out"] == 0.0


def test_old_usage_table_is_upgraded_and_keeps_its_rows(tmp_path, monkeypatch):
    import sqlite3
    monkeypatch.setenv("OLLAMA_HOST", "http://ollama.test:11434")
    db = tmp_path / "usage.sqlite"
    con = sqlite3.connect(db)
    con.executescript("""CREATE TABLE calls(
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, parent_id INTEGER,
        session TEXT, agent TEXT, node TEXT, route TEXT, role TEXT NOT NULL, kind TEXT NOT NULL,
        provider TEXT, provider_kind TEXT, external INTEGER, model TEXT,
        tokens_in INTEGER, tokens_out INTEGER, tokens_estimated INTEGER,
        total_ms REAL, load_ms REAL, eval_ms REAL, tokens_per_s REAL,
        status TEXT NOT NULL, error TEXT, attempts INTEGER, preview TEXT);
        INSERT INTO calls(ts,role,kind,status,provider,model,tokens_in,tokens_out) VALUES(1,'chat','chat','ok','ollama_local','gemma4:12b',5,6);""")
    con.commit(); con.close()
    gw = Gateway(SettingsStore(tmp_path / "s.sqlite"), db, transport=httpx.MockTransport(Recorder()))
    old = gw.usage_rows(5)[-1]
    assert old["tokens_in"] == 5 and old["cost_total"] is None and old["cost_known"] == 0


# ----------------------------------------------------------------------------------- summaries for the Admin view
def test_summary_groups_tokens_and_cost(env):
    store, gw = env
    gw.chat("chat", MSG, agent="agent_technical")
    gw.chat("chat", MSG, agent="agent_fundamental")
    gw.embed(["x"], agent="rag_search")
    by_agent = {r["key"]: r for r in gw.summary("agent")}
    assert by_agent["agent_technical"]["calls"] == 1 and by_agent["agent_technical"]["tokens_in"] == 12
    assert {r["key"] for r in gw.summary("role")} == {"chat", "embedding"}
    assert {r["key"] for r in gw.summary("model")} == {"gemma4:12b", "nomic-embed-text"}
    assert len(gw.summary("day")) == 1


def test_summary_rejects_an_unknown_grouping(env):
    _, gw = env
    with pytest.raises(ValueError):
        gw.summary("password; drop table calls")


def test_spend_today_and_cap(env):
    store, gw = env
    store.update_provider("external_api", base_url="http://api.test/v1", enabled=True)
    store.set_role("chat", "external_api", "m1")
    store.set_rate("external_api", "m1", 1000.0, 1000.0)
    gw.chat("chat", MSG)
    assert gw.spend_today() == pytest.approx(10 * 1000.0 / 1_000_000)
    store.set_value("cost_cap", {"daily": 0.001})
    assert gw.cost_cap_state()["exceeded"] is True


def test_cost_cap_blocks_the_next_external_call_but_not_local_ones(env):
    store, gw = env
    store.update_provider("external_api", base_url="http://api.test/v1", enabled=True)
    store.set_role("chat", "external_api", "m1")
    store.set_rate("external_api", "m1", 1000.0, 1000.0)
    store.set_value("cost_cap", {"daily": 0.001})
    gw.chat("chat", MSG)                                       # first call goes through and exceeds the cap
    from gateway import GatewayError
    with pytest.raises(GatewayError, match="daily cost cap"):
        gw.chat("chat", MSG)
    store.set_role("chat", "ollama_local", "gemma4:12b")
    assert gw.chat("chat", MSG).text                           # local is free, so the cap does not stop it


def test_no_cap_by_default(env):
    store, gw = env
    assert store.get_value("cost_cap") == {"daily": None}
    assert gw.cost_cap_state()["exceeded"] is False


def test_cost_cap_validation(env):
    store, _ = env
    with pytest.raises(SettingsError):
        store.set_value("cost_cap", {"daily": -5})
    store.set_value("cost_cap", {"daily": None})


# ----------------------------------------------------------------------------------- budget in money
def test_budget_stops_on_cost():
    b = Budget(max_cost=0.01)
    b.before_model_call()
    b.after_model_call(10, 10, cost=0.02)
    with pytest.raises(BudgetExceeded, match="cost limit"):
        b.before_model_call()


def test_budget_without_a_cost_limit_ignores_cost():
    b = Budget()
    b.after_model_call(10, 10, cost=999)
    b.before_model_call()
    assert b.summary()["cost"] == 999


def test_budget_after_model_call_still_works_without_cost():
    b = Budget()
    b.after_model_call(3, 4)
    assert b.summary() == {"model_calls": 1, "tool_calls": 0, "tokens": 7, "cost": 0.0}


# ----------------------------------------------------------------------------------- what-if and call trace
def test_what_if_prices_the_same_tokens_on_every_rate(env):
    from tokenomics import what_if
    rates = [{"provider": "a", "model": "m1", "per_m_in": 1.0, "per_m_out": 2.0},
             {"provider": "b", "model": "m2", "per_m_in": 0.5, "per_m_out": 0.5}]
    rows = what_if(1_000_000, 500_000, rates)
    assert rows[0]["provider"] == "b" and rows[0]["cost"] == pytest.approx(0.75)      # cheapest first
    assert rows[1]["cost"] == pytest.approx(1.0 + 1.0)


def test_what_if_with_no_rates_is_empty():
    from tokenomics import what_if
    assert what_if(10, 10, []) == []


def test_session_calls_and_recent_sessions(env):
    _, gw = env
    gw.chat("chat", MSG, session="s1", agent="agent_technical", node="model")
    gw.chat("chat", MSG, session="s1", agent="agent_technical", node="model")
    gw.chat("chat", MSG, session="s2", agent="agent_fundamental", node="model")
    assert [r["session"] for r in gw.recent_sessions()] == ["s2", "s1"]
    assert gw.recent_sessions()[1]["calls"] == 2
    calls = gw.session_calls("s1")
    assert len(calls) == 2 and calls[0]["id"] < calls[1]["id"]


def test_call_tree_nests_children_under_their_parent():
    from tokenomics import call_tree
    rows = [{"id": 1, "parent_id": None, "agent": "agent_portfolio_manager", "role": "chat"},
            {"id": 2, "parent_id": 1, "agent": "agent_research_analyst", "role": "chat"},
            {"id": 3, "parent_id": 2, "agent": "agent_technical", "role": "chat"},
            {"id": 4, "parent_id": None, "agent": "agent_technical", "role": "embedding"}]
    out = call_tree(rows)
    assert [(r["id"], r["depth"]) for r in out] == [(1, 0), (2, 1), (3, 2), (4, 0)]


def test_call_tree_without_parents_is_flat_and_keeps_order():
    from tokenomics import call_tree
    rows = [{"id": 5, "parent_id": None}, {"id": 6, "parent_id": None}]
    assert [(r["id"], r["depth"]) for r in call_tree(rows)] == [(5, 0), (6, 0)]


def test_call_tree_survives_a_missing_parent_and_a_cycle():
    from tokenomics import call_tree
    rows = [{"id": 1, "parent_id": 99}, {"id": 2, "parent_id": 3}, {"id": 3, "parent_id": 2}]
    assert {r["id"] for r in call_tree(rows)} == {1, 2, 3}
