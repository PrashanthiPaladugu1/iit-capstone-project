"""Screener snapshot tools for the fundamental agent. Numbers are read from the screener DuckDB file (path key
`screener_duckdb`, built by screener_db.py from the Screener CSV snapshots). No model is involved.

Three tools sit on this class (see mcp_fundamentals.py, prefix `screener_`):
    get_table     many stocks side by side: choose the metrics, sort, filter by a number or an industry group
    get_snapshot  every metric of one stock
    get_history   one metric of one stock across the snapshot dates

Errors are raised as ScreenerError; the MCP wrapper turns them into text for the agent.

Banks, finance companies and insurers use the same CSV columns as industrial companies but the meaning differs, so for them
operating margin, gross margin, debt to equity and enterprise value are left blank (the same rule as fundamentals.py).
"""
from __future__ import annotations

import re

import screener_db
from fundamentals import FINANCIAL_WARNING, GROUP_TYPE

MAX_TABLE_ROWS = 50
MAX_HISTORY_ROWS = 200
NOT_METRICS = {"symbol", "snap_date", "snap_time", "source_file", "bse_code", "isin_code", "company_name"}
TEXT_METRICS = {"industry_group", "industry"}
# Not meaningful for banks, finance companies and insurers.
FINANCIAL_BLANKED = {"opm_latest_quarter", "opm_preceding_quarter", "opm_last_year", "gpm_latest_quarter",
                     "debt_to_equity", "enterprise_value"}
ALIASES = {
    "pe": "price_to_earning", "p_e": "price_to_earning", "price_to_earnings": "price_to_earning", "ttm_pe": "price_to_earning",
    "pb": "price_to_book_value", "p_b": "price_to_book_value", "price_to_book": "price_to_book_value",
    "opm": "opm_latest_quarter", "npm": "npm_latest_quarter", "gpm": "gpm_latest_quarter",
    "roce": "return_on_capital_employed", "de": "debt_to_equity", "d_e": "debt_to_equity",
    "market_cap": "market_capitalization", "mcap": "market_capitalization", "ev": "enterprise_value",
    "price": "current_price", "peg": "peg_ratio", "fii": "fii_holding", "dii": "dii_holding", "promoter": "promoter_holding",
    "public": "public_holding", "div_yield": "dividend_yield", "dma50": "dma_50", "dma200": "dma_200",
    "52w_high": "high_price_52w", "52w_low": "low_price_52w", "pat": "profit_after_tax",
    "industry_pe": "industry_pe", "sector": "industry_group",
}
CAVEAT = ("Screener snapshot, not live data: price, market cap, P/E, RSI and similar values are as of the snapshot date. "
          "Sales, profit and margins change only when results are published. Amounts look like crore rupees; Screener states no unit.")


class ScreenerError(ValueError):
    pass


def _key(name) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name or "").strip().lower()).strip("_")


def _clean(value):
    return None if value is None or (isinstance(value, float) and value != value) else value


