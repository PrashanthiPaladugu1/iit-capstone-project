"""router: plain-code keyword routing."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from router import route  # noqa: E402


@pytest.mark.parametrize("question,expected", [
    ("check financial statement of infosys", "fundamental"),
    ("How has TCS net profit grown over 5 years?", "fundamental"),
    ("Compare ROE of INFY and TCS", "fundamental"),
    ("What is the P/E and market cap of RELIANCE?", "fundamental"),
    ("price to book of HDFCBANK", "fundamental"),
    ("return on equity of ITC", "fundamental"),
    ("show the balance sheet of Wipro-like TCS", "fundamental"),
    ("What is the RSI of TCS?", "technical"),
    ("Top 5 movers on the last day", "technical"),
    ("52 week high of INFY", "technical"),
    ("What are the stocks available?", "technical"),
    ("hello", "technical"),
    ("Revenue growth and RSI of INFY", "both"),
    ("Is TCS trend good and what is its net profit?", "both"),
    ("10 good points from last 5 years of TCS annual reports", "documents"),
    ("What did TCS management say on the earnings call?", "documents"),
    ("Summarise the investor presentation of INFY", "documents"),
    ("What did TCS management say about attrition?", "documents"),
    ("What does Reliance management say about margins?", "documents"),
    ("compare infosys and tcs", "both"),
    ("INFY vs TCS", "both"),
    ("which is better, infosys or tcs", "both"),
    ("Compare TCS versus WIPRO", "both"),
    ("compare infosys and tcs price", "technical"),
    ("compare INFY vs TCS fundamentals", "fundamental"),
    ("compare the RSI of INFY and TCS", "technical"),
    # spoken forms of "conference call", and topics people raise on those calls
    ("Find 4 stocks which shows higher capex in con calls?", "documents"),
    ("higher capex in concalls", "documents"),
    ("what was said in the con-call of TCS", "documents"),
    ("conference call guidance for INFY", "documents"),
    ("analyst call highlights of RELIANCE", "documents"),
    ("which companies talk about capex plans", "documents"),
    ("capex guidance of LT", "documents"),
    ("capital expenditure plans of ONGC", "documents"),
    ("order book commentary of LT", "documents"),
    ("which stocks mention AI in their earnings calls", "documents"),
    ("attrition at TCS", "documents"),
    # an open request for a full view of a stock needs both specialists (the research analyst)
    ("Research TCS", "both"),
    ("Full analysis of INFY", "both"),
    ("Give me a complete view of ITC", "both"),
    ("Analyse RELIANCE", "both"),
    ("Tell me everything about HDFCBANK", "both"),
    ("Is TCS a good stock to buy", "both"),
    ("research report on LT", "both"),
    ("Research the 2022 annual report of TCS", "documents"),
    ("full analysis of the RSI of TCS", "technical"),
    # natural ways to ask for the whole picture or for a view on a stock
    ("How is TCS doing?", "both"),
    ("Tell me about TCS", "both"),
    ("Should I invest in INFY", "both"),
    ("Is INFY undervalued", "both"),
    ("Is INFY overvalued", "both"),
    ("What do you think of HDFCBANK", "both"),
    ("Pros and cons of buying LT", "both"),
    ("Strengths and weaknesses of ONGC", "both"),
    ("Is it a good time to buy WIPRO", "both"),
    ("Give me a summary of RELIANCE", "both"),
    ("How is TCS doing technically and fundamentally", "both"),
    ("Is ITC cheap", "both"),
    ("Summary of the TCS annual report", "documents"),
    ("How is the RSI of TCS doing", "technical"),
    # screener snapshot columns: ratios, margins and holdings that are not in the statements
    ("show me NIFTY 50 stocks with PE RSI OPM NPM", "fundamental"),       # the screener table has RSI too
    ("show me nifty 50 stocks with PE RSI OPM NPM and the 52 week high", "both"),
    ("compare TCS and INFY on OPM NPM and PE", "fundamental"),
    ("show me nifty 50 stocks with PE OPM NPM", "fundamental"),
    ("FII holding of HDFCBANK", "fundamental"),
    ("which stocks have the highest promoter holding", "fundamental"),
    ("DII holding change in TCS", "fundamental"),
    ("ROCE and debt to equity of ITC", "fundamental"),
    ("PEG ratio of INFY", "fundamental"),
    ("stocks with OPM above 20", "fundamental"),
    ("NPM of RELIANCE", "fundamental"),
    ("industry PE of TCS", "fundamental"),
])
def test_route(question, expected):
    assert route(question) == expected


def test_documents_win_over_other_words():
    assert route("revenue guidance in the annual report of TCS") == "documents"


def test_word_boundaries_do_not_match_inside_words():
    assert route("pricey salesmen are everywhere") == "technical"      # 'sales' and 'price' are not whole words here


@pytest.mark.parametrize("question", [
    "create a postfolio of 10 stocks", "make a portfolo of 5 stocks", "build a portflio of TCS and INFY",
    "create a porfolio of ten stocks", "Create a portfollio of 6 stocks",
])
def test_a_misspelt_portfolio_still_routes_to_portfolio(question):
    assert route(question) == "portfolio"


@pytest.mark.parametrize("question", [
    "what is the RSI of TCS", "Analyze Infosys", "port facilities of Adani Ports", "important news on ITC",
    "portion of revenue from exports", "report on TCS",
])
def test_near_miss_words_are_not_taken_for_portfolio(question):
    assert route(question) != "portfolio"
