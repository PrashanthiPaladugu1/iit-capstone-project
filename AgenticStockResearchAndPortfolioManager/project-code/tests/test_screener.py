"""screener_db (CSV snapshots to DuckDB) and screener (the tools behind the screener_* tools of the fundamental agent)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import screener_db  # noqa: E402
from screener import Screener, ScreenerError  # noqa: E402

HEADER = ("Name,BSE Code,NSE Code,ISIN Code,Industry Group,Industry,Current Price,RSI,Price to Earning,Industry PE,"
          "OPM latest quarter,NPM latest quarter,Return on capital employed,Debt to equity,FII holding,Enterprise Value")
ROWS = {
    "AAA": "Alpha Ltd,1,AAA,INE1,IT - Software,IT Services,100.0,55.5,20.0,25.0,24.0,18.0,30.0,0.1,10.0,900.0",
    "BBB": "Beta Ltd,2,BBB,INE2,Banks,Private Sector Bank,200.0,40.1,12.0,14.0,41.0,22.0,7.0,6.5,30.0,800.0",
    "CCC": "Gamma Ltd,3,CCC,INE3,Automobiles,Cars,300.0,70.2,,18.0,10.0,6.0,15.0,0.9,20.0,700.0",
    "ZZZ": "Outsider Ltd,4,ZZZ,INE4,Banks,Private Sector Bank,50.0,50.0,9.0,9.0,5.0,5.0,5.0,1.0,1.0,100.0",
}


def write_csv(folder, stamp, edits=None):
    """One snapshot file. `edits` changes a value per symbol: {"AAA": {"RSI": 99.0}}."""
    cols = HEADER.split(",")
    lines = [HEADER]
    for sym, row in ROWS.items():
        values = row.split(",")
        for key, val in (edits or {}).get(sym, {}).items():
            values[cols.index(key)] = str(val)
        lines.append(",".join(values))
    path = Path(folder) / f"EquityData-All-Stocks_EquityData-All-Stocks_2026_{stamp}.csv"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def csv_dir(tmp_path):
    d = tmp_path / "csv"
    d.mkdir()
    write_csv(d, "20260601_090000", {"AAA": {"RSI": 40.0, "Price to Earning": 18.0}})
    write_csv(d, "20260605_020000", {"AAA": {"RSI": 50.0}})
    write_csv(d, "20260605_230000")                                    # second file the same day: this one wins
    return d


@pytest.fixture
def db(tmp_path, csv_dir):
    path = tmp_path / "screener.duckdb"
    screener_db.build(db_path=path, csv_dir=csv_dir, symbols=["AAA", "BBB", "CCC"])
    return path


@pytest.fixture
def sc(db):
    return Screener(screener_db.open_readonly(db))


# ------------------------------------------------------------------ screener_db
def test_build_keeps_only_the_given_symbols_and_the_last_file_of_each_day(db):
    con = screener_db.open_readonly(db)
    assert {r[0] for r in con.execute("select distinct symbol from snapshots").fetchall()} == {"AAA", "BBB", "CCC"}
    assert con.execute("select count(*) from snapshots").fetchone()[0] == 6          # 2 days x 3 stocks
    row = con.execute("select snap_date, snap_time, rsi from snapshots where symbol='AAA' order by snap_date desc").fetchone()
    assert str(row[0]) == "2026-06-05" and row[1] == "230000" and row[2] == 55.5      # the 23:00 file, not the 02:00 one


def test_build_reports_counts_and_unknown_symbols(tmp_path, csv_dir):
    out = screener_db.build(db_path=tmp_path / "s.duckdb", csv_dir=csv_dir, symbols=["AAA", "NOPE"])
    assert out["files"] == 3 and out["days"] == 2 and out["stocks"] == 1
    assert out["missing"] == ["NOPE"] and out["kept_old"] == ""


def test_rebuild_keeps_the_old_database_under_a_dated_name(tmp_path, csv_dir):
    target = tmp_path / "s.duckdb"
    screener_db.build(db_path=target, csv_dir=csv_dir, symbols=["AAA"])
    again = screener_db.build(db_path=target, csv_dir=csv_dir, symbols=["AAA", "BBB"])
    kept = Path(again["kept_old"])
    assert kept.exists() and kept != target and target.exists()
    assert screener_db.open_readonly(kept).execute("select count(distinct symbol) from snapshots").fetchone()[0] == 1


def test_build_without_csv_files_is_an_error(tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(FileNotFoundError):
        screener_db.build(db_path=tmp_path / "s.duckdb", csv_dir=tmp_path / "empty", symbols=["AAA"])


def test_open_readonly_missing_database_names_the_build_command(tmp_path):
    with pytest.raises(FileNotFoundError, match="screener_db.py"):
        screener_db.open_readonly(tmp_path / "none.duckdb")


# ------------------------------------------------------------------ get_table
def test_table_returns_the_requested_metrics_with_short_names_and_the_snapshot_date(sc):
    out = sc.get_table(["pe", "rsi", "opm", "npm"])
    assert out["as_of"] == "2026-06-05"
    assert out["columns"] == ["symbol", "price_to_earning", "rsi", "opm_latest_quarter", "npm_latest_quarter"]
    rows = {r[0]: r for r in out["rows"]}
    assert rows["AAA"] == ["AAA", 20.0, 55.5, 24.0, 18.0]
    assert out["count"] == 3


def test_table_blanks_margin_and_debt_measures_for_banks_and_says_so(sc):
    out = sc.get_table(["opm", "npm", "debt_to_equity"])
    bank = next(r for r in out["rows"] if r[0] == "BBB")
    assert bank[1] is None and bank[3] is None and bank[2] == 22.0                    # NPM kept, OPM and D/E blanked
    assert "BBB" in out["note"] and "bank" in out["note"].lower()
    industrial = next(r for r in out["rows"] if r[0] == "AAA")
    assert industrial[1] == 24.0 and industrial[3] == 0.1


def test_table_sorts_with_missing_values_last_and_applies_the_limit(sc):
    out = sc.get_table(["pe"], sort_by="pe", descending=False, limit=2)
    assert [r[0] for r in out["rows"]] == ["BBB", "AAA"] and out["count"] == 2
    desc = sc.get_table(["pe"], sort_by="pe", descending=True)
    assert [r[0] for r in desc["rows"]] == ["AAA", "BBB", "CCC"]                      # CCC has no P/E: last either way


def test_table_filters_and_industry_group(sc):
    assert [r[0] for r in sc.get_table(["roce"], min_values={"roce": 10})["rows"]] == ["AAA", "CCC"]
    assert [r[0] for r in sc.get_table(["rsi"], max_values={"rsi": 50})["rows"]] == ["BBB"]
    assert [r[0] for r in sc.get_table(["rsi"], industry_group="banks")["rows"]] == ["BBB"]


def test_table_accepts_text_columns_and_full_names(sc):
    out = sc.get_table(["industry_group", "Price to Earning"])
    assert out["columns"] == ["symbol", "industry_group", "price_to_earning"]
    assert out["rows"][0][1] == "IT - Software"


def test_table_rejects_unknown_metrics_and_lists_the_valid_ones(sc):
    with pytest.raises(ScreenerError, match="rsi"):
        sc.get_table(["pe", "magic"])
    with pytest.raises(ScreenerError):
        sc.get_table(["pe"], sort_by="magic")
    with pytest.raises(ScreenerError):
        sc.get_table(["pe"], min_values={"magic": 1})
    with pytest.raises(ScreenerError):
        sc.get_table([])
    with pytest.raises(ScreenerError, match="industry group"):
        sc.get_table(["pe"], industry_group="Nonsense")


def test_table_limit_is_capped_and_must_be_positive(sc):
    assert sc.get_table(["pe"], limit=1000)["count"] == 3
    with pytest.raises(ScreenerError):
        sc.get_table(["pe"], limit=0)


# ------------------------------------------------------------------ get_snapshot
def test_snapshot_has_every_metric_of_one_stock(sc):
    out = sc.get_snapshot("aaa")
    assert out["symbol"] == "AAA" and out["as_of"] == "2026-06-05" and out["industry_group"] == "IT - Software"
    assert out["values"]["rsi"] == 55.5 and out["values"]["price_to_earning"] == 20.0 and out["values"]["fii_holding"] == 10.0
    assert "bse_code" not in out["values"] and "name" not in out["values"]
    assert "not live" in out["caveat"].lower()


def test_snapshot_for_a_bank_has_no_margin_or_debt_values_and_a_warning(sc):
    out = sc.get_snapshot("BBB")
    assert out["values"]["opm_latest_quarter"] is None and out["values"]["debt_to_equity"] is None
    assert out["values"]["npm_latest_quarter"] == 22.0 and "bank" in out["warning"].lower()


def test_snapshot_rejects_a_symbol_that_is_not_loaded(sc):
    for bad in ("ZZZ", "", "TESLA"):
        with pytest.raises(ScreenerError, match="Nifty 50"):
            sc.get_snapshot(bad)


# ------------------------------------------------------------------ get_history
def test_history_lists_one_metric_over_the_snapshot_dates_oldest_first(sc):
    out = sc.get_history("AAA", "rsi")
    assert out["metric"] == "rsi" and out["rows"] == [["2026-06-01", 40.0], ["2026-06-05", 55.5]]
    assert out["first"] == 40.0 and out["latest"] == 55.5 and out["min"] == 40.0 and out["max"] == 55.5
    assert sc.get_history("AAA", "pe")["metric"] == "price_to_earning"


def test_history_limit_keeps_the_latest_dates(sc):
    assert sc.get_history("AAA", "rsi", limit=1)["rows"] == [["2026-06-05", 55.5]]


def test_history_rejects_bad_input(sc):
    with pytest.raises(ScreenerError):
        sc.get_history("AAA", "magic")
    with pytest.raises(ScreenerError):
        sc.get_history("AAA", "industry_group")                                       # text, not a number
    with pytest.raises(ScreenerError):
        sc.get_history("ZZZ", "rsi")
    with pytest.raises(ScreenerError):
        sc.get_history("AAA", "rsi", limit=0)


def test_history_blanks_margin_measures_for_banks(sc):
    out = sc.get_history("BBB", "opm")
    assert "warning" in out and all(r[1] is None for r in out["rows"])
