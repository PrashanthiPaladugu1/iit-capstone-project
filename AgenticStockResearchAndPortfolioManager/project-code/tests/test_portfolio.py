"""guardrails, scorecard and portfolio maths. Synthetic prices for the exact checks, the real databases for one end-to-end check."""
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import guardrails as gr  # noqa: E402
import portfolio as pf  # noqa: E402
import scorecard as sc  # noqa: E402


# ----------------------------------------------------------------------------------------------- synthetic data
def history(growth=0.0, wobble=0.0, n=300, jump_at=None, jump=-0.5):
    """n trading days. Close grows `growth` a day, with an alternating +/- `wobble` that sets the volatility."""
    start, close, rows = date(2025, 1, 1), 100.0, []
    for i in range(n):
        if i:
            close *= (1 + growth) * (1 + wobble * (1 if i % 2 else -1))
            if jump_at is not None and i == jump_at:
                close *= (1 + jump)
        rows.append({"date": start + timedelta(days=i), "close": close})
    return pd.DataFrame(rows)


STOCKS = [{"symbol": s, "name": s.title(), "industry_group": g} for s, g in
          [("AAA", "IT"), ("BBB", "IT"), ("CCC", "Banks"), ("DDD", "Auto"), ("EEE", "Pharma"), ("FFF", "Metals")]]


def table(rows):
    cols = ["symbol", "price_to_earning", "industry_pe", "return_on_capital_employed", "profit_growth", "npm_latest_quarter"]
    return {"as_of": "2026-11-20", "columns": cols, "rows": [[s] + v for s, v in rows.items()]}


GOOD = {"AAA": [10, 20, 30, 20, 15], "BBB": [30, 20, 10, 5, 5], "CCC": [15, 15, 8, 12, 20],
        "DDD": [20, 20, 20, 10, 10], "EEE": [12, 24, 25, 18, 14], "FFF": [8, 16, 12, 9, 7]}


def make_scorecard(histories=None, rows=None):
    histories = histories or {
        "AAA": history(0.0020, 0.001), "BBB": history(0.0001, 0.020), "CCC": history(0.0008, 0.005),
        "DDD": history(0.0005, 0.010), "EEE": history(0.0012, 0.003), "FFF": history(-0.0003, 0.008)}
    return sc.Scorecard(history=lambda s: histories[s], table=lambda: table(rows or GOOD), stocks=STOCKS)


# ----------------------------------------------------------------------------------------------- scorecard
def test_percentile_ranks_best_is_100_worst_is_0_ties_share_and_missing_stay_missing():
    got = sc.percentile_ranks({"a": 1.0, "b": 2.0, "c": 3.0, "d": None})
    assert got == {"a": 0.0, "b": 50.0, "c": 100.0, "d": None}
    assert sc.percentile_ranks({"a": 1.0, "b": 1.0, "c": 3.0})["a"] == sc.percentile_ranks({"a": 1.0, "b": 1.0, "c": 3.0})["b"]
    assert sc.percentile_ranks({"a": 1.0, "b": 2.0}, higher_is_better=False) == {"a": 100.0, "b": 0.0}
    assert sc.percentile_ranks({"a": 5.0}) == {"a": 50.0}
    assert sc.percentile_ranks({}) == {}


def test_clean_returns_drop_a_split_sized_day_and_count_it():
    returns, jumps = sc.clean_returns(history(0.001, 0.0, n=100, jump_at=50, jump=-0.6))
    assert jumps == 1 and returns.isna().sum() == 1 + 1          # the first row has no return, and the jump day
    assert returns.dropna().max() < 0.01


