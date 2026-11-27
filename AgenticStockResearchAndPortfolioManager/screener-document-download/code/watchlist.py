"""Watchlist file reader."""
from __future__ import annotations

from pathlib import Path
from typing import List


def read_watchlist(path: Path) -> List[str]:
    """One symbol per line; blank lines and '#' comments are ignored; duplicates dropped."""
    if not path.is_file():
        raise FileNotFoundError(f"Watchlist not found: {path}")
    symbols: List[str] = []
    seen = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line and line.upper() not in seen:
            seen.add(line.upper())
            symbols.append(line)
    return symbols
