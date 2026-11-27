"""MCP server `portfolio`. Run over stdio:  project-code/.venv/bin/python project-code/mcp_portfolio.py

A thin wrapper over portfolio.py and scorecard.py. Errors are returned as {"error": ...} text for the agent, not raised.
Results are kept small: the agent loop cuts a tool result at 6,000 characters, and cut-off JSON is useless to the model.
Define tools ABOVE the __main__ block.
"""
from __future__ import annotations

import json
import threading

from mcp.server.mcpserver import MCPServer

from portfolio import PortfolioError, PortfolioTools
from scorecard import ScorecardError

mcp = MCPServer("portfolio")
MAX_SCORECARD_ROWS = 25
_tools: PortfolioTools | None = None
_lock = threading.Lock()                 # one DuckDB connection serves one call at a time


def _pt() -> PortfolioTools:
    global _tools
    if _tools is None:
        _tools = PortfolioTools.default()
    return _tools


def _run(fn, *args, **kwargs) -> str:
    try:
        with _lock:
            return json.dumps(fn(*args, **kwargs), default=str)
    except (PortfolioError, ScorecardError, FileNotFoundError) as exc:
        return json.dumps({"error": str(exc)})


def _scorecard(strategy: str, limit: int) -> dict:
    card = _pt().scorecard.score_all(strategy)
    n = max(1, min(int(limit), MAX_SCORECARD_ROWS))
    rows = [{"symbol": r["symbol"], "industry_group": r["industry_group"], "total": r["total"], "momentum": r["momentum"],
             "quality": r["quality"], "valuation": r["valuation"], "risk": r["risk"],
             "vol_1y_pct": r["inputs"]["vol_1y_pct"], "flagged": bool(r["flags"])} for r in card["rows"][:n]]
    return {"strategy": card["strategy"], "factor_weights": card["weights"], "as_of": card["as_of"], "shown": len(rows),
            "rows": rows, "caveat": card["caveat"]}


@mcp.tool()
def portfolio_scorecard(strategy: str = "balanced", limit: int = 10) -> str:
    """Rank the Nifty 50 stocks for a strategy, best first, at most 25 rows. strategy is balanced, momentum, low_risk, quality, value, long_term or short_term. Each row has total, momentum, quality, valuation and risk (0 worst to 100 best; high risk score means low volatility) and a flagged marker for short history or a price jump. Past data only; not a forecast."""
    return _run(_scorecard, strategy, limit)


@mcp.tool()
def portfolio_suggest(strategy: str = "balanced", size: int = 5, include: list[str] | None = None,
                      exclude: list[str] | None = None) -> str:
    """Pick 4 to 6 Nifty 50 stocks for a strategy (balanced, momentum, low_risk, quality, value, long_term, short_term), one per industry group, best scorecard total first. include forces stocks in, exclude keeps stocks out. Returns picks and the same-group stocks that were skipped. Use portfolio_build instead when weights and a past replay are wanted."""
    return _run(_pt().suggest, strategy, size, include, exclude)


@mcp.tool()
def portfolio_build(strategy: str = "balanced", size: int = 5, weighting: str = "equal", include: list[str] | None = None,
                    exclude: list[str] | None = None, days: int = 252) -> str:
    """Build one portfolio of 4 to 6 Nifty 50 stocks: picks, weights (5% to 40% each, adding to 100%), guardrail result and a buy-and-hold replay of the last `days` trading days (return, max drawdown, volatility). strategy is balanced, momentum, low_risk, quality, value, long_term or short_term. weighting is equal or inverse_vol. The result includes a footer that must be shown. Call it again with a different strategy for another portfolio."""
    return _run(_pt().build, strategy, size, weighting, include, exclude, days)


@mcp.tool()
def portfolio_evaluate(symbols: list[str], weights: dict[str, float] | None = None, days: int = 252) -> str:
    """Check a portfolio the user named and replay its past. symbols are Nifty 50 symbols; weights are percentages per symbol (equal weights if omitted). Returns the guardrail result (blocks and warnings) and, when nothing blocks, a buy-and-hold replay. The result includes a footer that must be shown."""
    return _run(_pt().evaluate, symbols, weights, days)


if __name__ == "__main__":
    mcp.run("stdio")
