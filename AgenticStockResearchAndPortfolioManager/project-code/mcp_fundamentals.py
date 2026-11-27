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
from screener import Screener, ScreenerError

mcp = MCPServer("fundamentals")
_data: Fundamentals | None = None
_docs: Documents | None = None
_screener: Screener | None = None
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


def _sc() -> Screener:
    global _screener
    if _screener is None:
        _screener = Screener()
    return _screener


def _run(fn, *args, **kwargs) -> str:
    try:
        with _lock:
            return json.dumps(fn(*args, **kwargs), default=str)
    except (FundamentalsError, DocumentsError, ScreenerError, FileNotFoundError) as exc:
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


@mcp.tool()
def screener_get_table(metrics: list[str], sort_by: str | None = None, descending: bool = True, limit: int = 50,
                       min_values: dict[str, float] | None = None, max_values: dict[str, float] | None = None,
                       industry_group: str | None = None) -> str:
    """Many Nifty 50 stocks side by side from the latest Screener snapshot (all 50 including SBILIFE). metrics is a list such as ["pe","rsi","opm","npm"]. Valid names include pe, pb, peg, industry_pe, rsi, macd, opm, npm, gpm (latest quarter margins), roce, debt_to_equity, eps, dividend_yield, market_capitalization, enterprise_value, sales, profit_after_tax, sales_growth, profit_growth, promoter_holding, fii_holding, dii_holding, current_price, dma_50, dma_200, industry_group. sort_by is one numeric metric and descending picks the order. min_values and max_values filter, for example {"roce": 15}. industry_group filters to one group such as "Banks". limit is at most 50. Returns columns, rows and the snapshot date (as_of). Margins and debt are blank for banks, finance companies and insurers."""
    return _run(_sc().get_table, metrics, sort_by, descending, limit, min_values, max_values, industry_group)


@mcp.tool()
def screener_get_snapshot(symbol: str) -> str:
    """Every Screener metric of one Nifty 50 stock from the latest snapshot: P/E, industry P/E, PEG, P/B, ROCE, debt to equity, margins, growth, promoter, FII and DII holding and their change, dividend yield, RSI, 50 and 200 day averages, and more. Works for SBILIFE too. Returns the snapshot date (as_of)."""
    return _run(_sc().get_snapshot, symbol)


@mcp.tool()
def screener_get_history(symbol: str, metric: str, limit: int = 60) -> str:
    """One numeric Screener metric of one stock across the snapshot dates (oldest first), with first, latest, min and max. Covers about five months only (June to November 2026), so it shows a short range, not a long-term trend. metric is a name such as pe, rsi, fii_holding, promoter_holding, market_capitalization."""
    return _run(_sc().get_history, symbol, metric, limit)


if __name__ == "__main__":
    mcp.run("stdio")
