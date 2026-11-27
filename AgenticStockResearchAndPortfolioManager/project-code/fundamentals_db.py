"""Load the Screener Excel workbooks (one per stock) into DuckDB, and read them back.

Source: `data/<SYMBOL>/Financials_<SYMBOL>.xlsx`, sheet `Data Sheet`. All 49 workbooks share one layout (checked 2026-11-20):
a heading row (META, PROFIT & LOSS, Quarters, BALANCE SHEET, CASH FLOW:, PRICE:, DERIVED:), a `Report Date` row, then one
row per line item with one value per date. The workbook files are only read, never changed.

Output: the file at path key `fundamentals_duckdb`, separate from the price database so neither rebuild touches the other.
A rebuild keeps the previous file under a dated name (no-delete rule).

Units: the sheets state no unit. Values look like crore rupees. Callers must not claim a unit without confirming it.
"""
from __future__ import annotations

import datetime as dt
import re
import sys
import warnings
from pathlib import Path

import duckdb

import config

SHEET = "Data Sheet"
SECTION_HEADINGS = {
    "META": "meta", "PROFIT & LOSS": "profit_loss", "QUARTERS": "quarters", "BALANCE SHEET": "balance_sheet",
    "CASH FLOW:": "cash_flow", "PRICE:": "price", "DERIVED:": "derived",
}
DATED_SECTIONS = ("profit_loss", "quarters", "balance_sheet", "cash_flow")
META_KEYS = {"COMPANY NAME": "company_name", "Face Value": "face_value", "Current Price": "current_price",
             "Market Capitalization": "market_cap"}


def _docs_dir() -> Path:
    return config.documents_dir()


def find_workbook(symbol: str) -> Path | None:
    """The workbook for a stock, or None. `M&M` is stored as `Financials_M_M.xlsx`."""
    folder = _docs_dir() / symbol
    if not folder.is_dir():
        return None
    for name in (f"Financials_{symbol}.xlsx", f"Financials_{re.sub(r'[^A-Za-z0-9]', '_', symbol)}.xlsx"):
        if (folder / name).is_file():
            return folder / name
    found = sorted(folder.glob("Financials_*.xlsx"))
    return found[0] if found else None


def _num(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _day(value):
    return value.date() if isinstance(value, dt.datetime) else value if isinstance(value, dt.date) else None


def parse_workbook(path: Path) -> dict:
    """{"meta": {...}, "rows": [{"section", "label", "period_end", "value"}, ...]} from one workbook."""
    import openpyxl
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
        rows = [list(r) for r in wb[SHEET].iter_rows(values_only=True)]
        wb.close()

    meta: dict = {}
    out: list[dict] = []
    section = None
    dates: list = []
    annual_dates: list = []
    totals_seen = 0
    for row in rows:
        label = row[0] if row else None
        if not isinstance(label, str):
            continue
        label = label.strip()
        key = label.upper() if label.upper() in SECTION_HEADINGS else label
        if key in SECTION_HEADINGS or label.startswith("PRICE:"):
            section = SECTION_HEADINGS.get(key, "price")
            dates, totals_seen = [], 0
            if section == "price":
                for i, v in enumerate(row[1:]):
                    day = annual_dates[i] if i < len(annual_dates) else None
                    if _num(v) is not None and day:
                        out.append({"section": "price", "label": "Year-end price", "period_end": day, "value": _num(v)})
            continue
        if label in META_KEYS and section in (None, "meta"):
            value = row[1] if len(row) > 1 else None
            meta[META_KEYS[label]] = value.strip() if isinstance(value, str) else _num(value)
            continue
        if section is None or section == "meta" or section == "price":
            continue
        if label == "Report Date":
            dates = [_day(v) for v in row[1:]]
            if section == "profit_loss":
                annual_dates = dates
            continue
        if section == "balance_sheet" and label == "Total":
            totals_seen += 1
            label = "Total liabilities" if totals_seen == 1 else "Total assets"
        series = dates if section in DATED_SECTIONS else annual_dates          # derived rows follow the annual columns
        for i, v in enumerate(row[1:]):
            num = _num(v)
            day = series[i] if i < len(series) else None
            if num is not None and day is not None:
                out.append({"section": section, "label": label, "period_end": day, "value": num})
    return {"meta": meta, "rows": out}


def build(db_path: Path | str | None = None, symbols: list[str] | None = None) -> dict:
    """Load the workbooks into a new DuckDB file. If a database already exists it is renamed to a dated name first."""
    import pandas as pd
    if symbols is None:
        from market_data import nifty50_symbols
        symbols = nifty50_symbols()
    db_path = Path(db_path) if db_path else config.get("fundamentals_duckdb")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    building = db_path.with_name(db_path.name + ".building")
    if building.exists():
        building.rename(building.with_name(f"{building.name}.{dt.datetime.now():%Y%m%d-%H%M%S}.unfinished"))

    loaded, missing, failed, values, metas = [], [], [], [], []
    for sym in symbols:
        wb = find_workbook(sym)
        if wb is None:
            missing.append(sym)
            continue
        try:
            parsed = parse_workbook(wb)
        except Exception as exc:
            failed.append(f"{sym}: {type(exc).__name__}: {exc}")
            continue
        loaded.append(sym)
        values += [{"symbol": sym, **r} for r in parsed["rows"]]
        metas.append({"symbol": sym, "source_file": wb.name, **parsed["meta"]})

    con = duckdb.connect(str(building))
    try:
        vdf = pd.DataFrame(values, columns=["symbol", "section", "label", "period_end", "value"])
        vdf["period_end"] = pd.to_datetime(vdf["period_end"]).dt.date
        mdf = pd.DataFrame(metas, columns=["symbol", "source_file", "company_name", "face_value", "current_price", "market_cap"])
        con.register("v", vdf)
        con.register("m", mdf)
        con.execute("CREATE TABLE fin_values AS SELECT * FROM v ORDER BY symbol, section, label, period_end")
        con.execute("CREATE TABLE fin_meta AS SELECT * FROM m ORDER BY symbol")
        con.execute("CREATE TABLE build_info AS SELECT now() AS built_at, ? AS stocks, ? AS value_rows",
                    [len(loaded), len(vdf)])
    finally:
        con.close()

    kept = None
    if db_path.exists():
        kept = _dated_name(db_path)
        db_path.rename(kept)                                   # keep the previous database (no-delete rule)
    building.rename(db_path)
    return {"loaded": loaded, "missing": missing, "failed": failed, "rows": len(values), "kept_old": str(kept) if kept else ""}


def _dated_name(path: Path) -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate = path.with_name(f"{path.stem}.{stamp}{path.suffix}")
    n = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.stem}.{stamp}-{n}{path.suffix}")
        n += 1
    return candidate


def open_readonly(db_path: Path | str | None = None) -> duckdb.DuckDBPyConnection:
    db_path = Path(db_path) if db_path else config.get("fundamentals_duckdb")
    if not db_path.exists():
        raise FileNotFoundError(f"fundamentals database not found: {db_path}. Build it with bin/run_py.sh fundamentals_db.py")
    return duckdb.connect(str(db_path), read_only=True)


if __name__ == "__main__":
    result = build()
    print(f"loaded {len(result['loaded'])} stocks, {result['rows']:,} values")
    print(f"missing workbook: {result['missing']}")
    if result["failed"]:
        print(f"FAILED: {result['failed']}")
    if result["kept_old"]:
        print(f"previous database kept as: {result['kept_old']}")
    sys.exit(1 if result["failed"] else 0)
