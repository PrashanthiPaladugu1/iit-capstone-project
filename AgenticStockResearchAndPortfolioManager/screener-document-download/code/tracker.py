"""download_tracker.txt: one finished symbol per line, so completed stocks are skipped on later runs.

A symbol is only added after a real (non dry-run) run finished it with zero failures.
Lines starting with '#' and blank lines are ignored, so the file can be edited by hand.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Set

_LOCK = threading.Lock()  # workers mark symbols from different threads


def _read(path: Path) -> Set[str]:
    if not path.is_file():
        return set()
    done = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            done.add(line.upper())
    return done


def load_tracker(path: Path) -> Set[str]:
    with _LOCK:
        return _read(path)


def mark_done(path: Path, symbol: str) -> None:
    key = symbol.strip().upper()
    with _LOCK:
        if key in _read(path):
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(key + "\n")
