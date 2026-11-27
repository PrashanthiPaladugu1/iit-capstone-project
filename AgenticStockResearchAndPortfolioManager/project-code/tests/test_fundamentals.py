import pytest

import fundamentals as fu
import fundamentals_db as fdb


@pytest.fixture(scope="module")
def tools(tmp_path_factory):
    db = tmp_path_factory.mktemp("fund") / "real.duckdb"
    fdb.build(db)
    return fu.Fundamentals(fdb.open_readonly(db))


def test_company_type_from_industry_group(tools):
    assert tools.company_type("TCS") == "industrial"
    assert tools.company_type("HDFCBANK") == "bank"
    assert tools.company_type("BAJFINANCE") == "finance"
    assert tools.company_type("HDFCLIFE") == "insurance"
    assert tools.company_type("BSE") == "industrial"


def test_get_financials_annual_known_values(tools):
    r = tools.get_financials("TCS", "profit_loss", ["Sales", "Net profit"], periods=3)
    assert r["symbol"] == "TCS" and r["unit_note"]
    sales = {row["period_end"]: row["value"] for row in r["rows"] if row["label"] == "Sales"}
    assert sales["2025-03-31"] == 255324.0 and sales["2026-03-31"] == 267021.0
    assert len(sales) == 3


def test_get_financials_rejects_bad_section_and_unknown_label(tools):
    with pytest.raises(fu.FundamentalsError, match="section"):
        tools.get_financials("TCS", "nonsense", None)
    with pytest.raises(fu.FundamentalsError, match="label"):
        tools.get_financials("TCS", "profit_loss", ["Not a label"])


def test_unknown_or_missing_stock(tools):
    with pytest.raises(fu.FundamentalsError, match="not one of the Nifty 50"):
        tools.get_financials("AAPL", "profit_loss", None)
    with pytest.raises(fu.FundamentalsError, match="no financial workbook"):
        tools.get_financials("SBILIFE", "profit_loss", None)


def test_growth_rates_are_computed_by_code(tools):
    r = tools.compute_growth("TCS", "Sales", years=1)
    row = r["rows"][-1]
    assert row["period_end"] == "2026-03-31"
    assert row["growth_pct"] == pytest.approx((267021.0 / 255324.0 - 1) * 100, abs=1e-3)


def test_cagr(tools):
    r = tools.compute_growth("TCS", "Net profit", years=3)
    assert r["cagr_pct"] == pytest.approx(((49210.0 / r["start_value"]) ** (1 / r["years_used"]) - 1) * 100, abs=1e-3)


def test_cagr_refuses_negative_or_zero_start(tools):
    r = tools.compute_growth("TCS", "Dividend Amount", years=1)
    assert "cagr_pct" in r                                          # works for positive values
    # a synthetic check of the guard itself
    assert fu.cagr(-5.0, 10.0, 3) is None and fu.cagr(0.0, 10.0, 3) is None and fu.cagr(5.0, 10.0, 0) is None


def test_ratios_for_industrial_company(tools):
    r = tools.compute_ratios("TCS")
    last = r["ratios"][-1]
    assert last["period_end"] == "2026-03-31"
    assert last["net_margin_pct"] == pytest.approx(49210.0 / 267021.0 * 100, abs=1e-3)
    assert last["roe_pct"] is not None and last["debt_to_equity"] is not None
    assert r["company_type"] == "industrial" and "warning" not in r


def test_ratios_for_bank_skip_industrial_measures_and_warn(tools):
    r = tools.compute_ratios("HDFCBANK")
    last = r["ratios"][-1]
    assert r["company_type"] == "bank" and r["warning"]
    assert last["roe_pct"] is not None and last["net_margin_pct"] is not None
    assert "debt_to_equity" not in last and "interest_cover" not in last and "operating_margin_pct" not in last


def test_ratios_for_insurer_skip_industrial_measures(tools):
    last = tools.compute_ratios("HDFCLIFE")["ratios"][-1]
    assert "debt_to_equity" not in last and "interest_cover" not in last


def test_valuation_uses_price_and_latest_earnings(tools):
    r = tools.get_valuation("TCS")
    assert r["current_price"] == 2406.6 and r["market_cap"] == 870728.94
    assert r["pe"] == pytest.approx(870728.94 / 49210.0, abs=1e-3)
    assert r["as_of_financials"] == "2026-03-31"


def test_valuation_notes_for_bank_not_applicable_measures(tools):
    r = tools.get_valuation("HDFCBANK")
    assert r["pe"] is not None and "ev_to_sales" not in r


def test_quarterly_results(tools):
    r = tools.get_quarterly("TCS", quarters=4)
    assert len(r["rows"]) == 4 and r["rows"][-1]["period_end"] == "2026-09-30"
    assert r["rows"][-1]["Sales"] == 73188.0


def test_list_available_labels(tools):
    r = tools.list_line_items("TCS")
    assert "Sales" in r["profit_loss"] and "Borrowings" in r["balance_sheet"] and "Operating Profit" in r["quarters"]


def test_coverage_says_what_is_missing(tools):
    r = tools.coverage()
    assert r["with_workbook"] == 49 and r["without_workbook"] == ["SBILIFE"]
