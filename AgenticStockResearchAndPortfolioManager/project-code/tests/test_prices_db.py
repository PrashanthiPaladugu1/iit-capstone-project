"""Price loader. Uses small fake CSVs in a temp folder, plus checks against the real 50 files."""
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
import prices_db as pdb  # noqa: E402

HEADER = ("SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, LAST_PRICE, CLOSE_PRICE, AVG_PRICE, "
          "TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER\n")


def write(folder, symbol, rows):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{symbol}.csv").write_text(HEADER + "".join(f"{symbol}, EQ, {r}\n" for r in rows))


ROWS_A = ["02-Jan-2025, 100.00, 101.00, 105.00, 99.00, 104.00, 104.00, 102.50, 1000, 10.25, 50, 600, 60.00",
          "03-Jan-2025, 104.00, 104.50, 106.00, 103.00, 105.00, 105.00, 104.80, 1200, 12.58, 55, 700, 58.33"]


def test_read_price_csv_trims_spaces_and_parses_dates_and_numbers(tmp_path):
    write(tmp_path, "AAA", ROWS_A)
    df = pdb.read_price_csv(tmp_path / "AAA.csv")
    assert list(df["symbol"].unique()) == ["AAA"]
    assert df["date"].tolist() == [date(2025, 1, 2), date(2025, 1, 3)]
    assert df["close"].tolist() == [104.0, 105.0] and df["delivery_pct"].iloc[0] == 60.0


def test_dash_values_become_null(tmp_path):
    write(tmp_path, "AAA", ["02-Jan-2025, 100.00, 101.00, 105.00, 99.00, 104.00, 104.00, 102.50, 1000, 10.25, 50, -, -"])
    df = pdb.read_price_csv(tmp_path / "AAA.csv")
    assert df["delivery_qty"].isna().iloc[0] and df["delivery_pct"].isna().iloc[0]


def test_build_and_query_and_index_row_skipped(tmp_path):
    prices = tmp_path / "p"
    write(prices, "AAA", ROWS_A)
    write(prices, "BBB", ROWS_A)
    (prices / "BBB.csv").write_text((prices / "BBB.csv").read_text() + "NIFTY 50, EQ, 03-Jan-2025, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1\n")
    db = tmp_path / "x.duckdb"
    counts = pdb.build(db, prices)
    assert counts == {"files": 2, "rows": 4, "duplicates_removed": 0, "symbols": 2}
    con = pdb.open_readonly(db)
    assert pdb.symbols(con) == ["AAA", "BBB"]
    hist = pdb.history(con, "aaa", start=date(2025, 1, 3))
    assert hist["close"].tolist() == [105.0]
    assert pdb.data_dates(con)["last_date"] == date(2025, 1, 3)
    with pytest.raises(pdb.PriceDataError):
        pdb.history(con, "ZZZ")


def test_open_readonly_missing_file_has_clear_message(tmp_path):
    with pytest.raises(pdb.PriceDataError, match="Build it with"):
        pdb.open_readonly(tmp_path / "none.duckdb")


def test_build_with_no_files_fails_and_failed_build_keeps_old_file(tmp_path):
    prices = tmp_path / "p"
    write(prices, "AAA", ROWS_A)
    db = tmp_path / "x.duckdb"
    pdb.build(db, prices)
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(pdb.PriceDataError):
        pdb.build(db, empty)
    assert pdb.symbols(pdb.open_readonly(db)) == ["AAA"]


def test_exact_duplicate_rows_are_dropped_and_counted(tmp_path):
    prices = tmp_path / "p"
    write(prices, "AAA", ROWS_A + ROWS_A[:1])                 # a holiday file repeating the previous day
    counts = pdb.build(tmp_path / "x.duckdb", prices)
    assert counts["rows"] == 2 and counts["duplicates_removed"] == 1
    assert pdb.data_dates(pdb.open_readonly(tmp_path / "x.duckdb"))["duplicates_removed"] == 1


def test_conflicting_rows_for_the_same_day_are_an_error(tmp_path):
    prices = tmp_path / "p"
    changed = ROWS_A[0].replace("104.00, 104.00, 102.50", "104.00, 999.00, 102.50")
    write(prices, "AAA", ROWS_A + [changed])
    with pytest.raises(pdb.PriceDataError, match="different values"):
        pdb.build(tmp_path / "x.duckdb", prices)


def test_jump_detector_flags_split_like_moves(tmp_path):
    write(tmp_path, "AAA", ["02-Jan-2025, 1000.00, 1000, 1000, 490, 500, 500.00, 500, 1, 1, 1, 1, 1",
                            "03-Jan-2025, 500.00, 500, 510, 495, 505, 505.00, 500, 1, 1, 1, 1, 1"])
    flagged = pdb.detect_jumps(pdb.read_price_csv(tmp_path / "AAA.csv"))
    assert flagged["date"].tolist() == [date(2025, 1, 2)] and flagged["change_pct"].iloc[0] == -50.0


# ---------------------------------------------------------------- the real data
@pytest.fixture(scope="module")
def real_db(tmp_path_factory):
    db = tmp_path_factory.mktemp("db") / "real.duckdb"
    counts = pdb.build(db, config.prices_dir())
    return pdb.open_readonly(db), counts


def test_real_files_load_completely(real_db):
    con, counts = real_db
    assert counts["files"] == 50 and counts["symbols"] == 50
    # 57,767 file rows minus 2,600 exact duplicates from holiday files. Update if prices are refreshed.
    assert counts["rows"] == 55167 and counts["duplicates_removed"] == 2600
    info = pdb.data_dates(con)
    assert info["first_date"] == date(2022, 3, 23) and info["last_date"] == date(2026, 11, 13)


def test_real_tcs_last_row_matches_file(real_db):
    con, _ = real_db
    last = pdb.history(con, "TCS").iloc[-1]
    assert (str(last["date"]), last["close"], last["volume"]) == ("2026-11-13", 2407.5, 3344738)


def test_real_short_histories(real_db):
    con, _ = real_db
    assert len(pdb.history(con, "TMPV")) == 260


def test_real_data_has_no_duplicate_symbol_dates(real_db):
    con, _ = real_db
    assert con.execute("SELECT count(*) FROM (SELECT 1 FROM prices GROUP BY symbol, date HAVING count(*) > 1)").fetchone()[0] == 0


def test_history_dates_are_plain_dates_and_latest_indicators_work_on_real_data(real_db):
    import indicators
    con, _ = real_db
    df = pdb.history(con, "TCS")
    assert isinstance(df["date"].iloc[-1], date)
    latest = indicators.latest_indicators(df)
    assert latest["date"] == "2026-11-13" and latest["close"] == 2407.5
    assert 0 < latest["rsi_14"] < 100 and latest["sma_200"] is not None and latest["atr_14"] > 0
    short = indicators.latest_indicators(pdb.history(con, "TMPV").head(30))
    assert short["sma_200"] is None                                  # not enough history: None, never a made-up number
