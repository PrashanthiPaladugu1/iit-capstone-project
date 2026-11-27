"""Run progress tracking: counts, percentage, running totals, ETA, JSON summary."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set

KEYS = ("new", "skipped", "failed")


def fmt_duration(seconds: Optional[float]) -> str:
    if seconds is None:
        return "--:--:--"
    s = max(0, int(seconds))
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


class Progress:
    def __init__(self, total: int, clock: Callable[[], float] = time.monotonic):
        self.total = total
        self.done = 0
        self.started = 0
        self.totals: Dict[str, int] = {k: 0 for k in KEYS}
        self.failed_symbols: List[str] = []
        self._finished: Set[int] = set()   # positions (0-based) of finished symbols
        self._lock = threading.RLock()     # several workers report into one Progress
        self._clock = clock
        self._start = clock()

    # -- helpers
    def elapsed(self) -> float:
        return self._clock() - self._start

    def percent(self) -> float:
        return 100.0 * self.done / self.total if self.total else 0.0

    def eta(self) -> Optional[float]:
        if self.done == 0 or self.total == 0:
            return None
        return self.elapsed() / self.done * (self.total - self.done)

    # -- events (each returns the line to log)
    def begin(self, symbol: str) -> str:
        with self._lock:
            self.started += 1
            return (f"[{self.started}/{self.total}] {self.percent():.1f}% | {symbol} | "
                    f"elapsed {fmt_duration(self.elapsed())} ETA {fmt_duration(self.eta())}")

    def finish(self, symbol: str, stats: Dict[str, int], index: Optional[int] = None) -> str:
        """index = the symbol's 0-based position in the run (needed for a correct resume point
        when parallel workers finish out of order; sequential callers may omit it)."""
        with self._lock:
            self._finished.add(self.done if index is None else index)
            self.done += 1
            for k in KEYS:
                self.totals[k] += stats.get(k, 0)
            if stats.get("failed", 0):
                self.failed_symbols.append(symbol)
            t = self.totals
            return (f"{symbol} done: new={stats.get('new', 0)} skipped={stats.get('skipped', 0)} "
                    f"failed={stats.get('failed', 0)} | {self.done}/{self.total} ({self.percent():.1f}%) | "
                    f"total new={t['new']} skipped={t['skipped']} failed={t['failed']} | "
                    f"elapsed {fmt_duration(self.elapsed())} ETA {fmt_duration(self.eta())}")

    def record_error(self, symbol: str, index: Optional[int] = None) -> str:
        """A symbol that crashed unexpectedly: counts as done with one failure."""
        return self.finish(symbol, {"new": 0, "skipped": 0, "failed": 1}, index)

    def resume_offset(self) -> int:
        """How many symbols from the start are all finished (contiguous prefix). Resume from here;
        anything finished beyond a gap is simply skipped again by the incremental history."""
        with self._lock:
            n = 0
            while n in self._finished:
                n += 1
            return n

    # -- summary
    def summary(self, interrupted: bool = False) -> dict:
        with self._lock:
            return {
                "symbols_total": self.total,
                "symbols_done": self.done,
                "interrupted": interrupted,
                "totals": dict(self.totals),
                "symbols_with_failures": list(self.failed_symbols),
                "elapsed_seconds": round(self.elapsed(), 1),
            }

    def write_summary(self, path: Path, interrupted: bool = False) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.summary(interrupted), indent=2), encoding="utf-8")
