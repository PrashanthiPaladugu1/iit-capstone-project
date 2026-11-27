"""Load the Screener "all stocks" CSV snapshots into DuckDB (Nifty 50 rows only), and read them back.

Source: the folder at path key `screener_csv_dir`, files `EquityData-All-Stocks_*_<YYYYMMDD>_<HHMMSS>.csv`. Each file is the whole
Screener table (about 5,500 companies, 62 columns) as of one day. The files are only read, never changed.
Output: the file at path key `screener_duckdb`, table `snapshots` (one row per stock per day). When two files fall on the
same day, the later one is kept (a second run on 10 Nov re-calculated the market-cap based columns). Only the stocks in
`Reference-Files/nifty-50.csv` are kept (guardrail G1). A rebuild keeps the previous file under a dated name (no-delete rule).

Units: market cap, sales and profit look like crore rupees. Screener states no unit in the file.
"""
from __future__ import annotations

import datetime as dt
import re
import sys
from pathlib import Path

import duckdb

import config

FILE_RE = re.compile(r"_(\d{8})_(\d{6})\.csv$")
# CSV header -> column name in the table. Everything else in the file is not loaded.
COLUMNS = {
    "Name": "company_name", "BSE Code": "bse_code", "ISIN Code": "isin_code",
    "Industry Group": "industry_group", "Industry": "industry",
    "Current Price": "current_price", "High price all time": "high_price_all_time", "Low price all time": "low_price_all_time",
    "High price": "high_price_52w", "Low price": "low_price_52w", "Down from 52w high": "down_from_52w_high",
    "Book value": "book_value", "Price to book value": "price_to_book_value", "Market Capitalization": "market_capitalization",
    "Enterprise Value": "enterprise_value", "Market Cap to Sales": "market_cap_to_sales", "RSI": "rsi", "MACD": "macd",
    "Price to Earning": "price_to_earning", "Industry PE": "industry_pe", "Sales": "sales", "Price to Sales": "price_to_sales",
    "PEG Ratio": "peg_ratio", "Sales growth": "sales_growth", "Profit growth": "profit_growth",
    "Promoter holding": "promoter_holding", "Change in promoter holding": "change_in_promoter_holding", "EPS": "eps",
    "Return on capital employed": "return_on_capital_employed", "Profit after tax latest quarter": "profit_after_tax_latest_quarter",
    "Sales latest quarter": "sales_latest_quarter", "YOY Quarterly sales growth": "yoy_quarterly_sales_growth",
    "YOY Quarterly profit growth": "yoy_quarterly_profit_growth", "Profit after tax": "profit_after_tax",
    "NPM last year": "npm_last_year", "OPM last year": "opm_last_year", "EPS last year": "eps_last_year",
    "OPM latest quarter": "opm_latest_quarter", "NPM latest quarter": "npm_latest_quarter", "GPM latest quarter": "gpm_latest_quarter",
    "Net Profit latest quarter": "net_profit_latest_quarter", "NPM preceding quarter": "npm_preceding_quarter",
    "OPM preceding quarter": "opm_preceding_quarter", "Net Profit preceding quarter": "net_profit_preceding_quarter",
    "EPS preceding quarter": "eps_preceding_quarter", "Cash from operations last year": "cash_from_operations_last_year",
    "Debt to equity": "debt_to_equity", "Dividend yield": "dividend_yield", "Number of equity shares": "number_of_equity_shares",
    "Price to Quarterly Earning": "price_to_quarterly_earning", "Public holding": "public_holding", "DII holding": "dii_holding",
    "Change in DII holding": "change_in_dii_holding", "FII holding": "fii_holding", "Change in FII holding": "change_in_fii_holding",
    "DMA 50": "dma_50", "DMA 200": "dma_200", "Volume": "volume", "Volume 1week average": "volume_1week_average",
    "Volume 1month average": "volume_1month_average", "QoQ Sales": "qoq_sales",
}
TEXT_COLUMNS = {"company_name", "isin_code", "industry_group", "industry"}


def _csv_dir() -> Path:
    return config.get("screener_csv_dir")


