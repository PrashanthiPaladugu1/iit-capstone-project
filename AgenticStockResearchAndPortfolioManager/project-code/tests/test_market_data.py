"""market_data tools on the real built database, plus the MCP wrapper listing."""
import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
import market_data as md  # noqa: E402
import prices_db  # noqa: E402


@pytest.fixture(scope="module")
def tools(tmp_path_factory):
    db = tmp_path_factory.mktemp("db") / "real.duckdb"
    prices_db.build(db, config.prices_dir())
    return md.MarketData(prices_db.open_readonly(db))


def test_nifty50_list_has_50_and_all_have_prices(tools):
    syms = md.nifty50_symbols()
    assert len(syms) == 50 and set(syms) == set(prices_db.symbols(tools._con))


def test_latest_quote_matches_file(tools):
    q = tools.get_latest_quote("tcs")
    assert (q["date"], q["close"], q["prev_close"], q["volume"]) == ("2026-11-13", 2407.5, 2442.4, 3344738)
    assert q["change_pct"] == pytest.approx((2407.5 / 2442.4 - 1) * 100, abs=1e-3)
    assert q["as_of"] == "2026-11-13" and "not adjusted" in q["caveat"]


def test_unknown_and_non_nifty_symbols_are_rejected(tools):
    for bad in ("TESLA", "", "NIFTY 50", "../x"):
        with pytest.raises(md.MarketDataError):
            tools.get_latest_quote(bad)


def test_ohlcv_limits_rows_and_is_json_safe(tools):
    out = tools.get_ohlcv("INFY", days=5)
    assert len(out["rows"]) == 5 and out["rows"][-1]["date"] == "2026-11-13"
    assert len(tools.get_ohlcv("INFY", days=100000)["rows"]) == md.MAX_ROWS
    json.dumps(out)


def test_returns_and_52w_and_indicators(tools):
    r = tools.get_returns("TCS")
    assert set(r["returns_pct"]) == {"1D", "1W", "1M", "3M", "6M", "1Y"} and r["trading_days_available"] == 1147
    h = tools.get_52w_high_low("TCS")
    assert h["full_year"] and h["low"] < h["close"] < h["high"] and h["below_high_pct"] < 0
    json.dumps([r, h, tools.get_indicators("TCS")])


def test_short_history_stock_gets_a_note_not_made_up_numbers(tmp_path):
    src = config.pattern("price_file", symbol="TCS").read_text().splitlines()
    (tmp_path / "prices").mkdir()
    (tmp_path / "prices" / "TCS.csv").write_text("\n".join(src[:31]) + "\n")  # header + 30 days
    prices_db.build(tmp_path / "short.duckdb", tmp_path / "prices")
    short = md.MarketData(prices_db.open_readonly(tmp_path / "short.duckdb"))
    out = short.get_indicators("TCS")
    assert out["indicators"]["sma_200"] is None and "Not enough history" in out["note"]
    assert out["indicators"]["sma_20"] is not None
    assert short.get_52w_high_low("TCS")["full_year"] is False


def test_compare_and_top_movers(tools):
    c = tools.compare_stocks(["TCS", "infy", "TCS"])
    assert [r["symbol"] for r in c["rows"]] == ["TCS", "INFY"]
    with pytest.raises(md.MarketDataError):
        tools.compare_stocks(["TCS"])
    m = tools.top_movers("1M", 3)
    assert len(m["best"]) == 3 and m["best"][0]["return_pct"] >= m["best"][-1]["return_pct"]
    assert m["worst"][0]["return_pct"] <= m["worst"][-1]["return_pct"]
    assert m["best"][0]["return_pct"] >= m["worst"][0]["return_pct"]
    with pytest.raises(md.MarketDataError):
        tools.top_movers("2Y")


def test_top_movers_skips_stocks_with_too_little_history(tools):
    m = tools.top_movers("1Y", 5)
    assert isinstance(m["skipped_short_history"], list)       # TMPV has 260 days, enough for 252; none may be skipped
    assert "TMPV" not in m["skipped_short_history"]


def test_data_status(tools):
    s = tools.data_status()
    assert s["last_date"] == "2026-11-13" and s["symbols"] == 50 and s["rows"] == 55167


def test_list_stocks_returns_all_50_with_names_and_groups(tools):
    res = tools.list_stocks()
    assert res["count"] == 50 and len(res["stocks"]) == 50
    tcs = [s for s in res["stocks"] if s["symbol"] == "TCS"][0]
    assert tcs["name"] and tcs["industry_group"]
    assert {s["symbol"] for s in res["stocks"]} == set(prices_db.symbols(tools._con))
    assert res["as_of"] == "2026-11-13"


def test_mcp_server_lists_the_tools_and_calls_one(monkeypatch):
    import mcp_market_data as server
    monkeypatch.setattr(server, "_data", None)
    names = {t.name for t in asyncio.run(server.mcp.list_tools())} if not hasattr(
        asyncio.run(server.mcp.list_tools()), "tools") else {t.name for t in asyncio.run(server.mcp.list_tools()).tools}
    assert {"get_latest_quote", "get_ohlcv", "get_returns", "get_52w_high_low", "get_delivery_pct", "get_indicators",
            "compare_stocks", "top_movers", "data_status", "list_stocks"} <= names


def test_server_returns_error_text_for_bad_symbol(monkeypatch, tools):
    import mcp_market_data as server
    monkeypatch.setattr(server, "_data", tools)
    assert "error" in json.loads(server.get_latest_quote("TESLA"))
    assert json.loads(server.get_latest_quote("TCS"))["close"] == 2407.5