def test_factors_rank_the_right_way_round():
    card = make_scorecard().score_all("balanced")
    rows = {r["symbol"]: r for r in card["rows"]}
    assert rows["AAA"]["momentum"] == 100.0 and rows["FFF"]["momentum"] == 0.0            # fastest and slowest riser
    assert rows["AAA"]["risk"] == 100.0 and rows["BBB"]["risk"] == 0.0                    # calmest and most volatile (high score = low risk)
    assert rows["AAA"]["valuation"] > rows["BBB"]["valuation"]                            # P/E 10 against 25 beats 30 against 20
    assert rows["AAA"]["quality"] > rows["FFF"]["quality"]
    assert card["as_of"]["screener"] == "2026-11-20" and "not a forecast" in card["caveat"].lower()
    totals = [r["total"] for r in card["rows"]]
    assert totals == sorted(totals, reverse=True)                                         # best first


def test_strategy_changes_the_order():
    s = make_scorecard()
    momentum_first = s.score_all("momentum")["rows"][0]["symbol"]
    low_risk_first = s.score_all("low_risk")["rows"][0]["symbol"]
    assert momentum_first == "AAA" and low_risk_first == "AAA"
    value_order = [r["symbol"] for r in s.score_all("value")["rows"]]
    assert value_order.index("AAA") < value_order.index("BBB")
    with pytest.raises(sc.ScorecardError, match="Valid strategies"):
        s.score_all("yolo")


def test_missing_data_is_left_missing_not_guessed():
    rows = {**GOOD, "BBB": [None, None, None, None, None]}
    histories = {"AAA": history(0.002, 0.001), "BBB": history(0.0001, 0.02, n=40), "CCC": history(0.0008, 0.005),
                 "DDD": history(0.0005, 0.01), "EEE": history(0.0012, 0.003), "FFF": history(-0.0003, 0.008)}
    row = {r["symbol"]: r for r in make_scorecard(histories, rows).score_all()["rows"]}["BBB"]
    assert row["valuation"] is None and row["quality"] is None and row["momentum"] is None and row["risk"] is None
    assert row["total"] is None                                                           # fewer than two factors: no score
    assert "short price history" in " ".join(row["flags"])


def test_a_price_jump_in_the_window_drops_the_return_and_is_flagged():
    histories = {"AAA": history(0.002, 0.001, jump_at=250), "BBB": history(0.0001, 0.02), "CCC": history(0.0008, 0.005),
                 "DDD": history(0.0005, 0.01), "EEE": history(0.0012, 0.003), "FFF": history(-0.0003, 0.008)}
    row = {r["symbol"]: r for r in make_scorecard(histories).score_all()["rows"]}["AAA"]
    assert row["inputs"]["ret_6m"] is None and row["inputs"]["ret_3m"] is None and row["momentum"] is None
    assert row["inputs"]["vol_1y_pct"] is not None and row["inputs"]["vol_1y_pct"] < 10   # the split day is not counted as risk
    assert any("jump" in f for f in row["flags"])


def test_roce_is_not_used_for_banks():
    row = {r["symbol"]: r for r in make_scorecard().score_all()["rows"]}["CCC"]            # CCC is in the group "Banks"
    assert row["inputs"]["roce"] is None


def test_suggest_takes_one_stock_per_industry_group_and_honours_include_and_exclude():
    tools = pf.PortfolioTools(make_scorecard())
    out = tools.suggest("balanced", 5)
    groups = [p["industry_group"] for p in out["picks"]]
    assert len(out["picks"]) == 5 and len(set(groups)) == 5                                # AAA and BBB share "IT": only one is taken
    assert not ({"AAA", "BBB"} <= {p["symbol"] for p in out["picks"]})
    assert out["skipped_same_group"]
    forced = tools.suggest("balanced", 5, include=["BBB"])
    assert "BBB" in [p["symbol"] for p in forced["picks"]] and "AAA" not in [p["symbol"] for p in forced["picks"]]
    left_out = tools.suggest("balanced", 5, exclude=["AAA"])
    assert "AAA" not in [p["symbol"] for p in left_out["picks"]]
    with pytest.raises(pf.PortfolioError, match="not one of the Nifty 50"):
        tools.suggest("balanced", 4, include=["TESLA"])
    with pytest.raises(pf.PortfolioError, match="4 to 6"):
        tools.suggest("balanced", 8)