class Screener:
    def __init__(self, con=None):
        self._con = con or screener_db.open_readonly()
        cols = [r[0] for r in self._con.execute("describe snapshots").fetchall()]
        self._metrics = [c for c in cols if c not in NOT_METRICS]
        self._numeric = [c for c in self._metrics if c not in TEXT_METRICS]

    # ------------------------------------------------------------------ helpers
    def _metric(self, name, *, numeric_only=False) -> str:
        key = _key(name)
        key = ALIASES.get(key, key)
        valid = self._numeric if numeric_only else self._metrics
        if key not in valid:
            raise ScreenerError(f"Unknown metric {name!r}. Valid names: {', '.join(valid)}. "
                                f"Short names also work: pe, pb, opm, npm, gpm, roce, de, ev, fii, dii, promoter, peg.")
        return key

    def _latest_rows(self) -> tuple[str, list[dict]]:
        """(date, one dict per stock) for the newest snapshot date."""
        day = self._con.execute("select max(snap_date) from snapshots").fetchone()[0]
        if day is None:
            raise ScreenerError("The screener database is empty. Rebuild it with bin/run_py.sh screener_db.py.")
        cur = self._con.execute("select * from snapshots where snap_date = ? order by symbol", [day])
        names = [d[0] for d in cur.description]
        rows = [dict(zip(names, (_clean(v) for v in r))) for r in cur.fetchall()]
        return str(day), rows

    @staticmethod
    def _kind(row) -> str:
        return GROUP_TYPE.get(row.get("industry_group") or "", "industrial")

    def _mask(self, row) -> dict:
        """The row's values, with the measures that do not apply to a bank, finance company or insurer set to None."""
        out = dict(row)
        if self._kind(row) != "industrial":
            for col in FINANCIAL_BLANKED:
                if col in out:
                    out[col] = None
        return out

    def _symbol(self, symbol: str) -> str:
        sym = (symbol or "").strip().upper()
        known = {r[0] for r in self._con.execute("select distinct symbol from snapshots").fetchall()}
        if sym not in known:
            raise ScreenerError(f"{symbol!r} is not one of the Nifty 50 stocks in the screener data.")
        return sym

    # ------------------------------------------------------------------ tools
    def get_table(self, metrics: list[str], sort_by: str | None = None, descending: bool = True, limit: int = MAX_TABLE_ROWS,
                  min_values: dict | None = None, max_values: dict | None = None, industry_group: str | None = None) -> dict:
        if not metrics:
            raise ScreenerError("Give at least one metric, for example [\"pe\", \"rsi\", \"opm\", \"npm\"].")
        if limit is None or int(limit) < 1:
            raise ScreenerError("limit must be 1 or more.")
        limit = min(int(limit), MAX_TABLE_ROWS)
        columns = [self._metric(m) for m in metrics]
        sort_col = self._metric(sort_by, numeric_only=True) if sort_by else None
        lows = {self._metric(k, numeric_only=True): float(v) for k, v in (min_values or {}).items()}
        highs = {self._metric(k, numeric_only=True): float(v) for k, v in (max_values or {}).items()}

        as_of, raw = self._latest_rows()
        rows = [self._mask(r) for r in raw]
        if industry_group:
            groups = sorted({r["industry_group"] for r in rows if r.get("industry_group")})
            wanted = _key(industry_group)
            match = [g for g in groups if _key(g) == wanted]
            if not match:
                raise ScreenerError(f"No industry group matches {industry_group!r}. Groups: {', '.join(groups)}.")
            rows = [r for r in rows if r.get("industry_group") == match[0]]
        for col, low in lows.items():
            rows = [r for r in rows if r[col] is not None and r[col] >= low]
        for col, high in highs.items():
            rows = [r for r in rows if r[col] is not None and r[col] <= high]
        if sort_col:
            have = sorted((r for r in rows if r[sort_col] is not None), key=lambda r: r[sort_col], reverse=bool(descending))
            rows = have + [r for r in rows if r[sort_col] is None]            # a missing value is last either way
        matched = len(rows)
        rows = rows[:limit]

        blanked = sorted(r["symbol"] for r in rows if self._kind(r) != "industrial" and FINANCIAL_BLANKED & set(columns))
        note = (f"Left blank for {', '.join(blanked)} (banks, finance companies and insurers): operating margin, gross margin, "
                f"debt to equity and enterprise value mean something different for them.") if blanked else ""
        return {"as_of": as_of, "columns": ["symbol"] + columns, "rows": [[r["symbol"]] + [r[c] for c in columns] for r in rows],
                "count": len(rows), "matched": matched, "note": note, "caveat": CAVEAT}

    def get_snapshot(self, symbol: str) -> dict:
        sym = self._symbol(symbol)
        as_of, raw = self._latest_rows()
        row = next((r for r in raw if r["symbol"] == sym), None)
        if row is None:
            raise ScreenerError(f"{sym} has no row in the latest snapshot ({as_of}).")
        kind = self._kind(row)
        masked = self._mask(row)
        out = {"symbol": sym, "company_name": row.get("company_name"), "industry_group": row.get("industry_group"),
               "industry": row.get("industry"), "company_type": kind, "as_of": as_of,
               "values": {c: masked[c] for c in self._numeric}, "caveat": CAVEAT}
        if kind != "industrial":
            out["warning"] = FINANCIAL_WARNING.format(kind=kind)
        return out

    def get_history(self, symbol: str, metric: str, limit: int = 60) -> dict:
        sym = self._symbol(symbol)
        col = self._metric(metric, numeric_only=True)
        if limit is None or int(limit) < 1:
            raise ScreenerError("limit must be 1 or more.")
        limit = min(int(limit), MAX_HISTORY_ROWS)
        group = self._con.execute("select industry_group from snapshots where symbol = ? limit 1", [sym]).fetchone()[0]
        kind = GROUP_TYPE.get(group or "", "industrial")
        blank = kind != "industrial" and col in FINANCIAL_BLANKED
        data = self._con.execute(f"select snap_date, {col} from snapshots where symbol = ? order by snap_date desc limit ?",
                                 [sym, limit]).fetchall()
        rows = [[str(d), None if blank else _clean(v)] for d, v in reversed(data)]
        values = [v for _, v in rows if v is not None]
        out = {"symbol": sym, "metric": col, "rows": rows, "count": len(rows),
               "first": values[0] if values else None, "latest": values[-1] if values else None,
               "min": min(values) if values else None, "max": max(values) if values else None, "caveat": CAVEAT}
        if blank:
            out["warning"] = FINANCIAL_WARNING.format(kind=kind)
        return out
