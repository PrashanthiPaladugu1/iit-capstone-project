"""Technical indicators computed in Python (pandas), never by the model.

Each function takes a pandas Series (or a DataFrame with high, low, close) in date order and returns a
Series of the same length. Early rows with too little history are NaN.

Conventions (checked against hand calculation in tests/test_indicators.py):
  SMA        simple mean over `window` closes.
  EMA        pandas ewm(span=window, adjust=False), seeded with the first value.
  RSI        Wilder's method: average gain and loss start as the simple average of the first `window` changes,
             then smooth with (previous * (window - 1) + current) / window.
  MACD       EMA(fast) - EMA(slow); signal = EMA(MACD, signal); histogram = MACD - signal.
  Bollinger  SMA(window) +/- k * population standard deviation (ddof=0), the usual charting convention.
  ATR        Wilder's smoothing of the true range, seeded the same way.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _wilder(values: pd.Series, window: int) -> pd.Series:
    """Wilder's smoothing: the first output is the simple average of the first `window` valid values,
    then out[i] = (out[i-1] * (window - 1) + value[i]) / window. Earlier rows are NaN."""
    arr = values.to_numpy(dtype=float)
    out = np.full(len(arr), np.nan)
    valid = np.flatnonzero(~np.isnan(arr))
    if len(valid) < window:
        return pd.Series(out, index=values.index)
    start = valid[0] + window - 1
    out[start] = arr[valid[0]: start + 1].mean()
    for i in range(start + 1, len(arr)):
        out[i] = (out[i - 1] * (window - 1) + arr[i]) / window
    return pd.Series(out, index=values.index)


def sma(close: pd.Series, window: int = 20) -> pd.Series:
    return close.rolling(window, min_periods=window).mean()


def ema(close: pd.Series, window: int = 20) -> pd.Series:
    return close.ewm(span=window, adjust=False, min_periods=window).mean()


def rsi(close: pd.Series, window: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    gain[delta.isna()] = np.nan
    loss[delta.isna()] = np.nan
    avg_gain = _wilder(gain, window)
    avg_loss = _wilder(loss, window)
    rs = avg_gain / avg_loss
    out = 100 - 100 / (1 + rs)
    out[(avg_loss == 0) & (avg_gain > 0)] = 100.0          # no losses in the window
    out[(avg_loss == 0) & (avg_gain == 0)] = np.nan        # no movement: undefined
    return out


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = close.ewm(span=fast, adjust=False).mean() - close.ewm(span=slow, adjust=False).mean()
    line[: slow - 1] = np.nan
    sig = line.ewm(span=signal, adjust=False, ignore_na=True).mean()
    return pd.DataFrame({"macd": line, "signal": sig, "histogram": line - sig})


def bollinger(close: pd.Series, window: int = 20, k: float = 2.0) -> pd.DataFrame:
    mid = close.rolling(window, min_periods=window).mean()
    std = close.rolling(window, min_periods=window).std(ddof=0)       # population std, the usual charting convention
    return pd.DataFrame({"middle": mid, "upper": mid + k * std, "lower": mid - k * std})


def atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    true_range = pd.concat([df["high"] - df["low"], (df["high"] - prev_close).abs(),
                            (df["low"] - prev_close).abs()], axis=1).max(axis=1)
    true_range.iloc[0] = df["high"].iloc[0] - df["low"].iloc[0]
    return _wilder(true_range, window)


def returns(close: pd.Series, periods: dict[str, int] | None = None) -> dict[str, float | None]:
    """Percent return over trading-day lookbacks, for example {'1M': 21, '3M': 63, '1Y': 252}."""
    periods = periods or {"1D": 1, "1W": 5, "1M": 21, "3M": 63, "6M": 126, "1Y": 252}
    out: dict[str, float | None] = {}
    for label, n in periods.items():
        out[label] = round(float((close.iloc[-1] / close.iloc[-1 - n] - 1) * 100), 2) if len(close) > n else None
    return out


def high_low_52w(df: pd.DataFrame, days: int = 252) -> dict:
    window = df.tail(days)
    return {"high": float(window["high"].max()), "low": float(window["low"].min()),
            "days_used": int(len(window)), "full_year": len(window) >= days}


def latest_indicators(df: pd.DataFrame) -> dict:
    """Latest value of each indicator for one stock's history (date order)."""
    close = df["close"]
    m, b = macd(close), bollinger(close)
    last = lambda s: None if pd.isna(s.iloc[-1]) else round(float(s.iloc[-1]), 4)   # noqa: E731
    return {
        "date": str(df["date"].iloc[-1]), "close": float(close.iloc[-1]),
        "sma_20": last(sma(close, 20)), "sma_50": last(sma(close, 50)), "sma_200": last(sma(close, 200)),
        "ema_20": last(ema(close, 20)), "rsi_14": last(rsi(close, 14)),
        "macd": last(m["macd"]), "macd_signal": last(m["signal"]), "macd_histogram": last(m["histogram"]),
        "bollinger_upper": last(b["upper"]), "bollinger_lower": last(b["lower"]),
        "atr_14": last(atr(df, 14)),
    }