# ----------------------------------------------------------------------------------------------- weights
def test_bound_weights_sum_to_100_and_stay_inside_5_and_40():
    out = pf.bound_weights({"A": 90, "B": 5, "C": 3, "D": 2})
    assert out["A"] == pytest.approx(40.0) and sum(out.values()) == pytest.approx(100.0, abs=0.01)
    assert min(out.values()) >= 5.0 - 1e-9 and max(out.values()) <= 40.0 + 1e-9
    assert pf.bound_weights({"A": 1, "B": 1, "C": 1, "D": 1}) == {"A": 25.0, "B": 25.0, "C": 25.0, "D": 25.0}
    with pytest.raises(pf.PortfolioError):
        pf.bound_weights({"A": 1, "B": 1})                                                 # two stocks cannot stay under 40%


def test_inverse_volatility_gives_the_calmer_stock_more():
    w = pf.make_weights("inverse_vol", ["A", "B", "C", "D"], {"A": 10.0, "B": 20.0, "C": 20.0, "D": 20.0})
    assert w["A"] > w["B"] and sum(w.values()) == pytest.approx(100.0, abs=0.01)
    assert pf.make_weights("equal", ["A", "B", "C", "D", "E"])["E"] == 20.0
    with pytest.raises(pf.PortfolioError, match="Valid weighting"):
        pf.make_weights("magic", ["A", "B", "C", "D"])


# ----------------------------------------------------------------------------------------------- evaluate (exact maths)
def test_evaluate_buy_and_hold_return_drawdown_and_jump_handling():
    hist = {"A": history(0.001, 0.0), "B": history(0.0, 0.0)}
    out = pf.evaluate(hist, {"A": 50.0, "B": 50.0}, days=100)
    assert out["window"]["trading_days"] == 100
    assert out["total_return_pct"] == pytest.approx((0.5 * 1.001 ** 99 + 0.5 - 1) * 100, abs=0.02)
    assert out["max_drawdown_pct"] == 0.0 and out["stocks"]["B"]["return_pct"] == 0.0
    hist["B"] = history(0.0, 0.0, jump_at=250, jump=-0.5)
    out = pf.evaluate(hist, {"A": 50.0, "B": 50.0}, days=100)
    assert out["jump_days"] == {"B": 1} and out["stocks"]["B"]["return_pct"] == 0.0        # the split is not a loss
    assert "not a forecast" in out["caveat"].lower()


def test_evaluate_needs_enough_common_history():
    with pytest.raises(pf.PortfolioError, match="common"):
        pf.evaluate({"A": history(n=300), "B": history(n=30)}, {"A": 50.0, "B": 50.0}, days=252)


# ----------------------------------------------------------------------------------------------- guardrails
NIFTY = {"AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG", "HHH"}
GROUPS = {"AAA": "IT", "BBB": "IT", "CCC": "Banks", "DDD": "Auto", "EEE": "Pharma", "FFF": "Metals", "GGG": "Oil", "HHH": "FMCG"}


def check(symbols, weights=None, days=None):
    return gr.check_portfolio(symbols, weights=weights, universe=NIFTY, groups=GROUPS,
                              history_days=days or {s: 1000 for s in symbols})


def test_g1_only_nifty_50_and_no_duplicates():
    out = check(["AAA", "CCC", "DDD", "TESLA"])
    assert out["ok"] is False and any("G1" in b and "TESLA" in b for b in out["blocks"])
    assert any("twice" in b for b in check(["AAA", "AAA", "CCC", "DDD"])["blocks"])
    assert check(["aaa", "ccc", "ddd", "eee"])["ok"] is True                                # case does not matter


