"""input_guard: built-in checks on the QUESTION TEXT, in plain code, before any agent or model runs.

G1 a stock outside the Nifty 50 is named        G2/G3 a portfolio question asks for fewer than 4 or more than 6 stocks
Uses small stock lists built in the test, plus one test on the project's real lists (skipped when the files are absent).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import input_guard as ig  # noqa: E402

NIFTY = [{"Name": "Tata Consultancy", "NSE Code": "TCS"}, {"Name": "Infosys", "NSE Code": "INFY"},
         {"Name": "Tata Motors PVeh", "NSE Code": "TMPV"}, {"Name": "ITC", "NSE Code": "ITC"},
         {"Name": "HDFC Bank", "NSE Code": "HDFCBANK"}, {"Name": "Larsen & Toubro", "NSE Code": "LT"}]
ALIASES = {"TCS": (["Tata Consultancy"], ["TCS"], []), "INFY": (["Infosys"], [], []), "TMPV": (["Tata Motors"], [], []),
           "ITC": ([], ["ITC"], []), "HDFCBANK": (["HDFC Bank"], [], []), "LT": (["Larsen"], ["L&T"], [])}
ALL = NIFTY + [{"Name": "Adani Total Gas", "NSE Code": "ATGL"}, {"Name": "Vedanta", "NSE Code": "VEDL"},
               {"Name": "Tata Chemicals", "NSE Code": "TATACHEM"}, {"Name": "Tata Motors", "NSE Code": "TATAMOTORS"},
               {"Name": "Premier", "NSE Code": "PREMIER"}, {"Name": "Wipro", "NSE Code": "WIPRO"},
               {"Name": "Oil India", "NSE Code": "OIL"}, {"Name": "Tata Power", "NSE Code": "TATAPOWER"},
               {"Name": "Reliance Power", "NSE Code": "RPOWER"}, {"Name": "No Code Ltd", "NSE Code": ""}]


@pytest.fixture(scope="module")
def guard():
    return ig.InputGuard(NIFTY, ALL, ALIASES)


def ids(result):
    return [b["id"] for b in result.blocks]


# ----------------------------------------------------------------------------------------------- G1: stock names
@pytest.mark.parametrize("question, named", [
    ("Analyze Adani GAS", "Adani Gas"),                          # added by hand: the list calls it Adani Total Gas
    ("analyze adani total gas", "Adani Total Gas"),
    ("Analyze ATGL", "ATGL"),
    ("What is the RSI of Vedanta?", "Vedanta"),
    ("Tata Chemicals share price", "Tata Chemicals"),
    ("Is Tata Power a good buy", "Tata Power"),
    ("Latest news on Tesla", "Tesla"),
    ("Compare TCS with Wipro", "Wipro"),
    ("What is the RSI of ADANIGAS", "ADANIGAS"),
    ("Add Tesla and Infosys to my portfolio of TCS and ITC", "Tesla"),
    ("RSI of Microsoft", "Microsoft"),
    ("How is Britannia doing", "Britannia"),                      # the list says "Britannia Inds.", so it is added by hand
])
def test_a_stock_outside_the_nifty_50_is_blocked_with_g1(guard, question, named):
    result = guard.check(question)
    assert result.blocked and ids(result) == ["G1"]
    assert named in result.blocks[0]["text"] and "not in the Nifty 50" in result.blocks[0]["text"]
    assert named in result.blocks[0]["names"]


def test_several_outside_stocks_are_listed_once_each_in_one_alert(guard):
    result = guard.check("Compare Tesla with Vedanta and Tesla again")
    assert len(result.blocks) == 1 and sorted(result.blocks[0]["names"]) == ["Tesla", "Vedanta"]
    assert "are not in the Nifty 50" in result.blocks[0]["text"]


@pytest.mark.parametrize("question", [
    "RSI of TCS", "Compare TCS with Infosys", "What is the RSI of INFY?", "Is Tata Motors a good buy",      # Tata Motors is TMPV here
    "How is Tata Motors PVeh doing", "Revenue growth of HDFC Bank", "RSI of L&T", "Larsen price trend",
    "PE of ITC", "Top 5 movers today", "Show me NIFTY 50 PE RSI OPM NPM", "Any news on the Nifty 50 this week?",
    "What is the weather in Mumbai", "RSI of TCS and the latest news on it", "tell me about the premier league",
    "Why is oil falling today", "Analyze the IT sector", "Explain the MACD", "What does P/E mean?",
])
def test_valid_nifty_questions_and_ordinary_words_are_not_blocked(guard, question):
    assert not guard.check(question).blocked, question


def test_a_nifty_name_that_is_also_part_of_an_outside_name_is_not_blocked(guard):
    # "Tata Motors" is a Nifty stock here (TMPV) even though the all-stocks list also has an old "Tata Motors" row.
    assert not guard.check("Tata Motors RSI").blocked


def test_a_code_must_be_typed_in_capitals_to_count(guard):
    assert not guard.check("what is oil doing").blocked and not guard.check("is premier a word").blocked
    assert not guard.check("OIL prices today").blocked          # three letters: too short to be a confident match


def test_rows_with_no_code_do_not_break_the_loader(guard):
    assert not guard.check("hello").blocked


def test_the_ambiguous_single_words_are_not_matched(guard):
    assert not guard.check("Premier league table").blocked and "premier" in ig.AMBIGUOUS


# ----------------------------------------------------------------------------------------------- G2 / G3: portfolio size
@pytest.mark.parametrize("question, rule, count", [
    ("Create a portfolio of 10 stocks", "G2", 10),
    ("create a postfolio of 10 stocks", "G2", 10),
    ("Create a portfolio of 7 stocks", "G2", 7),
    ("build me a portfolio of ten stocks", "G2", 10),
    ("Create a portfolio of 2 stocks: TCS and INFY", "G3", 2),
    ("make a 3-stock portfolio", "G3", 3),
    ("Give me a portfolio of three low-risk stocks", "G3", 3),
    ("portfolio with 1 stock", "G3", 1),
    ("create a portfolio of 20 shares", "G2", 20),
])
def test_a_portfolio_size_outside_4_to_6_is_blocked(guard, question, rule, count):
    result = guard.check(question, portfolio=True)
    assert ids(result) == [rule] and result.blocks[0]["count"] == count
    assert str(count) in result.blocks[0]["text"] and "4 to 6" in result.blocks[0]["text"]


@pytest.mark.parametrize("question", [
    "Create a portfolio of 4 stocks", "Create a portfolio of 5 stocks", "Make a 6-stock portfolio",
    "Make a portfolio of five low risk stocks", "Create a balanced portfolio", "Create a portfolio of TCS, INFY, ITC, LT",
    "Give me 2 portfolio ideas for long term and short term",     # "2 portfolio ideas" is a count of portfolios, not stocks
])
def test_a_valid_or_unstated_portfolio_size_passes(guard, question):
    assert not guard.check(question, portfolio=True).blocked, question


def test_the_size_check_runs_only_for_a_portfolio_question(guard):
    assert not guard.check("Top 10 stocks by return this month").blocked
    assert not guard.check("Which 2 stocks have the highest RSI?").blocked


def test_nifty_50_stocks_is_not_a_portfolio_size(guard):
    assert not guard.check("Build a portfolio from the Nifty 50 stocks", portfolio=True).blocked
    assert not guard.check("Pick 5 stocks out of the Nifty50 stocks for a portfolio", portfolio=True).blocked


def test_two_different_counts_in_one_question_are_not_guessed(guard):
    assert not guard.check("From 20 stocks I like, make a portfolio of 5 stocks", portfolio=True).blocked


def test_a_size_and_an_outside_stock_give_both_alerts_in_order(guard):
    result = guard.check("Create a portfolio of 10 stocks with Tesla", portfolio=True)
    assert ids(result) == ["G1", "G2"]


def test_an_alert_line_is_the_text_of_each_block(guard):
    result = guard.check("Create a portfolio of 10 stocks with Tesla", portfolio=True)
    assert result.alerts == [b["text"] for b in result.blocks] and result.alerts[0].startswith("G1:")


# ----------------------------------------------------------------------------------------------- what the chat shows
def test_the_checks_listed_for_the_trace_name_every_built_in_check(guard):
    assert guard.CHECKS == ("G1 stock names", "G2/G3 portfolio size")


def test_an_empty_or_odd_question_is_passed_not_crashed(guard):
    for q in ("", "   ", "?!", "ADANI" * 500):
        assert not guard.check(q).blocked


# ----------------------------------------------------------------------------------------------- the project's real lists
def test_real_lists_do_not_block_any_nifty_50_name_or_code():
    try:
        real = ig.load_default()
    except ig.InputGuardError:
        pytest.skip("reference stock lists not present")
    import csv
    import config
    nifty = list(csv.DictReader(open(config.nifty50_list(), encoding="utf-8-sig")))
    assert len(nifty) == 50
    bad = []
    for row in nifty:
        for text in (row["Name"], row["NSE Code"], f"RSI of {row['NSE Code']}", f"news on {row['Name']}"):
            if real.check(text).blocked:
                bad.append(text)
    assert bad == []


def test_real_lists_catch_the_examples_from_the_screenshots():
    try:
        real = ig.load_default()
    except ig.InputGuardError:
        pytest.skip("reference stock lists not present")
    assert real.check("Analyze Adani GAS").blocked
    assert real.check("Create a portfolio of 10 stocks", portfolio=True).blocked
    assert not real.check("Analyze Infosys").blocked and not real.check("Compare TCS with Infosys").blocked


def test_real_lists_do_not_block_the_questions_already_in_the_router_tests():
    try:
        real = ig.load_default()
    except ig.InputGuardError:
        pytest.skip("reference stock lists not present")
    import re
    source = (Path(__file__).resolve().parent / "test_router.py").read_text(encoding="utf-8")
    questions = re.findall(r'^\s+\("([^"]{8,})", "[a-z]+"\)', source, re.M)
    assert len(questions) > 40
    blocked = [q for q in questions if real.check(q).blocked]
    # Wipro is not in this app's Nifty 50 list, so G1 is right to block it. The router tests only use it as a sample name.
    assert [q for q in blocked if "wipro" not in q.lower()] == [], blocked
    assert blocked, "the router tests name Wipro, so at least one question should be blocked"
