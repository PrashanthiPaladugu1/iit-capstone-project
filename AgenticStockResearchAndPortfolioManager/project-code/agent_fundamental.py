"""agent_fundamental: answers questions about company financials (profit, balance sheet, cash flow, ratios, valuation).

It reuses the loop in agent_technical.py (model node, LangGraph ToolNode, shared Budget, "no tool data, no answer" rule)
and changes only three things: the tools (wrappers over the `fundamentals` MCP server), the system prompt, and the
agent name used in the usage log. The numbers come from Excel workbooks and Screener CSV snapshots loaded into DuckDB, never from the model.

    agent = FundamentalAgent(gateway, server)       # server = McpServer("fundamentals", "mcp_fundamentals.py")
    result = agent.run("How has TCS profit grown over 5 years?", session="s1")
"""
from __future__ import annotations

from langchain_core.tools import BaseTool, tool

from agent_technical import TechnicalAgent, TechnicalResult

AGENT = "agent_fundamental"
FundamentalResult = TechnicalResult

SYSTEM_PROMPT = """You are the fundamental analysis agent in a Nifty 50 research app. You have two sources: the financial
statements (numbers) and the text of annual reports, earnings-call transcripts and investor presentations (meaning).
Rules:
- Use the tools to get every number. Never quote a sales, profit, ratio or valuation figure you did not get from a tool.
- Only Nifty 50 stocks are covered. SBILIFE has no financial workbook: if asked, say its statements are missing. If a
  tool says a stock is not covered, say so plainly.
- The workbooks state no unit. Say "in the workbook's units (probably Rs crore)" once when you quote amounts. Ratios and
  growth rates are percentages and need no unit.
- Banks, finance companies and insurers are reported differently (for a bank, Sales is total income and Interest is an
  expense). Do not quote operating margin, interest cover or debt to equity for them. Pass on the tool's warning.
- Use fsa_get_financials for statement lines, fsa_get_quarterly for the latest quarters, fsa_compute_growth for growth
  and CAGR, fsa_compute_ratios for margins, ROE and ROA, fsa_get_valuation for P/E, price to book and market cap. If
  unsure which line names exist, call fsa_list_line_items first.
- For a comparison of several stocks, call the tool once per stock and put the results side by side.
- Say which years or quarters the figures are for. A CAGR is not given when the starting value is not positive: say so.
- P/E, price to book and interest cover are plain multiples (write 16.55, or 16.55x), never a percentage. Margins, ROE,
  ROA, growth and dividend yield are percentages.
- For "how did X grow over N years" quote start_value, end_value and cagr_pct from fsa_compute_growth with years=N. Call it
  with years=1 only when year-on-year growth is wanted. With years=N the rows are N-year growth, not year-on-year.
- screener_* tools read the Screener snapshot (all 50 stocks, SBILIFE included), which is dated and not live. Use
  screener_get_table for "show me stocks with P/E, RSI, OPM, NPM" and for rankings or filters: put the metrics in a list,
  e.g. ["pe", "rsi", "opm", "npm"], and show the rows as a table with a column per metric. Use screener_get_snapshot for
  one stock's P/E, industry P/E, PEG, ROCE, debt to equity, margins, promoter, FII and DII holding. Use screener_get_history
  for how one metric moved across the snapshot dates. State the as_of date once. OPM and NPM here are the latest quarter's
  margins, P/E is on trailing profit, and the amounts look like crore rupees. History covers about five months only.
  A blank cell means the measure does not apply (banks, finance companies, insurers) or is missing: say so, never fill it.
  For statements over several years use fsa_*. If the two differ, say which source each number came from.
- Do not say buy or sell and do not predict. Describe what the numbers show.
- For risks, strategy, management comments, outlook, reasons or "what did management say", call rag_search_documents. Pass the
  stock symbol, and doc_type (transcript, annual_report or presentation) when the question names one. Never take a
  number from it: get numbers from the statement tools.
- Cite every point taken from rag_search_documents with its file and page, for example (Transcript_Oct_2025.pdf, p. 7). Use
  only what the passages say. If it returns found=false, say no matching passage was found; do not fill in from memory.
- Only the latest annual reports, all transcripts and the latest presentations are indexed. ITC and TRENT have no
  transcripts, BAJAJ-AUTO has no presentations and INFY has no documents. Say so when the search finds nothing for them.
- News is not available.
- Keep the answer short: a few lines or a small table, not an essay."""

REMINDER = ("You must call at least one tool to get the data before you answer. "
            "Do not write numbers from memory or placeholders. Call the right tool now.")
NO_DATA_ANSWER = ("I have no tool data for this question, so I will not guess numbers. "
                  "Try naming one of the Nifty 50 stocks, for example: 'What is the net profit trend of TCS?'")


