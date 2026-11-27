"""Price layer: load the Nifty 50 price CSVs into DuckDB, and read them back.

    project-code/.venv/bin/python project-code/prices_db.py   # (re)build the DuckDB file named in config/paths.json (run with the app stopped)

The CSVs stay the source of truth. The DuckDB file is derived data and is rebuilt from them.
Writing needs exclusive access to the file. The app opens it read-only via open_readonly().

Price caveats (also shown to users): prices are NOT adjusted for splits, bonuses or demergers.

Source quirk found on 19 Nov 2026: on market holidays the downloaded daily file repeats the previous trading
day's rows (for example the 14 and 15 Apr 2022 files hold 13 Apr data). Exact duplicate (symbol, date) rows are
dropped here and counted. Two rows with the same symbol and date but different values are an error.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timezone

import duckdb
import pandas as pd

import config

TABLE = "prices"
COLUMNS = ["symbol", "series", "date", "prev_close", "open", "high", "low", "last", "close", "avg_price",
           "volume", "turnover_lacs", "trades", "delivery_qty", "delivery_pct"]
JUMP_THRESHOLD = 0.25            # a one-day move above 25% is flagged as a possible split, bonus or demerger


class PriceDataError(RuntimeError):
    pass


def read_price_csv(path) -> pd.DataFrame:
    """One bhavcopy-derived file. Headers and values have a leading space after each comma."""
    df = pd.read_csv(path, skipinitialspace=True, na_values=["-", " -", ""], keep_default_na=True)
    df.columns = [c.strip() for c in df.columns]
    for col in ("SYMBOL", "SERIES", "DATE1"):
        df[col] = df[col].astype(str).str.strip()
    out = pd.DataFrame({
        "symbol": df["SYMBOL"], "series": df["SERIES"],
        "date": pd.to_datetime(df["DATE1"], format="%d-%b-%Y").dt.date,
        "prev_close": pd.to_numeric(df["PREV_CLOSE"], errors="coerce"),
        "open": pd.to_numeric(df["OPEN_PRICE"], errors="coerce"),
        "high": pd.to_numeric(df["HIGH_PRICE"], errors="coerce"),
        "low": pd.to_numeric(df["LOW_PRICE"], errors="coerce"),
        "last": pd.to_numeric(df["LAST_PRICE"], errors="coerce"),
        "close": pd.to_numeric(df["CLOSE_PRICE"], errors="coerce"),
        "avg_price": pd.to_numeric(df["AVG_PRICE"], errors="coerce"),
        "volume": pd.to_numeric(df["TTL_TRD_QNTY"], errors="coerce"),
        "turnover_lacs": pd.to_numeric(df["TURNOVER_LACS"], errors="coerce"),
        "trades": pd.to_numeric(df["NO_OF_TRADES"], errors="coerce"),
        "delivery_qty": pd.to_numeric(df["DELIV_QTY"], errors="coerce"),
        "delivery_pct": pd.to_numeric(df["DELIV_PER"], errors="coerce"),
    })
    return out


def build(db_path=None, prices_dir=None) -> dict:
    """Rebuild the table from every CSV. Returns counts. Needs exclusive access to the DuckDB file."""
    db_path = db_path or config.duckdb_file()
    prices_dir = prices_dir or config.prices_dir()
    files = sorted(prices_dir.glob("*.csv"))
    if not files:
        raise PriceDataError(f"no price files in {prices_dir}")
    frames = []
    for f in files:
        part = read_price_csv(f)
        part = part[~part["symbol"].str.contains(" ")]             # skip the 'NIFTY 50' index row
        frames.append(part)
    data = pd.concat(frames, ignore_index=True)[COLUMNS]
    exact = int(data.duplicated().sum())
    data = data.drop_duplicates().reset_index(drop=True)
    conflicts = int(data.duplicated(["symbol", "date"]).sum())
    if conflicts:
        raise PriceDataError(f"{conflicts} rows share a (symbol, date) but have different values")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = db_path.with_suffix(".building")
    tmp.unlink(missing_ok=True)
    con = duckdb.connect(str(tmp))
    try:
        con.register("incoming", data)
        con.execute(f"CREATE TABLE {TABLE} AS SELECT * FROM incoming ORDER BY symbol, date")
        con.execute(f"CREATE TABLE meta AS SELECT ? AS built_at, count(*) AS rows, ? AS duplicates_removed, "
                    f"count(DISTINCT symbol) AS symbols, min(date) AS first_date, max(date) AS last_date FROM {TABLE}",
                    [datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"), exact])
    finally:
        con.close()
    tmp.replace(db_path)                                            # only a finished file replaces the old one
    return {"files": len(files), "rows": len(data), "duplicates_removed": exact, "symbols": int(data["symbol"].nunique())}


def open_readonly(db_path=None) -> duckdb.DuckDBPyConnection:
    db_path = db_path or config.duckdb_file()
    if not db_path.exists():
        raise PriceDataError(f"{db_path} not found. Build it with: python3 project-code/prices_db.py")
    return duckdb.connect(str(db_path), read_only=True)


def symbols(con) -> list[str]:
    return [r[0] for r in con.execute(f"SELECT DISTINCT symbol FROM {TABLE} ORDER BY symbol").fetchall()]


def history(con, symbol: str, start: date | None = None, end: date | None = None) -> pd.DataFrame:
    """Daily rows for one stock in date order. Raises if the symbol is unknown."""
    sql = f"SELECT * FROM {TABLE} WHERE symbol = ?"
    args: list = [symbol.upper()]
    if start:
        sql += " AND date >= ?"; args.append(start)
    if end:
        sql += " AND date <= ?"; args.append(end)
    df = con.execute(sql + " ORDER BY date", args).df()
    df["date"] = pd.to_datetime(df["date"]).dt.date              # plain dates, not timestamps
    if df.empty and not con.execute(f"SELECT 1 FROM {TABLE} WHERE symbol = ? LIMIT 1", [symbol.upper()]).fetchall():
        raise PriceDataError(f"no price data for {symbol}")
    return df


def data_dates(con) -> dict:
    row = con.execute("SELECT first_date, last_date, rows, symbols, built_at, duplicates_removed FROM meta").fetchone()
    return {"first_date": row[0], "last_date": row[1], "rows": row[2], "symbols": row[3], "built_at": row[4],
            "duplicates_removed": row[5]}


def detect_jumps(df: pd.DataFrame, threshold: float = JUMP_THRESHOLD) -> pd.DataFrame:
    """Days where close vs previous close moved more than the threshold. These may be splits, bonuses or
    demergers because prices are not adjusted. Flag them, do not silently fix them."""
    change = df["close"] / df["prev_close"] - 1
    flagged = df.loc[change.abs() > threshold, ["date", "prev_close", "close"]].copy()
    flagged["change_pct"] = (change[change.abs() > threshold] * 100).round(2)
    return flagged.reset_index(drop=True)


if __name__ == "__main__":
    try:
        print(build())
    except (PriceDataError, duckdb.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
