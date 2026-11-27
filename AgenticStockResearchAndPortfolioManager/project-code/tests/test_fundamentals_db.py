import datetime as dt

import openpyxl
import pytest

import config
import fundamentals_db as fdb


def make_workbook(path, name="ACME LTD", pl_sales=(100.0, 120.0), bank=False):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Data Sheet"
    d1, d2 = dt.datetime(2024, 3, 31), dt.datetime(2025, 3, 31)
    rows = [
        ["COMPANY NAME", name], ["LATEST VERSION", 2.1], ["CURRENT VERSION", 2.1], [],
        ["META"], ["Number of shares"], ["Face Value", 1.0], ["Current Price", 50.0], ["Market Capitalization", 5000.0],
        [], [], [], [], [],
        ["PROFIT & LOSS"], ["Report Date", d1, d2],
        ["Sales", *pl_sales], ["Raw Material Cost", 30.0, 35.0], ["Other Expenses", 20.0, 25.0],
        ["Other Income", 5.0, 6.0], ["Depreciation", 4.0, 5.0], ["Interest", 2.0, 3.0],
        ["Profit before tax", 49.0, 58.0], ["Tax", 12.0, 14.0], ["Net profit", 37.0, 44.0], [],
        ["Quarters"], ["Report Date", dt.datetime(2025, 6, 30), dt.datetime(2025, 9, 30)],
        ["Sales", 30.0, 32.0], ["Net profit", 10.0, 11.0], ["Operating Profit", 14.0, 15.0], [],
        ["BALANCE SHEET"], ["Report Date", d1, d2],
        ["Equity Share Capital", 100.0, 100.0], ["Reserves", 300.0, 380.0], ["Borrowings", 50.0, 40.0],
        ["Other Liabilities", 50.0, 60.0], ["Total", 500.0, 580.0],
        ["Net Block", 200.0, 220.0], ["Other Assets", 300.0, 360.0], ["Total", 500.0, 580.0], [],
        ["CASH FLOW:"], ["Report Date", d1, d2],
        ["Cash from Operating Activity", 40.0, 50.0], ["Net Cash Flow", 1.0, 2.0], [],
        ["PRICE:", 40.0, 50.0], [],
        ["DERIVED:"], ["Adjusted Equity Shares in Cr", 100.0, 100.0],
    ]
    for row in rows:
        ws.append(row)
    wb.save(path)


def test_parse_workbook_sections_labels_and_dates(tmp_path):
    f = tmp_path / "Financials_ACME.xlsx"
    make_workbook(f)
    p = fdb.parse_workbook(f)
    assert p["meta"]["company_name"] == "ACME LTD" and p["meta"]["current_price"] == 50.0
    by = {(r["section"], r["label"], r["period_end"]): r["value"] for r in p["rows"]}
    assert by[("profit_loss", "Sales", dt.date(2025, 3, 31))] == 120.0
    assert by[("quarters", "Operating Profit", dt.date(2025, 9, 30))] == 15.0
    assert by[("cash_flow", "Net Cash Flow", dt.date(2024, 3, 31))] == 1.0
    assert by[("derived", "Adjusted Equity Shares in Cr", dt.date(2025, 3, 31))] == 100.0
    assert by[("price", "Year-end price", dt.date(2025, 3, 31))] == 50.0


def test_two_balance_sheet_totals_get_distinct_names(tmp_path):
    f = tmp_path / "Financials_ACME.xlsx"
    make_workbook(f)
    labels = {r["label"] for r in fdb.parse_workbook(f)["rows"] if r["section"] == "balance_sheet"}
    assert {"Total liabilities", "Total assets"} <= labels and "Total" not in labels


def test_empty_cells_are_skipped(tmp_path):
    f = tmp_path / "Financials_ACME.xlsx"
    make_workbook(f)
    assert all(r["value"] is not None for r in fdb.parse_workbook(f)["rows"])


def test_find_workbook_handles_ampersand_name(tmp_path, monkeypatch):
    monkeypatch.setattr(fdb, "_docs_dir", lambda: tmp_path)
    (tmp_path / "M&M").mkdir()
    make_workbook(tmp_path / "M&M" / "Financials_M_M.xlsx")
    assert fdb.find_workbook("M&M").name == "Financials_M_M.xlsx"
    assert fdb.find_workbook("SBILIFE") is None


def test_build_and_read_back(tmp_path, monkeypatch):
    monkeypatch.setattr(fdb, "_docs_dir", lambda: tmp_path / "data")
    (tmp_path / "data" / "ACME").mkdir(parents=True)
    make_workbook(tmp_path / "data" / "ACME" / "Financials_ACME.xlsx")
    (tmp_path / "data" / "NOBOOK").mkdir()
    db = tmp_path / "f.duckdb"
    res = fdb.build(db, symbols=["ACME", "NOBOOK"])
    assert res["loaded"] == ["ACME"] and res["missing"] == ["NOBOOK"]
    con = fdb.open_readonly(db)
    n = con.execute("select count(*) from fin_values where symbol='ACME'").fetchone()[0]
    assert n > 20


def test_rebuild_keeps_the_old_database(tmp_path, monkeypatch):
    monkeypatch.setattr(fdb, "_docs_dir", lambda: tmp_path / "data")
    (tmp_path / "data" / "ACME").mkdir(parents=True)
    make_workbook(tmp_path / "data" / "ACME" / "Financials_ACME.xlsx")
    db = tmp_path / "f.duckdb"
    fdb.build(db, symbols=["ACME"])
    fdb.build(db, symbols=["ACME"])
    kept = [p.name for p in tmp_path.glob("f.*.duckdb")]
    assert len(kept) == 1 and db.exists()                      # old file renamed to a dated name, never removed


@pytest.fixture(scope="module")
def real_db(tmp_path_factory):
    db = tmp_path_factory.mktemp("fdb") / "real.duckdb"
    res = fdb.build(db)
    return db, res


def test_real_build_loads_49_and_misses_only_sbilife(real_db):
    _, res = real_db
    assert len(res["loaded"]) == 49 and res["missing"] == ["SBILIFE"]
    assert "M&M" in res["loaded"]


def test_real_tcs_known_values(real_db):
    db, _ = real_db
    con = fdb.open_readonly(db)
    sales = con.execute("select value from fin_values where symbol='TCS' and section='profit_loss' and label='Sales' "
                        "and period_end=DATE '2017-03-31'").fetchone()[0]
    assert sales == 117966.0
    npf = con.execute("select value from fin_values where symbol='TCS' and section='profit_loss' and label='Net profit' "
                      "and period_end=DATE '2017-03-31'").fetchone()[0]
    assert npf == 26289.0