def make_tools(call) -> list[BaseTool]:
    """The tools this agent may use. `call(name, arguments)` runs one tool on the MCP server and returns text."""

    @tool
    def fsa_list_line_items(symbol: str) -> str:
        """Which line items exist for a stock in each statement section (profit_loss, quarters, balance_sheet, cash_flow, derived, price)."""
        return call("fsa_list_line_items", {"symbol": symbol})

    @tool
    def fsa_get_financials(symbol: str, section: str, labels: list[str] | None = None, periods: int = 5) -> str:
        """Annual statement lines for one stock. section is profit_loss, balance_sheet, cash_flow, derived or price. labels is a list such as ["Sales", "Net profit"] (all lines if omitted). periods is how many latest years (default 5)."""
        return call("fsa_get_financials", {"symbol": symbol, "section": section, "labels": labels, "periods": periods})

    @tool
    def fsa_get_quarterly(symbol: str, quarters: int = 4) -> str:
        """Latest quarterly results: Sales, Expenses, Other Income, Depreciation, Interest, Profit before tax, Tax, Net profit, Operating Profit."""
        return call("fsa_get_quarterly", {"symbol": symbol, "quarters": quarters})

    @tool
    def fsa_compute_growth(symbol: str, label: str, years: int = 1, section: str = "profit_loss") -> str:
        """Growth for one line item, for example label "Sales" or "Net profit". With years=1 each row is year-on-year growth. With years=N each row is the growth over N years ending at that period (NOT year-on-year), and cagr_pct is the compound annual rate over the latest N years."""
        return call("fsa_compute_growth", {"symbol": symbol, "label": label, "years": years, "section": section})

    @tool
    def fsa_compute_ratios(symbol: str, periods: int = 5) -> str:
        """Net margin, ROE, ROA and (industrial companies only) operating margin, interest cover and debt to equity per year. Banks, finance companies and insurers get a warning and no industrial measures."""
        return call("fsa_compute_ratios", {"symbol": symbol, "periods": periods})

    @tool
    def fsa_get_valuation(symbol: str) -> str:
        """Market cap, price, P/E, price to book, dividend yield (and EV to sales for industrial companies) from the latest annual results."""
        return call("fsa_get_valuation", {"symbol": symbol})

    @tool
    def fsa_coverage() -> str:
        """Which Nifty 50 stocks have no financial workbook (statement data missing)."""
        return call("fsa_coverage", {})

    @tool
    def rag_search_documents(query: str, symbol: str | None = None, doc_type: str | None = None, year: int | None = None,
                         top_k: int = 5) -> str:
        """Search the text of annual reports, earnings-call transcripts and investor presentations. Returns passages with file and page, or found=false. doc_type is transcript, annual_report or presentation (all if omitted). year is the document year. Use for meaning (risks, strategy, management comments, reasons), never for numbers."""
        return call("rag_search_documents", {"query": query, "symbol": symbol, "doc_type": doc_type, "year": year,
                                         "top_k": top_k})

    @tool
    def screener_get_table(metrics: list[str], sort_by: str | None = None, descending: bool = True, limit: int = 50,
                           min_values: dict[str, float] | None = None, max_values: dict[str, float] | None = None,
                           industry_group: str | None = None) -> str:
        """Many Nifty 50 stocks side by side from the latest Screener snapshot (all 50 including SBILIFE). metrics is a list such as ["pe","rsi","opm","npm"]. Valid names include pe, pb, peg, industry_pe, rsi, macd, opm, npm, gpm (latest quarter margins), roce, debt_to_equity, eps, dividend_yield, market_capitalization, enterprise_value, sales, profit_after_tax, sales_growth, profit_growth, promoter_holding, fii_holding, dii_holding, current_price, dma_50, dma_200, industry_group. sort_by is one numeric metric and descending picks the order. min_values and max_values filter, for example {"roce": 15}. industry_group filters to one group such as "Banks". limit is at most 50. Returns columns, rows and the snapshot date (as_of). Margins and debt are blank for banks, finance companies and insurers."""
        return call("screener_get_table", {"metrics": metrics, "sort_by": sort_by, "descending": descending, "limit": limit,
                                           "min_values": min_values, "max_values": max_values, "industry_group": industry_group})

    @tool
    def screener_get_snapshot(symbol: str) -> str:
        """Every Screener metric of one Nifty 50 stock from the latest snapshot: P/E, industry P/E, PEG, P/B, ROCE, debt to equity, margins, growth, promoter, FII and DII holding and their change, dividend yield, RSI, 50 and 200 day averages, and more. Works for SBILIFE too. Returns the snapshot date (as_of)."""
        return call("screener_get_snapshot", {"symbol": symbol})

    @tool
    def screener_get_history(symbol: str, metric: str, limit: int = 60) -> str:
        """One numeric Screener metric of one stock across the snapshot dates (oldest first), with first, latest, min and max. Covers about five months only (June to November 2026), so it shows a short range, not a long-term trend. metric is a name such as pe, rsi, fii_holding, promoter_holding, market_capitalization."""
        return call("screener_get_history", {"symbol": symbol, "metric": metric, "limit": limit})

    return [fsa_list_line_items, fsa_get_financials, fsa_get_quarterly, fsa_compute_growth, fsa_compute_ratios,
            fsa_get_valuation, fsa_coverage, rag_search_documents, screener_get_table, screener_get_snapshot,
            screener_get_history]


class FundamentalAgent(TechnicalAgent):
    agent_name = AGENT
    system_prompt = SYSTEM_PROMPT
    reminder = REMINDER
    no_data_answer = NO_DATA_ANSWER

    def run(self, question: str, *, route: str = "fundamental", **kw) -> FundamentalResult:
        # `focus` (see TechnicalAgent.run) passes through **kw.
        return super().run(question, route=route, **kw)

    def _make_tools(self) -> list[BaseTool]:
        return make_tools(self._run_tool)
