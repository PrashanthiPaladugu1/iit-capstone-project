"""Market-data tools: plain functions that read prices and return JSON-safe dicts.

The MCP server (mcp_market_data.py) only wraps these functions. They are tested directly.
Every result carries the data date and the price caveat. Numbers come from DuckDB and pandas, never from a model.
Unknown symbols raise MarketDataError (guardrail G1 also checks this before the tools run).
"""
from __future__ import annotations

import csv
from datetime import date

import config
import indicators
import prices_db

CAVEAT = "Prices are not adjusted for splits, bonuses or demergers."
MAX_ROWS = 260


class MarketDataError(ValueError):
    pass


def nifty50_symbols() -> list[str]:
    """The 50 stocks, from the reference file named in config/paths.json."""
    with open(config.nifty50_list(), newline="", encoding="utf-8") as fh:
        return [r["NSE Code"].strip() for r in csv.DictReader(fh) if r.get("NSE Code", "").strip()]


def nifty50_table() -> list[dict]:
    """Symbol, company name, industry group and industry for the 50 stocks, from the reference file."""
    with open(config.nifty50_list(), newline="", encoding="utf-8") as fh:
        return [{"symbol": r["NSE Code"].strip(), "name": (r.get("Name") or "").strip(),
                 "industry_group": (r.get("Industry Group") or "").strip(), "industry": (r.get("Industry") or "").strip()}
                for r in csv.DictReader(fh) if r.get("NSE Code", "").strip()]


