"""guardrails: plain-code checks on a portfolio before any number is shown (G1 to G7; G8 is budget.py).

    out = check_portfolio(["TCS", "INFY", "ITC", "LT"], weights={"TCS": 25, ...}, universe=nifty, groups=groups,
                          history_days={"TCS": 1147, ...})
    out -> {"ok": bool, "blocks": [...], "warnings": [...]}      ok is False when anything blocks

G1 Nifty 50 only (block)          G5 more than half in one industry group (warn)
G2 seven or more stocks (block)   G6 under one year of prices (warn)
G3 fewer than four (block)        G7 disclaimer, data date and the unadjusted-price note (footer)
G4 weights sum to 100 and each is 5 to 40 (block)

No model is involved, so a guardrail cannot be talked out of a rule.
"""
from __future__ import annotations

MIN_STOCKS, MAX_STOCKS = 4, 6
MIN_WEIGHT, MAX_WEIGHT = 5.0, 40.0
GROUP_LIMIT_PCT = 50.0
FULL_YEAR_DAYS = 252                 # trading days; TMPV has 260, so it is not warned
SUM_TOLERANCE = 0.05                 # percentage points

DISCLAIMER = ("This is not investment advice. It is a description of past price and Screener data, not a forecast "
              "and not a recommendation to buy or sell.")


def footer(prices_as_of: str | None) -> str:
    """G7: added to every portfolio answer by the tools, so the model cannot leave it out."""
    return (f"{DISCLAIMER} Price data to {prices_as_of or 'an unknown date'}. "
            f"Prices are not adjusted for splits, bonuses or demergers.")


def check_portfolio(symbols: list[str], weights: dict[str, float] | None = None, *, universe: set[str],
                    groups: dict[str, str], history_days: dict[str, int]) -> dict:
    blocks: list[str] = []
    warnings: list[str] = []
    names = [str(s).strip().upper() for s in symbols]
    known = {u.upper() for u in universe}

    outside = [s for s in dict.fromkeys(names) if s not in known]
    if outside:
        blocks.append(f"G1: {', '.join(outside)} {'is' if len(outside) == 1 else 'are'} not in the Nifty 50. "
                      f"This app covers only the 50 Nifty 50 stocks.")
    repeated = sorted({s for s in names if names.count(s) > 1})
    if repeated:
        blocks.append(f"{', '.join(repeated)} appears twice in the list.")
    unique = list(dict.fromkeys(names))

    if len(unique) >= MAX_STOCKS + 1:
        blocks.append(f"G2: a portfolio holds {MIN_STOCKS} to {MAX_STOCKS} stocks. You gave {len(unique)}. "
                      f"Choose up to {MAX_STOCKS}.")
    elif len(unique) < MIN_STOCKS:
        blocks.append(f"G3: a portfolio needs at least {MIN_STOCKS} stocks. You gave {len(unique)}.")

    if weights is not None:
        given = {str(k).strip().upper(): float(v) for k, v in weights.items()}
        if set(given) != set(unique):
            blocks.append("G4: the weights must be given for exactly the stocks in the portfolio.")
        else:
            total = sum(given.values())
            if abs(total - 100.0) > SUM_TOLERANCE:
                blocks.append(f"G4: the weights add up to {total:g}%, not 100%.")
            high = sorted(s for s, w in given.items() if w > MAX_WEIGHT + 1e-9)
            low = sorted(s for s, w in given.items() if w < MIN_WEIGHT - 1e-9)
            if high:
                blocks.append(f"G4: {', '.join(high)} is above the {MAX_WEIGHT:g}% limit for one stock.")
            if low:
                blocks.append(f"G4: {', '.join(low)} is below the {MIN_WEIGHT:g}% minimum for one stock.")
        by_group: dict[str, float] = {}
        for s, w in given.items():
            if s in known:
                by_group[groups.get(s) or "unknown"] = by_group.get(groups.get(s) or "unknown", 0.0) + w
    else:
        share = 100.0 / len(unique) if unique else 0.0
        by_group = {}
        for s in unique:
            if s in known:
                by_group[groups.get(s) or "unknown"] = by_group.get(groups.get(s) or "unknown", 0.0) + share
    for group, pct in sorted(by_group.items(), key=lambda kv: -kv[1]):
        if pct > GROUP_LIMIT_PCT + 1e-9:
            warnings.append(f"G5: {pct:.0f}% of the portfolio is in one industry group ({group}). "
                            f"One group moves together, so this is less diversified than it looks.")

    short = [f"{s} ({history_days[s]} days)" for s in unique if s in history_days and history_days[s] < FULL_YEAR_DAYS]
    if short:
        warnings.append(f"G6: less than one year ({FULL_YEAR_DAYS} trading days) of prices for {', '.join(short)}. "
                        f"Risk and return figures for it are less reliable.")
    return {"ok": not blocks, "blocks": blocks, "warnings": warnings}
