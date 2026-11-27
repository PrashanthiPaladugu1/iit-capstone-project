"""scorecard: ranks the Nifty 50 on four factors, from price history and the Screener snapshot. No model is involved.

    card = Scorecard.default().score_all("low_risk")
    card -> {"strategy", "weights", "as_of": {"prices", "screener"}, "rows": [...best first...], "caveat"}

Every factor is a percentile among the 50 stocks (0 worst, 100 best). A missing input stays missing; it is never guessed.
    momentum   average of the 3 and 6 month price return                  (higher is better)
    quality    average rank of ROCE, profit growth and net profit margin  (higher is better; ROCE is not used for banks)
    valuation  P/E divided by the industry P/E                            (lower is better)
    risk       one-year volatility of daily returns                       (lower volatility scores higher)

A one-day move above 25% is treated as a split, bonus or demerger, because prices are not adjusted. That day is left out
of volatility, and any return window that contains it is left missing. The row says so in `flags`.
"""
from __future__ import annotations

import math

import pandas as pd

from fundamentals import GROUP_TYPE
from prices_db import JUMP_THRESHOLD

TRADING_DAYS = 252
WINDOW_3M, WINDOW_6M = 63, 126
MIN_VOL_OBSERVATIONS = 120
MIN_FACTORS = 2

STRATEGIES = {
    "balanced":   {"momentum": 0.25, "quality": 0.25, "valuation": 0.25, "risk": 0.25},
    "momentum":   {"momentum": 0.60, "quality": 0.20, "risk": 0.20},
    "low_risk":   {"risk": 0.60, "quality": 0.20, "valuation": 0.20},
    "quality":    {"quality": 0.60, "risk": 0.20, "valuation": 0.20},
    "value":      {"valuation": 0.60, "quality": 0.30, "risk": 0.10},
    "long_term":  {"quality": 0.40, "valuation": 0.30, "risk": 0.20, "momentum": 0.10},
    "short_term": {"momentum": 0.60, "risk": 0.20, "valuation": 0.20},
}
FACTORS = ("momentum", "quality", "valuation", "risk")
CAVEAT = ("Scores rank the 50 stocks against each other on past prices and the latest Screener snapshot. "
          "They are not a forecast and not investment advice.")


class ScorecardError(ValueError):
    pass


def percentile_ranks(values: dict, higher_is_better: bool = True) -> dict:
    """0 for the worst, 100 for the best, ties share the average rank, one value scores 50, None stays None."""
    have = {k: float(v) for k, v in values.items() if v is not None and not (isinstance(v, float) and math.isnan(v))}
    out: dict = {k: None for k in values}
    if not have:
        return out
    if len(have) == 1:
        out[next(iter(have))] = 50.0
        return out
    ordered = sorted(have.items(), key=lambda kv: kv[1], reverse=not higher_is_better)   # worst first
    i = 0
    while i < len(ordered):
        j = i
        while j + 1 < len(ordered) and ordered[j + 1][1] == ordered[i][1]:
            j += 1
        rank = (i + j) / 2.0                                                              # 0-based average rank
        for k in range(i, j + 1):
            out[ordered[k][0]] = rank / (len(ordered) - 1) * 100.0
        i = j + 1
    return out


def clean_returns(df: pd.DataFrame) -> tuple[pd.Series, int]:
    """(daily close-to-close returns with split-sized days set to NaN, the number of such days)."""
    returns = df["close"].astype(float).pct_change()
    jump = returns.abs() > JUMP_THRESHOLD
    return returns.mask(jump), int(jump.sum())


def _window_return(returns: pd.Series, days: int):
    """Compounded return over the last `days` returns, in percent. None if any day is missing or the history is short."""
    tail = returns.iloc[-days:]
    if len(tail) < days or tail.isna().any():
        return None
    return float(((1 + tail).prod() - 1) * 100)


def _round(value, places=2):
    return None if value is None else round(float(value), places)


