"""Limits shared by every agent in one user request (guardrail G8).

One Budget object is created per request and passed down the call chain, so a portfolio request that calls the
analyst, which calls the technical agent, still stops at the same totals. Depth counts agent-to-agent calls.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from dataclasses import dataclass, field

MAX_DEPTH = 3


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class Budget:
    max_model_calls: int = 12
    max_tool_calls: int = 20
    max_tokens: int = 40000
    max_cost: float | None = None          # money for one request; None = no limit (local models cost nothing)
    max_depth: int = MAX_DEPTH
    model_calls: int = 0
    tool_calls: int = 0
    tokens: int = 0
    cost: float = 0.0
    depth: int = 0
    log: list[str] = field(default_factory=list)
    # Agents may run in several threads (the analyst's parallel mode). The counters are shared and guarded by this lock.
    # Depth is per branch: a thread inside branch() has its own depth, so two specialists are both one level below their parent.
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False, compare=False)
    _local: threading.local = field(default_factory=threading.local, repr=False, compare=False)

    def before_model_call(self) -> None:
        with self._lock:
            if self.model_calls >= self.max_model_calls:
                raise BudgetExceeded(f"model call limit reached ({self.max_model_calls})")
            if self.tokens >= self.max_tokens:
                raise BudgetExceeded(f"token limit reached ({self.max_tokens})")
            if self.max_cost is not None and self.cost >= self.max_cost:
                raise BudgetExceeded(f"cost limit reached ({self.max_cost})")

    def after_model_call(self, tokens_in: int, tokens_out: int, cost: float | None = None) -> None:
        with self._lock:
            self.model_calls += 1
            self.tokens += tokens_in + tokens_out
            self.cost += cost or 0.0

    def before_tool_call(self) -> None:
        with self._lock:
            if self.tool_calls >= self.max_tool_calls:
                raise BudgetExceeded(f"tool call limit reached ({self.max_tool_calls})")
            self.tool_calls += 1

    def current_depth(self) -> int:
        """Depth seen by the calling thread: its own branch depth inside branch(), else the shared depth."""
        local = getattr(self._local, "depth", None)
        return self.depth if local is None else local

    @contextmanager
    def branch(self, depth: int):
        """Run one parallel branch (a thread) starting at `depth`. Enter and leave inside it change only this branch."""
        self._local.depth = depth
        try:
            yield self
        finally:
            self._local.depth = None

    def enter_agent(self, name: str) -> "Budget":
        """Call when one agent starts another. Raises past the depth limit."""
        with self._lock:
            now = self.current_depth()
            if now + 1 > self.max_depth:
                raise BudgetExceeded(f"agent depth limit reached ({self.max_depth}) at {name}")
            self._set_depth(now + 1)
            self.log.append(f"{'  ' * (now + 1)}{name}")
        return self

    def leave_agent(self) -> None:
        with self._lock:
            self._set_depth(max(0, self.current_depth() - 1))

    def _set_depth(self, value: int) -> None:
        if getattr(self._local, "depth", None) is None:
            self.depth = value
        else:
            self._local.depth = value

    def summary(self) -> dict:
        with self._lock:
            return {"model_calls": self.model_calls, "tool_calls": self.tool_calls, "tokens": self.tokens,
                    "cost": round(self.cost, 8)}
