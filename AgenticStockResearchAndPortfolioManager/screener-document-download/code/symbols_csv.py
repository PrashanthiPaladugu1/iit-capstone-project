"""Read symbols from a Screener.in screen export (CSV)."""
from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import List, Optional

from config import CSV_GLOB

NSE_COL = "NSE Code"
BSE_COL = "BSE Code"


def find_latest_csv(directory: Path) -> Optional[Path]:
    """Newest `equitydata-screener-all-stocks-*.csv` in `directory` (date is in the name), or None."""
    matches = sorted(directory.glob(CSV_GLOB))
    return matches[-1] if matches else None


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def find_index_csv(directory: Path, name: str) -> Path:
    """CSV in `directory` whose file name matches `name`, ignoring case, '-', '_' and spaces
    (so `Nifty50`, `nifty-50` and `NIFTY_50` all select `nifty-50.csv`)."""
    files = sorted(directory.glob("*.csv")) if directory.is_dir() else []
    for f in files:
        if _norm(f.stem) == _norm(name):
            return f
    available = ", ".join(f.stem for f in files) or "none"
    raise FileNotFoundError(f"--index {name}: no matching CSV in {directory} (available: {available})")


def read_symbols_from_csv(path: Path, start: int = 0, limit: Optional[int] = None) -> List[str]:
    """Return one Screener slug per row: NSE code if present, else BSE code.

    Screener accepts either in /company/{slug}/. Rows with neither code are skipped,
    duplicates dropped (order kept). `start`/`limit` slice the result for batched runs.
    """
    if not path.is_file():
        raise FileNotFoundError(f"CSV not found: {path}")
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in (NSE_COL, BSE_COL) if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"CSV is missing column(s): {', '.join(missing)}")
        symbols: List[str] = []
        seen = set()
        for row in reader:
            slug = (row.get(NSE_COL) or "").strip() or (row.get(BSE_COL) or "").strip()
            if slug and slug.upper() not in seen:
                seen.add(slug.upper())
                symbols.append(slug)
    end = None if limit is None else start + limit
    return symbols[start:end]
