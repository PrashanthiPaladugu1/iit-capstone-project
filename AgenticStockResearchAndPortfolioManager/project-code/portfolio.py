"""portfolio: picks 4 to 6 Nifty 50 stocks from the scorecard, sets weights, checks the guardrails and replays the past.

    tools = PortfolioTools.default()
    tools.suggest("low_risk", 5)                   one stock per industry group, best scorecard total first
    tools.build("low_risk", 5, "inverse_vol")      suggest + weights + guardrails + a buy-and-hold replay
    tools.evaluate(["TCS", "ITC", "LT", "HDFCBANK"], {"TCS": 25, ...}, 252)

All numbers are computed here in plain code. The same input gives the same list. Nothing here is a forecast.
"""
from __future__ import annotations

import math

import pandas as pd

import guardrails
from prices_db import JUMP_THRESHOLD
from scorecard import Scorecard, ScorecardError  # noqa: F401  (ScorecardError is re-exported for callers)

WEIGHTINGS = ("equal", "inverse_vol")
MIN_COMMON_DAYS = 60
MAX_SKIPPED_SHOWN = 10
CAVEAT = ("This replays the past with the chosen weights bought on the first day and held, with no trading costs or tax. "
          "It is not a forecast and not investment advice. Days with a one-day price move above 25% are treated as a split, "
          "bonus or demerger and counted as no change, because prices are not adjusted.")


class PortfolioError(ValueError):
    pass


# ------------------------------------------------------------------------------------------------ weights
def bound_weights(raw: dict[str, float]) -> dict[str, float]:
    """Scale to 100, then hold every weight inside the 5 to 40 limits. Raises when the limits cannot be met."""
    lo, hi, n = guardrails.MIN_WEIGHT, guardrails.MAX_WEIGHT, len(raw)
    if n == 0 or n * hi < 100 - 1e-9 or n * lo > 100 + 1e-9:
        raise PortfolioError(f"{n} stocks cannot be weighted between {lo:g}% and {hi:g}% and add up to 100%.")
    if any(v is None or v <= 0 or math.isnan(v) for v in raw.values()):
        raise PortfolioError("Every stock needs a positive weight input.")
    fixed: dict[str, float] = {}
    for _ in range(n + 1):
        free = {k: v for k, v in raw.items() if k not in fixed}
        if not free:
            break
        room = 100.0 - sum(fixed.values())
        scale = room / sum(free.values())
        proposal = {k: v * scale for k, v in free.items()}
        over = {k: p - hi for k, p in proposal.items() if p > hi + 1e-9}
        under = {k: lo - p for k, p in proposal.items() if p < lo - 1e-9}
        if not over and not under:
            fixed.update(proposal)
            break
        if sum(over.values()) >= sum(under.values()):
            fixed.update({k: hi for k in over})
        else:
            fixed.update({k: lo for k in under})
    out = {k: round(fixed[k], 2) for k in raw}
    drift = round(100.0 - sum(out.values()), 2)
    if drift:                                                            # put the rounding difference on a stock with room
        for k in sorted(out, key=lambda x: -out[x]):
            if lo <= out[k] + drift <= hi:
                out[k] = round(out[k] + drift, 2)
                break
    return out


def make_weights(method: str, symbols: list[str], vols: dict[str, float] | None = None) -> dict[str, float]:
    key = (method or "").strip().lower().replace("-", "_").replace(" ", "_")
    if key not in WEIGHTINGS:
        raise PortfolioError(f"Unknown weighting {method!r}. Valid weighting methods: {', '.join(WEIGHTINGS)}.")
    if key == "equal":
        return bound_weights({s: 1.0 for s in symbols})
    vols = vols or {}
    missing = [s for s in symbols if not vols.get(s)]
    if missing:
        raise PortfolioError(f"No volatility for {', '.join(missing)}, so inverse_vol weighting is not possible. Use equal.")
    return bound_weights({s: 1.0 / vols[s] for s in symbols})


