"""MCP server `market-data`. Run over stdio:  project-code/.venv/bin/python project-code/mcp_market_data.py

A thin wrapper: each tool calls a function in market_data.py. Errors are returned as text for the agent, not
raised, so the model sees "not a Nifty 50 stock" instead of a crash. MCP SDK v2: MCPServer and @mcp.tool().
"""
from __future__ import annotations

import json
import threading

from mcp.server.mcpserver import MCPServer

import prices_db
from market_data import MarketData, MarketDataError

mcp = MCPServer("market-data")
_data: MarketData | None = None
# The MCP server runs tools in parallel threads, but one DuckDB connection serves one call at a time.
_lock = threading.Lock()


def _md() -> MarketData:
    global _data
    if _data is None:
        _data = MarketData()
    return _data


def _run(fn, *args, **kwargs) -> str:
    try:
        with _lock:
            return json.dumps(fn(*args, **kwargs), default=str)
    except (MarketDataError, prices_db.PriceDataError) as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
def get_latest_quote(symbol: str) -> str:
    """Latest close, previous close, percent change, volume and delivery percent for one Nifty 50 stock."""
    return _run(_md().get_latest_quote, symbol)


@mcp.tool()
def get_ohlcv(symbol: str, days: int = 30) -> str:
    """Daily open, high, low, close, volume and delivery percent for the last `days` trading days (maximum 260)."""
    return _run(_md().get_ohlcv, symbol, days)


@mcp.tool()
def get_returns(symbol: str) -> str:
    """Percent return over 1 day, 1 week, 1 month, 3 months, 6 months and 1 year."""
    return _run(_md().get_returns, symbol)


@mcp.tool()
def get_52w_high_low(symbol: str) -> str:
    """52-week high and low and how far the latest close is from each."""
    return _run(_md().get_52w_high_low, symbol)


@mcp.tool()
def get_delivery_pct(symbol: str, days: int = 20) -> str:
    """Average and latest delivery percent over the last `days` trading days."""
    return _run(_md().get_delivery_pct, symbol, days)


@mcp.tool()
def get_indicators(symbol: str) -> str:
    """Latest SMA 20/50/200, EMA 20, RSI 14, MACD, Bollinger bands and ATR 14."""
    return _run(_md().get_indicators, symbol)


@mcp.tool()
def compare_stocks(symbols: list[str]) -> str:
    """Compare 2 to 6 stocks side by side: close, returns, RSI and distance from the 52-week high."""
    return _run(_md().compare_stocks, symbols)


@mcp.tool()
def top_movers(period: str = "1M", n: int = 5) -> str:
    """Best and worst `n` Nifty 50 stocks by return. period is one of 1D, 1W, 1M, 3M, 6M, 1Y."""
    return _run(_md().top_movers, period, n)


@mcp.tool()
def data_status() -> str:
    """Date range, row count and build time of the price data, plus the price caveat."""
    return _run(_md().data_status)


@mcp.tool()
def list_stocks() -> str:
    """All Nifty 50 stocks this app has data for: symbol, company name and industry group. Use for 'which stocks are available'."""
    return _run(_md().list_stocks)


if __name__ == "__main__":
    mcp.run("stdio")
