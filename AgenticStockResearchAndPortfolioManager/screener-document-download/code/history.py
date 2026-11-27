"""Persistent download history (downloaded_history.json)."""
from __future__ import annotations

import json
import logging
import tempfile
import threading
from pathlib import Path
from typing import Dict

from config import LOGGER_NAME

log = logging.getLogger(LOGGER_NAME)

History = Dict[str, Dict[str, dict]]  # {SYMBOL: {url: {file, type, label, downloaded_at}}}

# Workers run different stocks in parallel but share one history dict and one history file.
# Every mutation and every save goes through this lock so json.dump never sees a dict change.
_LOCK = threading.RLock()


def load_history(path: Path) -> History:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError as exc:
        # Do not silently discard history: keep a copy and start fresh.
        backup = path.with_suffix(".json.corrupt")
        path.replace(backup)
        log.error("History file was corrupt (%s); moved to %s and starting fresh", exc, backup)
    return {}


def symbol_history(history: History, symbol: str) -> Dict[str, dict]:
    """The record dict for one symbol, created if missing (thread-safe)."""
    with _LOCK:
        return history.setdefault(symbol, {})


def save_history(path: Path, history: History) -> None:
    """Atomic write so a crash mid-run can't truncate the history."""
    with _LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                         delete=False, suffix=".tmp") as tmp:
            json.dump(history, tmp, indent=2, sort_keys=True)
            tmp_name = tmp.name
        Path(tmp_name).replace(path)


def record_entry(history: History, path: Path, symbol: str, key: str, record: dict) -> None:
    """Add one record to the in-memory history and persist it, as one atomic step."""
    with _LOCK:
        history.setdefault(symbol, {})[key] = record
        save_history(path, history)