def snapshot_files(csv_dir: Path | str | None = None) -> list[tuple[str, str, Path]]:
    """(date, time, path) for every snapshot file in the folder, oldest first. Files elsewhere in the tree are not looked at."""
    folder = Path(csv_dir) if csv_dir else _csv_dir()
    found = []
    for f in folder.glob("EquityData-All-Stocks_*.csv"):
        m = FILE_RE.search(f.name)
        if m:
            found.append((m.group(1), m.group(2), f))
    return sorted(found)


def build(db_path: Path | str | None = None, csv_dir: Path | str | None = None, symbols: list[str] | None = None) -> dict:
    """Load the snapshots into a new DuckDB file. If a database already exists it is renamed to a dated name first."""
    import pandas as pd
    if symbols is None:
        from market_data import nifty50_symbols
        symbols = nifty50_symbols()
    files = snapshot_files(csv_dir)
    if not files:
        raise FileNotFoundError(f"no EquityData-All-Stocks_*.csv snapshot files in {csv_dir or _csv_dir()}")
    db_path = Path(db_path) if db_path else config.get("screener_duckdb")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    building = db_path.with_name(db_path.name + ".building")
    if building.exists():
        building.rename(building.with_name(f"{building.name}.{dt.datetime.now():%Y%m%d-%H%M%S}.unfinished"))

    wanted = set(symbols)
    frames = []
    for day, clock, path in files:
        raw = pd.read_csv(path, usecols=lambda c: c in COLUMNS or c == "NSE Code")
        raw = raw[raw["NSE Code"].isin(wanted)].copy()
        raw["snap_date"] = pd.to_datetime(day, format="%Y%m%d").date()
        raw["snap_time"] = clock
        raw["source_file"] = path.name
        frames.append(raw)
    data = pd.concat(frames, ignore_index=True)
    data = data.rename(columns={"NSE Code": "symbol", **COLUMNS})
    data = data.sort_values(["symbol", "snap_date", "snap_time"]).drop_duplicates(["symbol", "snap_date"], keep="last")
    for col in COLUMNS.values():
        if col not in data.columns:
            data[col] = None
        if col not in TEXT_COLUMNS:
            data[col] = pd.to_numeric(data[col], errors="coerce")
    order = ["symbol", "snap_date", "snap_time", "source_file"] + list(COLUMNS.values())
    data = data[order]

    con = duckdb.connect(str(building))
    try:
        con.register("d", data)
        con.execute("CREATE TABLE snapshots AS SELECT * FROM d ORDER BY symbol, snap_date")
        con.execute("CREATE TABLE build_info AS SELECT now() AS built_at, ? AS files, ? AS days, ? AS stocks, ? AS rows",
                    [len(files), int(data["snap_date"].nunique()), int(data["symbol"].nunique()), len(data)])
    finally:
        con.close()

    kept = None
    if db_path.exists():
        kept = _dated_name(db_path)
        db_path.rename(kept)                                   # keep the previous database (no-delete rule)
    building.rename(db_path)
    return {"files": len(files), "days": int(data["snap_date"].nunique()), "stocks": int(data["symbol"].nunique()),
            "rows": len(data), "missing": sorted(wanted - set(data["symbol"])), "kept_old": str(kept) if kept else ""}


def _dated_name(path: Path) -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate = path.with_name(f"{path.stem}.{stamp}{path.suffix}")
    n = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.stem}.{stamp}-{n}{path.suffix}")
        n += 1
    return candidate


def open_readonly(db_path: Path | str | None = None) -> duckdb.DuckDBPyConnection:
    db_path = Path(db_path) if db_path else config.get("screener_duckdb")
    if not db_path.exists():
        raise FileNotFoundError(f"screener database not found: {db_path}. Build it with bin/run_py.sh screener_db.py")
    return duckdb.connect(str(db_path), read_only=True)


if __name__ == "__main__":
    result = build()
    print(f"loaded {result['files']} files, {result['days']} days, {result['stocks']} stocks, {result['rows']:,} rows")
    if result["missing"]:
        print(f"no rows for: {result['missing']}")
    if result["kept_old"]:
        print(f"previous database kept as: {result['kept_old']}")
    sys.exit(0)