# ------------------------------------------------------------------------------------------------ replay
def evaluate(histories: dict[str, pd.DataFrame], weights: dict[str, float], days: int = 252) -> dict:
    """Buy on the first day of the window, hold to the last. Jump days count as no change."""
    syms = list(weights)
    common = sorted(set.intersection(*[set(histories[s]["date"]) for s in syms]))
    if len(common) < MIN_COMMON_DAYS:
        raise PortfolioError(f"Only {len(common)} common trading days across these stocks; at least {MIN_COMMON_DAYS} are needed.")
    window = common[-max(int(days), 2):]
    index, jump_days, stock_rows = {}, {}, {}
    for s in syms:
        df = histories[s]
        close = df.set_index("date")["close"].astype(float).reindex(window)
        ret = close.pct_change().iloc[1:]
        jumps = int((ret.abs() > JUMP_THRESHOLD).sum())
        if jumps:
            jump_days[s] = jumps
        level = pd.concat([pd.Series([1.0]), (1 + ret.mask(ret.abs() > JUMP_THRESHOLD, 0.0)).cumprod()], ignore_index=True)
        index[s] = level
        stock_rows[s] = {"weight": weights[s], "return_pct": round(float(level.iloc[-1] - 1) * 100, 2)}
    value = sum(index[s] * (weights[s] / 100.0) for s in syms)
    drawdown = (value / value.cummax() - 1).min() * 100
    daily = value.pct_change().dropna()
    vol = float(daily.std() * math.sqrt(252) * 100) if len(daily) > 1 else None
    return {"window": {"start": str(window[0]), "end": str(window[-1]), "trading_days": len(window)},
            "total_return_pct": round(float(value.iloc[-1] - 1) * 100, 2),
            "max_drawdown_pct": round(float(drawdown), 2) + 0.0,
            "volatility_pct": None if vol is None else round(vol, 2),
            "stocks": stock_rows, "jump_days": jump_days, "caveat": CAVEAT}


