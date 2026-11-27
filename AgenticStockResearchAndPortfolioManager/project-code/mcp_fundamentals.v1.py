"""MCP server `fundamentals`. Run over stdio:  project-code/.venv/bin/python project-code/mcp_fundamentals.py

A thin wrapper: each tool calls a function in fundamentals.py. Errors are returned as text for the agent, not raised,
so the model sees "no financial workbook for SBILIFE" instead of a crash. Define tools ABOVE the __main__ block.
"""
from __future__ import annotations

import json
import threading

from mcp.server.mcpserver import MCPServer

from documents import Documents, DocumentsError
from fundamentals import Fundamentals, FundamentalsError

mcp = MCPServer("fundamentals")
_data: Fundamentals | None = None
_docs: Documents | None = None
# The MCP server runs tools in parallel threads, but one DuckDB connection serves one call at a time.
_lock = threading.Lock()


def _fd() -> Fundamentals:
    global _data
    if _data is None:
        _data = Fundamentals()
    return _data


def _documents() -> Documents:
    global _docs
    if _docs is None:
        _docs = Documents()
    return _docs


def _run(fn, *args, **kwargs) -> str:
    try:
        with _lock:
            return json.dumps(fn(*args, **kwargs), default=str)
    except (FundamentalsError, DocumentsError, FileNotFoundError) as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
def fsa_list_line_items(symbol: str) -> str:
    """Which line items exist for a stock in each statement section (profit_loss, quarters, balance_sheet, cash_flow, derived, price)."""
    return _run(_fd().list_line_items, symbol)


@mcp.tool()
def fsa_get_financials(symbol: str, section: str, labels: list[str] | None = None, periods: int = 5) -> str:
    """Annual statement lines for a stock. section is profit_loss, balance_sheet, cash_flow, derived or price. labels is a list such as ["Sales","Net profit"] (all if omitted). periods is how many latest years (default 5)."""
    return _run(_fd().get_financials, symbol, section, labels, periods)


@mcp.tool()
def fsa_get_quarterly(symbol: str, quarters: int = 4) -> str:
    """Latest quarterly results (Sales, Expenses, Other Income, Depreciation, Interest, Profit before tax, Tax, Net profit, Operating Profit)."""
    return _run(_fd().get_quarterly, symbol, quarters)


@mcp.tool()
def fsa_compute_growth(symbol: str, label: str, years: int = 1, section: str = "profit_loss") -> str:
    """Growth for one line item, for example label "Sales" or "Net profit". With years=1 each row is year-on-year growth. With years=N each row is the growth over N years ending at that period (NOT year-on-year), and cagr_pct is the compound annual rate over the latest N years."""
    return _run(_fd().compute_growth, symbol, label, years, section)


@mcp.tool()
def fsa_compute_ratios(symbol: str, periods: int = 5) -> str:
    """Net margin, ROE, ROA and (industrial companies only) operating margin, interest cover and debt to equity per year. Banks, finance companies and insurers get a warning and no industrial measures."""
    return _run(_fd().compute_ratios, symbol, periods)


@mcp.tool()
def fsa_get_valuation(symbol: str) -> str:
    """Market cap, price, P/E, price to book, dividend yield (and EV to sales for industrial companies) from the latest annual results."""
    return _run(_fd().get_valuation, symbol)


@mcp.tool()
def fsa_coverage() -> str:
    """Which Nifty 50 stocks have no financial workbook (statement data missing)."""
    return _run(_fd().coverage)


@mcp.tool()
def rag_search_documents(query: str, symbol: str | None = None, doc_type: str | None = None, year: int | None = None,
                     top_k: int = 5) -> str:
    """Search the text of annual reports, earnings-call transcripts and investor presentations. Returns passages with file and page, or found=false. doc_type is transcript, annual_report or presentation (all if omitted). year is the document year. Use for meaning (risks, strategy, management comments, reasons), never for numbers."""
    return _run(_documents().search, query, symbol, doc_type, year, top_k)


if __name__ == "__main__":
    mcp.run("stdio")
