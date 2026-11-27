"""Build one CSV per index stock in data_stock_bhavcopy_nifty50/ from the daily bhavcopy files.

    python3 code/bhavcopy_index_filter.py                  # NIFTY_50 constituents, EQ series
    python3 code/bhavcopy_index_filter.py --series EQ BE   # more series
    python3 code/bhavcopy_index_filter.py --series ALL     # every series
    python3 code/bhavcopy_index_filter.py --index NIFTY_NEXT_50 --out data_stock_bhavcopy_niftynext50

The stock list is read from the newest data_nse_index/<YYYYMMDD>/<INDEX>.csv (the index's own row,
e.g. "NIFTY 50", is ignored). Every data_stock_bhavcopy/sec_bhavdata_full_DDMMYYYY.csv is read in date
order and the rows of those symbols are collected into <out>/<SYMBOL>.csv (bhavcopy header, one row per
trading day, oldest first). Only files whose content changed are rewritten, and .csv files in the output
folder for symbols that are no longer in the index are removed, so it is safe to re-run after every
bhavcopy / index download.
"""
from __future__ import annotations

import argparse
import csv
import logging
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from config import DEFAULT_LOG_DIR, LOGGER_NAME, PROJECT_ROOT
from log_setup import setup_logging

log = logging.getLogger(LOGGER_NAME)

DEFAULT_SRC = PROJECT_ROOT / "data_stock_bhavcopy"
DEFAULT_INDEX_DIR = PROJECT_ROOT / "data_nse_index"
DEFAULT_OUT = PROJECT_ROOT / "data_stock_bhavcopy_nifty50"
DEFAULT_INDEX = "NIFTY_50"
DEFAULT_SERIES = ["EQ"]
PREFIX = "sec_bhavdata_full_"
PATTERN = PREFIX + "*.csv"


def find_index_file(index_dir: Path, name: str) -> Path:
    """Newest `<index_dir>/<YYYYMMDD>/<name>.csv`."""
    matches = sorted(p for p in index_dir.glob(f"*/{name}.csv") if p.parent.name.isdigit())
    if not matches:
        raise FileNotFoundError(f"No {name}.csv found under {index_dir}/<YYYYMMDD>/")
    return matches[-1]