# ------------------------------------------------------------------------------------------------ tools
class PortfolioTools:
    def __init__(self, scorecard: Scorecard):
        self.scorecard = scorecard
        self._known = {s["symbol"] for s in scorecard.stocks}

    @classmethod
    def default(cls) -> "PortfolioTools":
        return cls(Scorecard.default())

    # ------------------------------------------------------------------ helpers
    def _symbols(self, names, what) -> list[str]:
        out = [str(n).strip().upper() for n in (names or [])]
        bad = [n for n in out if n not in self._known]
        if bad:
            raise PortfolioError(f"{', '.join(bad)} is not one of the Nifty 50 ({what}). This app covers only those 50 stocks.")
        return out

    @staticmethod
    def _brief(row: dict) -> dict:
        return {"symbol": row["symbol"], "name": row["name"], "industry_group": row["industry_group"], "total": row["total"],
                "momentum": row["momentum"], "quality": row["quality"], "valuation": row["valuation"], "risk": row["risk"],
                "vol_1y_pct": row["inputs"]["vol_1y_pct"], "flags": row["flags"]}

    # ------------------------------------------------------------------ suggest
    def suggest(self, strategy: str = "balanced", size: int = 5, include=None, exclude=None) -> dict:
        try:
            size = int(size)
        except (TypeError, ValueError):
            raise PortfolioError("size must be a whole number from 4 to 6.") from None
        if not guardrails.MIN_STOCKS <= size <= guardrails.MAX_STOCKS:
            raise PortfolioError(f"A portfolio holds {guardrails.MIN_STOCKS} to {guardrails.MAX_STOCKS} stocks (4 to 6). "
                                 f"You asked for {size}.")
        include = list(dict.fromkeys(self._symbols(include, "include")))
        exclude = set(self._symbols(exclude, "exclude"))
        if len(include) > size:
            raise PortfolioError(f"{len(include)} stocks to include does not fit a portfolio of {size}.")
        clash = [s for s in include if s in exclude]
        if clash:
            raise PortfolioError(f"{', '.join(clash)} is in both include and exclude.")
        card = self.scorecard.score_all(strategy)
        rows = {r["symbol"]: r for r in card["rows"]}
        ranked = [r for r in card["rows"] if r["total"] is not None and r["symbol"] not in exclude]
        unscored = [s for s in include if rows[s]["total"] is None]
        if unscored:
            raise PortfolioError(f"{', '.join(unscored)} has too little data to score, so it cannot be included.")
        picks = {s: rows[s] for s in include}
        used = {r["industry_group"] for r in picks.values()}
        for r in ranked:
            if len(picks) >= size:
                break
            if r["symbol"] in picks or r["industry_group"] in used:
                continue
            picks[r["symbol"]] = r
            used.add(r["industry_group"])
        if len(picks) < size:
            raise PortfolioError(f"Only {len(picks)} industry groups have a scored stock after the exclusions; cannot pick {size}.")
        ordered = [r for r in card["rows"] if r["symbol"] in picks]
        by_group = {r["industry_group"]: r["symbol"] for r in ordered}
        skipped = [{"symbol": r["symbol"], "industry_group": r["industry_group"], "kept_instead": by_group[r["industry_group"]],
                    "total": r["total"]}
                   for r in ranked if r["symbol"] not in picks and r["industry_group"] in by_group][:MAX_SKIPPED_SHOWN]
        return {"strategy": card["strategy"], "size": size, "picks": [self._brief(r) for r in ordered],
                "skipped_same_group": skipped, "as_of": card["as_of"], "caveat": card["caveat"]}

    # ------------------------------------------------------------------ evaluate and build
    def _check_and_replay(self, symbols, weights, days, as_of_prices=None) -> dict:
        days_have = {}
        for s in symbols:
            if s in self._known:
                days_have[s] = len(self.scorecard.history(s))
        known = [s for s in symbols if s in self._known]
        check = guardrails.check_portfolio(symbols, weights, universe=self._known, groups=self.scorecard.groups(),
                                           history_days=days_have)
        backtest = None
        if check["ok"]:
            used = weights or make_weights("equal", symbols)
            backtest = evaluate({s: self.scorecard.history(s) for s in known}, used, days)
        last = max((self.scorecard.history(s)["date"].max() for s in known), default=None)
        return {"guardrails": check, "backtest": backtest, "prices_as_of": str(last) if last is not None else as_of_prices}

    def evaluate(self, symbols: list[str], weights: dict | None = None, days: int = 252) -> dict:
        names = [str(s).strip().upper() for s in (symbols or [])]
        weights = {str(k).strip().upper(): float(v) for k, v in weights.items()} if weights else None
        out = self._check_and_replay(names, weights, days)
        used = weights or (make_weights("equal", names) if out["guardrails"]["ok"] else None)
        return {"symbols": names, "weights": used, "guardrails": out["guardrails"], "backtest": out["backtest"],
                "as_of": {"prices": out["prices_as_of"]}, "footer": guardrails.footer(out["prices_as_of"])}

    def build(self, strategy: str = "balanced", size: int = 5, weighting: str = "equal", include=None, exclude=None,
              days: int = 252) -> dict:
        chosen = self.suggest(strategy, size, include, exclude)
        symbols = [p["symbol"] for p in chosen["picks"]]
        weights = make_weights(weighting, symbols, {p["symbol"]: p["vol_1y_pct"] for p in chosen["picks"]})
        out = self._check_and_replay(symbols, weights, days, chosen["as_of"]["prices"])
        return {"strategy": chosen["strategy"], "weighting": weighting, "picks": chosen["picks"], "weights": weights,
                "skipped_same_group": chosen["skipped_same_group"], "guardrails": out["guardrails"],
                "backtest": out["backtest"], "as_of": chosen["as_of"], "footer": guardrails.footer(out["prices_as_of"])}
