"""router: decides which agent answers a chat question. Plain code, no model call, so it is fast and testable.

Routes:
  technical    price, trend, indicators, returns, movers
  fundamental  financial statements, growth, ratios, valuation
  both         the question mixes the two (both agents run and both answers are shown)
  documents    annual reports, transcripts, presentations (answered by agent_fundamental with rag_search_documents)

A question with no keyword goes to `technical`, which has the stock list tool and says plainly when it cannot help.
The planned LLM router (role `router`) can replace `route()` later without changing the callers.
"""
from __future__ import annotations

import re

DOCUMENTS = ["annual report", "annual reports", "transcript", "transcripts", "earnings call", "concall", "con call",
             "investor presentation", "presentation", "management said", "management commentary", "risk factors",
             "mda", "md&a", "what did management", "outlook statement", "management say", "management says",
             "management comment", "management comments", "management think",
             # spoken and plural forms of "conference call", and topics that live in calls and reports, not in the statements
             "earnings calls", "con call", "con calls", "con-call", "con-calls", "concalls", "conference call",
             "conference calls", "analyst call", "analyst calls", "capex", "capital expenditure", "guidance",
             "order book", "attrition"]

FUNDAMENTAL = ["financial statement", "financial statements", "financials", "fundamental", "fundamentals",
               "balance sheet", "profit and loss", "p&l", "income statement", "cash flow", "revenue", "sales",
               "net profit", "profit", "earnings", "ebitda", "operating margin", "net margin", "margin", "margins",
               "roe", "roa", "roce", "return on equity", "return on assets", "debt", "borrowings", "interest cover",
               "p/e", "pe ratio", "price to earnings", "price to book", "p/b", "market cap", "market capitalisation",
               "market capitalization", "valuation", "dividend", "dividend yield", "cagr", "quarterly results",
               "quarterly result", "quarter results", "balance-sheet", "equity", "reserves", "assets", "liabilities"]

TECHNICAL = ["technical", "rsi", "macd", "sma", "ema", "bollinger", "atr", "moving average", "trend", "momentum",
             "price", "prices", "close", "closing", "volume", "delivery", "52-week", "52 week", "52w", "return",
             "returns", "movers", "gainers", "losers", "volatility", "support", "resistance", "overbought",
             "oversold", "chart", "ohlc", "ohlcv", "quote"]

# A comparison with no price or financial word ("compare infosys and tcs") needs both views.
COMPARE = ["compare", "comparison", "versus", "vs", "which is better", "better than"]

# An open request for the whole picture of a stock. Needs both views, so it goes to the research analyst.
RESEARCH = ["research", "full analysis", "complete analysis", "detailed analysis", "complete view", "full view",
            "analyse", "analyze", "everything about", "overview of", "is it a good stock", "good stock to buy",
            "worth buying", "investment case", "stock report", "tell me about", "how is", "how are", "should i invest",
            "invest in", "should i buy", "undervalued", "overvalued", "cheap", "expensive", "what do you think",
            "pros and cons", "strengths and weaknesses", "good time to buy", "summary of", "technically and fundamentally",
            "fundamentally and technically"]

# Phrases that contain a technical word but are fundamental. Removed before the technical check.
_FUNDAMENTAL_PHRASES = ["price to earnings", "price to book", "return on equity", "return on assets",
                        "return on capital", "price/earnings", "price-to-earnings", "price-to-book"]


def _has(words: list[str], text: str) -> bool:
    return any(re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", text) for w in words)


def route(question: str) -> str:
    text = " ".join(question.lower().split())
    if _has(DOCUMENTS, text):
        return "documents"
    fundamental = _has(FUNDAMENTAL, text)
    stripped = text
    for phrase in _FUNDAMENTAL_PHRASES:
        stripped = stripped.replace(phrase, " ")
    technical = _has(TECHNICAL, stripped)
    if fundamental and technical:
        return "both"
    if not fundamental and not technical and _has(RESEARCH, text):
        return "both"
    if not fundamental and not technical and _has(COMPARE, text):
        return "both"
    return "fundamental" if fundamental else "technical"
