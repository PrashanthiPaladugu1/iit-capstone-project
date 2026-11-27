"""Indicators checked against values worked out by hand."""
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import indicators as ind  # noqa: E402


def test_sma_hand_values():
    s = pd.Series([1, 2, 3, 4, 5, 6], dtype=float)
    out = ind.sma(s, 3)
    assert out.isna().tolist() == [True, True, False, False, False, False]
    assert out.tolist()[2:] == [2.0, 3.0, 4.0, 5.0]


def test_ema_hand_values():
    # span 3 -> alpha 0.5, seeded with the first value: 1, 1.5, 2.25, 3.125
    out = ind.ema(pd.Series([1, 2, 3, 4], dtype=float), 3)
    assert out.isna().tolist() == [True, True, False, False]
    assert out.iloc[2] == pytest.approx(2.25) and out.iloc[3] == pytest.approx(3.125)


def test_rsi_all_gains_is_100_and_all_losses_is_0_and_flat_is_nan():
    up = ind.rsi(pd.Series(np.arange(1, 40, dtype=float)), 14)
    down = ind.rsi(pd.Series(np.arange(40, 1, -1, dtype=float)), 14)
    flat = ind.rsi(pd.Series([5.0] * 40), 14)
    assert up.iloc[-1] == 100.0 and down.iloc[-1] == pytest.approx(0.0)
    assert math.isnan(flat.iloc[-1])


def test_rsi_wilder_reference_value():
    # Wilder's own method: seed = simple average of the first 14 changes, then smooth. Worked out with plain loops.
    close = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28,
             46.28, 46.00, 46.03, 46.41, 46.22, 45.64]
    diffs = [b - a for a, b in zip(close, close[1:])]
    gains = [max(d, 0) for d in diffs]
    losses = [max(-d, 0) for d in diffs]
    ag, al = sum(gains[:14]) / 14, sum(losses[:14]) / 14
    expected = [100 - 100 / (1 + ag / al)]
    for g, l in zip(gains[14:], losses[14:]):
        ag, al = (ag * 13 + g) / 14, (al * 13 + l) / 14
        expected.append(100 - 100 / (1 + ag / al))
    out = ind.rsi(pd.Series(close), 14)
    assert out.iloc[:14].isna().all()
    assert out.iloc[14:].tolist() == pytest.approx(expected)


def test_macd_line_signal_histogram_relationship():
    close = pd.Series(np.linspace(100, 140, 80) + np.sin(np.arange(80)))
    m = ind.macd(close)
    assert m["macd"].iloc[:25].isna().all() and not math.isnan(m["macd"].iloc[25])
    manual = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    assert m["macd"].iloc[-1] == pytest.approx(manual.iloc[-1])
    assert (m["histogram"] - (m["macd"] - m["signal"])).abs().max() < 1e-12


def test_bollinger_hand_values():
    s = pd.Series([2, 4, 4, 4, 5, 5, 7, 9], dtype=float)          # mean 5, population std 2
    b = ind.bollinger(s, 8, 2.0)
    assert b["middle"].iloc[-1] == pytest.approx(5.0)
    assert b["upper"].iloc[-1] == pytest.approx(9.0) and b["lower"].iloc[-1] == pytest.approx(1.0)


def test_atr_wilder_hand_values():
    df = pd.DataFrame({"high": [12.0, 13.0, 14.0, 15.0], "low": [10.0, 11.0, 12.0, 13.0], "close": [11.0, 12.0, 13.0, 14.0]})
    # true ranges: 2, 2, 2, 2 -> window 3: seed at index 2 = 2.0, next = (2*2 + 2)/3 = 2.0
    out = ind.atr(df, 3)
    assert out.isna().tolist() == [True, True, False, False] and out.iloc[3] == pytest.approx(2.0)
    spike = pd.DataFrame({"high": [12.0, 12.0, 12.0, 20.0], "low": [10.0, 10.0, 10.0, 10.0], "close": [11.0] * 4})
    # true ranges 2, 2, 2, 10 -> seed 2.0, then (2*2 + 10)/3
    assert ind.atr(spike, 3).iloc[3] == pytest.approx(14 / 3)


def test_atr_constant_range():
    df = pd.DataFrame({"high": [11.0] * 30, "low": [9.0] * 30, "close": [10.0] * 30})
    assert ind.atr(df, 14).iloc[-1] == pytest.approx(2.0)


def test_returns_and_short_history():
    close = pd.Series([100.0, 110.0, 121.0])
    r = ind.returns(close, {"1D": 1, "2D": 2, "1Y": 252})
    assert r == {"1D": 10.0, "2D": 21.0, "1Y": None}


def test_52w_high_low_and_full_year_flag():
    df = pd.DataFrame({"high": [10, 50, 20], "low": [5, 8, 1]})
    r = ind.high_low_52w(df, 252)
    assert (r["high"], r["low"], r["days_used"], r["full_year"]) == (50.0, 1.0, 3, False)
