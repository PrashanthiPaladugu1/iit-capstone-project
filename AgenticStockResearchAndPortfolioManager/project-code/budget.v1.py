"""Limits shared by every agent in one user request (guardrail G8).

One Budget object is created per request and passed down the call chain, so a portfolio request that calls the
analyst, which calls the technical agent, still stops at the same totals. Depth counts agent-to-agent calls.
"""
from __future__ import annotations

from dataclasses import dataclass, field

MAX_DEPTH = 3


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class Budget:
    max_model_calls: int = 12
    max_tool_calls: int = 20
    max_tokens: int = 40000
    max_depth: int = MAX_DEPTH
    model_calls: int = 0
    tool_calls: int = 0
    tokens: int = 0
    depth: int = 0
    log: list[str] = field(default_factory=list)

    def before_model_call(self) -> None:
        if self.model_calls >= self.max_model_calls:
            raise BudgetExceeded(f"model call limit reached ({self.max_model_calls})")
        if self.tokens >= self.max_tokens:
            raise BudgetExceeded(f"token limit reached ({self.max_tokens})")

    def after_model_call(self, tokens_in: int, tokens_out: int) -> None:
        self.model_calls += 1
        self.tokens += tokens_in + tokens_out

    def before_tool_call(self) -> None:
        if self.tool_calls >= self.max_tool_calls:
            raise BudgetExceeded(f"tool call limit reached ({self.max_tool_calls})")
        self.tool_calls += 1

    def enter_agent(self, name: str) -> "Budget":
        """Call when one agent starts another. Raises past the depth limit."""
        if self.depth + 1 > self.max_depth:
            raise BudgetExceeded(f"agent depth limit reached ({self.max_depth}) at {name}")
        self.depth += 1
        self.log.append(f"{'  ' * self.depth}{name}")
        return self

    def leave_agent(self) -> None:
        self.depth = max(0, self.depth - 1)

    def summary(self) -> dict:
        return {"model_calls": self.model_calls, "tool_calls": self.tool_calls, "tokens": self.tokens}