def test_g2_g3_portfolio_size_is_4_to_6():
    assert any("G2" in b and "7" in b for b in check(["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG"])["blocks"])
    assert any("G3" in b for b in check(["AAA", "CCC", "DDD"])["blocks"])
    assert check(["AAA", "CCC", "DDD", "EEE", "FFF", "GGG"])["ok"] is True


def test_g4_weights_must_sum_to_100_and_stay_between_5_and_40():
    names = ["AAA", "CCC", "DDD", "EEE"]
    assert check(names, {"AAA": 25, "CCC": 25, "DDD": 25, "EEE": 25})["ok"] is True
    assert any("G4" in b and "100" in b for b in check(names, {"AAA": 30, "CCC": 25, "DDD": 25, "EEE": 25})["blocks"])
    assert any("G4" in b and "40" in b for b in check(names, {"AAA": 45, "CCC": 25, "DDD": 20, "EEE": 10})["blocks"])
    assert any("G4" in b and "5" in b for b in check(names, {"AAA": 40, "CCC": 30, "DDD": 27, "EEE": 3})["blocks"])
    assert any("G4" in b for b in check(names, {"AAA": 50, "CCC": 50})["blocks"])           # weights for the wrong stocks


def test_g5_more_than_half_in_one_group_warns_but_does_not_block():
    out = check(["AAA", "BBB", "CCC", "DDD"], {"AAA": 30, "BBB": 30, "CCC": 20, "DDD": 20})
    assert out["ok"] is True and any("G5" in w and "IT" in w for w in out["warnings"])
    assert not any("G5" in w for w in check(["AAA", "CCC", "DDD", "EEE"])["warnings"])


def test_g6_under_252_trading_days_warns_and_names_the_stock():
    out = check(["AAA", "CCC", "DDD", "EEE"], days={"AAA": 1000, "CCC": 260, "DDD": 251, "EEE": 100})
    warns = " ".join(out["warnings"])
    assert out["ok"] is True and "DDD" in warns and "EEE" in warns and "CCC" not in warns


def test_g7_footer_has_disclaimer_date_and_the_unadjusted_note():
    text = gr.footer("2026-11-13")
    assert "not investment advice" in text.lower() and "2026-11-13" in text and "not adjusted" in text.lower()


# ----------------------------------------------------------------------------------------------- real data, end to end
@pytest.fixture(scope="module")
def real():
    return pf.PortfolioTools.default()


def test_real_scorecard_scores_all_50_with_a_date(real):
    card = real.scorecard.score_all("balanced")
    assert len(card["rows"]) == 50 and card["as_of"]["prices"] and card["as_of"]["screener"]
    scored = [r for r in card["rows"] if r["total"] is not None]
    assert len(scored) >= 45 and all(0 <= r["total"] <= 100 for r in scored)


def test_real_build_returns_a_checked_portfolio_with_exact_weights(real):
    out = real.build("balanced", 5, "equal")
    assert len(out["picks"]) == 5 and sum(out["weights"].values()) == pytest.approx(100.0, abs=0.01)
    assert out["guardrails"]["ok"] is True and out["backtest"]["window"]["trading_days"] >= 200
    assert len({p["industry_group"] for p in out["picks"]}) == 5
    assert out["as_of"] and "G7" not in out["footer"] and "not investment advice" in out["footer"].lower()
    again = real.build("balanced", 5, "equal")
    assert [p["symbol"] for p in again["picks"]] == [p["symbol"] for p in out["picks"]]     # the same input gives the same list


def test_real_evaluate_blocks_a_bad_list_and_tmpv_is_not_warned_at_260_days(real):
    bad = real.evaluate(["TCS", "INFY", "TESLA", "ITC"])
    assert bad["guardrails"]["ok"] is False and bad["backtest"] is None
    good = real.evaluate(["TCS", "HDFCBANK", "ITC", "TMPV"], None, 252)
    assert good["guardrails"]["ok"] is True
    assert not any("TMPV" in w for w in good["guardrails"]["warnings"])