class MarketData:
    def __init__(self, con=None):
        self._con = con or prices_db.open_readonly()
        self._universe = None

    # ------------------------------------------------------------------ helpers
    def _symbol(self, symbol: str) -> str:
        sym = (symbol or "").strip().upper()
        if self._universe is None:
            self._universe = set(prices_db.symbols(self._con))
        if sym not in self._universe:
            raise MarketDataError(f"{symbol!r} is not one of the Nifty 50 stocks in the price data.")
        return sym

    def _hist(self, symbol: str, start=None, end=None):
        return prices_db.history(self._con, self._symbol(symbol), start, end)

    def _meta(self, df) -> dict:
        return {"as_of": str(df["date"].iloc[-1]), "caveat": CAVEAT}

    @staticmethod
    def _clean(value):
        return None if value is None or value != value else (round(float(value), 4) if isinstance(value, float) else value)

    # ------------------------------------------------------------------ tools
    def get_ohlcv(self, symbol: str, days: int = 30) -> dict:
        """Last `days` daily rows (open, high, low, close, volume, delivery %). At most 260."""
        days = max(1, min(int(days), MAX_ROWS))
        df = self._hist(symbol).tail(days)
        rows = [{"date": str(r.date), "open": r.open, "high": r.high, "low": r.low, "close": r.close,
                 "volume": int(r.volume), "delivery_pct": self._clean(r.delivery_pct)} for r in df.itertuples()]
        return {"symbol": symbol.upper(), "rows": rows, **self._meta(df)}

    def get_latest_quote(self, symbol: str) -> dict:
        df = self._hist(symbol)
        last = df.iloc[-1]
        change = (last["close"] / last["prev_close"] - 1) * 100 if last["prev_close"] else None
        return {"symbol": symbol.upper(), "date": str(last["date"]), "close": float(last["close"]),
                "prev_close": float(last["prev_close"]), "change_pct": self._clean(change),
                "volume": int(last["volume"]), "delivery_pct": self._clean(last["delivery_pct"]), **self._meta(df)}

    def get_returns(self, symbol: str) -> dict:
        df = self._hist(symbol)
        return {"symbol": symbol.upper(), "returns_pct": indicators.returns(df["close"]),
                "trading_days_available": int(len(df)), **self._meta(df)}

    def get_52w_high_low(self, symbol: str) -> dict:
        df = self._hist(symbol)
        hl = indicators.high_low_52w(df)
        close = float(df["close"].iloc[-1])
        hl["close"] = close
        hl["below_high_pct"] = round((close / hl["high"] - 1) * 100, 2)
        hl["above_low_pct"] = round((close / hl["low"] - 1) * 100, 2)
        if not hl["full_year"]:
            hl["note"] = f"Only {hl['days_used']} trading days of history, so this is not a full 52 weeks."
        return {"symbol": symbol.upper(), **hl, **self._meta(df)}

    def get_delivery_pct(self, symbol: str, days: int = 20) -> dict:
        df = self._hist(symbol).tail(max(1, min(int(days), MAX_ROWS)))
        series = df["delivery_pct"].dropna()
        return {"symbol": symbol.upper(), "days": int(len(df)),
                "average_delivery_pct": self._clean(float(series.mean())) if len(series) else None,
                "latest_delivery_pct": self._clean(float(series.iloc[-1])) if len(series) else None, **self._meta(df)}

    def get_indicators(self, symbol: str) -> dict:
        df = self._hist(symbol)
        result = indicators.latest_indicators(df)
        short = [k for k in ("sma_50", "sma_200") if result[k] is None]
        out = {"symbol": symbol.upper(), "indicators": result, **self._meta(df)}
        if short:
            out["note"] = f"Not enough history for {', '.join(short)} ({len(df)} trading days)."
        return out

    def compare_stocks(self, symbols: list[str]) -> dict:
        if not 2 <= len(symbols) <= 6:
            raise MarketDataError("compare 2 to 6 stocks")
        rows = []
        for s in dict.fromkeys(x.upper() for x in symbols):
            df = self._hist(s)
            r = indicators.returns(df["close"])
            hl = indicators.high_low_52w(df)
            rows.append({"symbol": s, "close": float(df["close"].iloc[-1]), "return_1m_pct": r["1M"],
                         "return_3m_pct": r["3M"], "return_1y_pct": r["1Y"],
                         "rsi_14": self._clean(indicators.rsi(df["close"]).iloc[-1]),
                         "below_52w_high_pct": round((float(df["close"].iloc[-1]) / hl["high"] - 1) * 100, 2),
                         "trading_days": int(len(df))})
        return {"rows": rows, "as_of": str(self._hist(rows[0]["symbol"])["date"].iloc[-1]), "caveat": CAVEAT}

    def top_movers(self, period: str = "1M", n: int = 5) -> dict:
        """Best and worst `n` stocks by return over 1D, 1W, 1M, 3M, 6M or 1Y. Stocks with too little history are skipped."""
        lookback = {"1D": 1, "1W": 5, "1M": 21, "3M": 63, "6M": 126, "1Y": 252}
        period = period.upper()
        if period not in lookback:
            raise MarketDataError(f"period must be one of {', '.join(lookback)}")
        n = max(1, min(int(n), 10))
        ranked, skipped = [], []
        for s in sorted(self._con.execute("SELECT DISTINCT symbol FROM prices").fetchall()):
            sym = s[0]
            close = self._hist(sym)["close"]
            if len(close) <= lookback[period]:
                skipped.append(sym)
                continue
            ranked.append((sym, float((close.iloc[-1] / close.iloc[-1 - lookback[period]] - 1) * 100)))
        ranked.sort(key=lambda x: x[1], reverse=True)
        fmt = lambda items: [{"symbol": a, "return_pct": round(b, 2)} for a, b in items]  # noqa: E731
        info = prices_db.data_dates(self._con)
        return {"period": period, "best": fmt(ranked[:n]), "worst": fmt(ranked[-n:][::-1]),
                "skipped_short_history": skipped, "as_of": str(info["last_date"]), "caveat": CAVEAT}

    def list_stocks(self) -> dict:
        """Every stock the app covers (those with price data), with company name and industry group."""
        have = set(prices_db.symbols(self._con))
        rows = [r for r in nifty50_table() if r["symbol"] in have]
        return {"count": len(rows), "stocks": rows, "as_of": str(prices_db.data_dates(self._con)["last_date"]),
                "caveat": CAVEAT}

    def data_status(self) -> dict:
        info = prices_db.data_dates(self._con)
        return {"first_date": str(info["first_date"]), "last_date": str(info["last_date"]), "rows": info["rows"],
                "symbols": info["symbols"], "duplicates_removed": info["duplicates_removed"],
                "built_at": info["built_at"], "caveat": CAVEAT}