class Scorecard:
    def __init__(self, history, table, stocks: list[dict]):
        self._history, self._table, self.stocks = history, table, stocks
        self._cache: dict = {}

    @classmethod
    def default(cls) -> "Scorecard":
        import prices_db
        from market_data import nifty50_table
        from screener import Screener
        con, screener = prices_db.open_readonly(), Screener()
        return cls(history=lambda s: prices_db.history(con, s),
                   table=lambda: screener.get_table(["pe", "industry_pe", "roce", "profit_growth", "npm"], limit=50),
                   stocks=nifty50_table())

    # ------------------------------------------------------------------ price history
    def history(self, symbol: str) -> pd.DataFrame:
        if symbol not in self._cache:
            self._cache[symbol] = self._history(symbol)
        return self._cache[symbol]

    def groups(self) -> dict[str, str]:
        return {s["symbol"]: s.get("industry_group") or "" for s in self.stocks}

    # ------------------------------------------------------------------ scoring
    def score_all(self, strategy: str = "balanced") -> dict:
        key = (strategy or "").strip().lower().replace("-", "_").replace(" ", "_")
        if key not in STRATEGIES:
            raise ScorecardError(f"Unknown strategy {strategy!r}. Valid strategies: {', '.join(STRATEGIES)}.")
        weights = STRATEGIES[key]
        table = self._table()
        cols = {c: i for i, c in enumerate(table["columns"])}
        screen = {r[0]: r for r in table["rows"]}

        facts: dict[str, dict] = {}
        for stock in self.stocks:
            sym = stock["symbol"]
            df = self.history(sym)
            returns, _ = clean_returns(df)
            returns = returns.iloc[1:]                                  # the first row has no return
            recent = returns.iloc[-TRADING_DAYS:]
            jumps_recent = int(recent.isna().sum())
            observed = recent.dropna()
            vol = float(observed.std() * math.sqrt(TRADING_DAYS) * 100) if len(observed) >= MIN_VOL_OBSERVATIONS else None
            r3, r6 = _window_return(returns, WINDOW_3M), _window_return(returns, WINDOW_6M)

            def pick(col):
                row = screen.get(sym)
                value = row[cols[col]] if row is not None and col in cols else None
                return None if value is None or (isinstance(value, float) and math.isnan(value)) else float(value)

            pe, ind_pe = pick("price_to_earning"), pick("industry_pe")
            vs_industry = pe / ind_pe if pe is not None and ind_pe is not None and pe > 0 and ind_pe > 0 else None
            roce = None if GROUP_TYPE.get(stock.get("industry_group") or "") else pick("return_on_capital_employed")
            flags = []
            if len(df) < TRADING_DAYS:
                flags.append(f"short price history ({len(df)} trading days)")
            if jumps_recent:
                flags.append(f"{jumps_recent} one-day price jump(s) above {JUMP_THRESHOLD:.0%} in the last year, "
                             f"probably a split, bonus or demerger; those days are left out and return windows that contain one are missing")
            facts[sym] = {"ret_3m": r3, "ret_6m": r6, "vol": vol, "pe": pe, "industry_pe": ind_pe, "vs_industry": vs_industry,
                          "roce": roce, "profit_growth": pick("profit_growth"), "npm": pick("npm_latest_quarter"), "flags": flags}

        syms = list(facts)
        momentum_raw = {s: (None if facts[s]["ret_3m"] is None or facts[s]["ret_6m"] is None
                            else (facts[s]["ret_3m"] + facts[s]["ret_6m"]) / 2) for s in syms}
        momentum = percentile_ranks(momentum_raw)
        risk = percentile_ranks({s: facts[s]["vol"] for s in syms}, higher_is_better=False)
        valuation = percentile_ranks({s: facts[s]["vs_industry"] for s in syms}, higher_is_better=False)
        parts = [percentile_ranks({s: facts[s][k] for s in syms}) for k in ("roce", "profit_growth", "npm")]
        quality = {}
        for s in syms:
            got = [p[s] for p in parts if p[s] is not None]
            quality[s] = sum(got) / len(got) if got else None

        rows = []
        for stock in self.stocks:
            s, f = stock["symbol"], facts[stock["symbol"]]
            scores = {"momentum": momentum[s], "quality": quality[s], "valuation": valuation[s], "risk": risk[s]}
            used = {k: w for k, w in weights.items() if scores[k] is not None}
            total = (sum(scores[k] * w for k, w in used.items()) / sum(used.values())) if len(used) >= MIN_FACTORS else None
            rows.append({"symbol": s, "name": stock.get("name", ""), "industry_group": stock.get("industry_group", ""),
                         "total": _round(total, 1), **{k: _round(v, 1) for k, v in scores.items()},
                         "inputs": {"ret_3m": _round(f["ret_3m"]), "ret_6m": _round(f["ret_6m"]), "vol_1y_pct": _round(f["vol"]),
                                    "pe": _round(f["pe"]), "industry_pe": _round(f["industry_pe"]),
                                    "pe_vs_industry": _round(f["vs_industry"]), "roce": _round(f["roce"]),
                                    "profit_growth": _round(f["profit_growth"]), "npm": _round(f["npm"])},
                         "flags": f["flags"]})
        rows.sort(key=lambda r: (r["total"] is None, -(r["total"] or 0), r["symbol"]))
        last = max((self.history(s["symbol"])["date"].max() for s in self.stocks), default=None)
        return {"strategy": key, "weights": weights, "as_of": {"prices": str(last) if last is not None else None,
                                                               "screener": table.get("as_of")},
                "rows": rows, "caveat": CAVEAT}
