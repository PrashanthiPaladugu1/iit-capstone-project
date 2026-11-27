"""MCP server `news`. Run over stdio:  project-code/.venv/bin/python project-code/mcp_news.py

A thin wrapper over news_tools.py. Errors are returned as {"error": ...} text for the agent, not raised.
Define tools ABOVE the __main__ block.
"""
from __future__ import annotations

import json
import threading

from mcp.server.mcpserver import MCPServer

from news_tools import NewsError, NewsTools

mcp = MCPServer("news")
_tools: NewsTools | None = None
_lock = threading.Lock()


def _nt() -> NewsTools:
    global _tools
    if _tools is None:
        _tools = NewsTools()
    return _tools


def _run(fn, *args, **kwargs) -> str:
    try:
        with _lock:
            return json.dumps(fn(*args, **kwargs), default=str)
    except NewsError as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
def news_search(stock: str, days: int = 7, limit: int = 10) -> str:
    """Recent headlines that name one Nifty 50 stock, newest first, from Economic Times, Mint, Business Standard, Hindu BusinessLine and NDTV Profit. stock is a symbol or a company name (TCS, INFY, Infosys). days is 1 to 30. Each headline has source, date, title and link. Headlines only, never full articles. No headlines can mean the stock was not in these feeds."""
    return _run(_nt().search, stock, days, limit)


@mcp.tool()
def news_sentiment(stock: str, days: int = 7) -> str:
    """Counts of positive, negative and neutral headlines for one Nifty 50 stock over the last `days` days (1 to 30), with the labelled headlines. A model labels each headline and code adds up the counts. A rough guide from headlines only, not a forecast."""
    return _run(_nt().sentiment, stock, days)


@mcp.tool()
def news_market(days: int = 1, limit: int = 10) -> str:
    """Latest general Indian market headlines (indices, rupee, economy, sectors), newest first. Use only when no stock is named."""
    return _run(_nt().market, days, limit)


if __name__ == "__main__":
    mcp.run("stdio")