def read_index_symbols(path: Path) -> List[str]:
    """Stock symbols of an index CSV (first column 'symbol'). Rows with a space in the symbol, such as
    the index's own row 'NIFTY 50', are not stocks and are skipped. Duplicates dropped, order kept."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        if not header or header[0].strip().lower() != "symbol":
            raise ValueError(f"{path}: first column must be 'symbol'")
        out: List[str] = []
        seen: Set[str] = set()
        for row in reader:
            sym = row[0].strip() if row else ""
            if sym and " " not in sym and sym.upper() not in seen:
                seen.add(sym.upper())
                out.append(sym)
    return out


def file_date(path: Path) -> Optional[date]:
    """Trading date from `sec_bhavdata_full_DDMMYYYY.csv`, or None if the name does not match."""
    try:
        return datetime.strptime(path.stem[len(PREFIX):], "%d%m%Y").date()
    except ValueError:
        return None


def daily_files(src: Path) -> List[Path]:
    """Daily bhavcopy files, oldest first (files whose name has no valid date are ignored)."""
    dated = [(file_date(p), p) for p in src.glob(PATTERN)]
    return [p for d, p in sorted((d, p) for d, p in dated if d is not None)]


def collect(files: List[Path], symbols: List[str],
            series: Optional[Set[str]]) -> Tuple[str, Dict[str, List[str]]]:
    """(header, {SYMBOL: rows}) from the daily files, in the order given.
    Bhavcopy fields are separated by ', ', so SYMBOL and SERIES are stripped before comparing."""
    canon = {s.upper(): s for s in symbols}
    rows: Dict[str, List[str]] = {s: [] for s in symbols}
    header = ""
    for f in files:
        lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        if not lines:
            continue
        header = header or lines[0]
        for line in lines[1:]:
            parts = line.split(",", 2)
            if len(parts) < 2:
                continue
            sym = canon.get(parts[0].strip().upper())
            if sym is None:
                continue
            if series is not None and parts[1].strip().upper() not in series:
                continue
            rows[sym].append(line)
    return header, rows


def run(src: Path, out: Path, symbols: List[str],
        series: Optional[Set[str]]) -> Tuple[Dict[str, int], List[str]]:
    """Rebuild <out>/<SYMBOL>.csv for every symbol. Returns (counts, symbols with no rows)."""
    if not src.is_dir():
        raise FileNotFoundError(f"Bhavcopy folder not found: {src}")
    files = daily_files(src)
    if not files:
        raise FileNotFoundError(f"No {PATTERN} files in {src}")
    header, rows = collect(files, symbols, series)
    out.mkdir(parents=True, exist_ok=True)

    stats = {"new": 0, "updated": 0, "unchanged": 0, "removed": 0, "rows": 0, "days": len(files)}
    missing: List[str] = []
    for sym in symbols:
        if not rows[sym]:
            missing.append(sym)
            continue
        text = header + "\n" + "\n".join(rows[sym]) + "\n"
        dest = out / f"{sym}.csv"
        stats["rows"] += len(rows[sym])
        if not dest.exists():
            dest.write_text(text, encoding="utf-8")
            stats["new"] += 1
        elif dest.read_text(encoding="utf-8") != text:
            dest.write_text(text, encoding="utf-8")
            stats["updated"] += 1
        else:
            stats["unchanged"] += 1

    keep = {f"{s}.csv" for s in symbols if rows[s]}
    for stale in out.glob("*.csv"):
        if stale.name not in keep:
            stale.unlink()
            stats["removed"] += 1
    return stats, missing


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build one CSV per index stock from the daily bhavcopy files.")
    p.add_argument("--index", default=DEFAULT_INDEX,
                   help="Index file name (without .csv) in data_nse_index/<date>/ (default: NIFTY_50)")
    p.add_argument("--index-dir", type=Path, default=DEFAULT_INDEX_DIR)
    p.add_argument("--src", type=Path, default=DEFAULT_SRC, help="Folder with the full daily bhavcopy files")
    p.add_argument("-o", "--out", type=Path, default=DEFAULT_OUT, help="Folder for the <SYMBOL>.csv files")
    p.add_argument("--series", nargs="+", default=DEFAULT_SERIES, metavar="SERIES",
                   help="Bhavcopy SERIES values to keep, or ALL (default: EQ)")
    p.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR)
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    setup_logging(args.verbose, args.log_dir / f"bhavcopy_filter_{datetime.now():%Y%m%d_%H%M%S}.log")
    series = None if any(s.upper() == "ALL" for s in args.series) else {s.upper() for s in args.series}
    try:
        index_file = find_index_file(args.index_dir, args.index)
        symbols = read_index_symbols(index_file)
        if not symbols:
            raise ValueError(f"{index_file}: no stock symbols found")
        log.info("%d symbol(s) from %s", len(symbols), index_file)
        log.info("Series: %s", "ALL" if series is None else ", ".join(sorted(series)))
        stats, missing = run(args.src, args.out, symbols, series)
    except (FileNotFoundError, ValueError) as exc:
        log.error("%s", exc)
        return 2
    log.info("Done. %d daily file(s) -> new=%d updated=%d unchanged=%d removed=%d rows=%d -> %s",
             stats["days"], stats["new"], stats["updated"], stats["unchanged"], stats["removed"],
             stats["rows"], args.out)
    if missing:
        log.warning("No bhavcopy rows for %d symbol(s): %s", len(missing), ", ".join(missing))
    return 0


if __name__ == "__main__":
    sys.exit(main())
