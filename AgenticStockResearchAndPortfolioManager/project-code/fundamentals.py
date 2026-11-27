"""Financial statement tools for the fundamental agent. All numbers and ratios are computed here, in code.

Reads the fundamentals DuckDB file (path key `fundamentals_duckdb`), built by fundamentals_db.py from the Screener workbooks. No model is involved.
Errors are raised as FundamentalsError; the MCP wrapper (mcp_fundamentals.py) turns them into text for the agent.

Banks, finance companies and insurers use the same row labels as industrial companies but the lines mean something
else (Sales is total income, Interest is an expense of the business, Borrowings include deposits). For them the
industrial measures (operating margin, interest cover, debt to equity, EV to sales) are NOT computed.
"""
from __future__ import annotations

import fundamentals_db as fdb
from market_data import nifty50_symbols, nifty50_table

SECTIONS = ("profit_loss", "quarters", "balance_sheet", "cash_flow", "derived", "price")
UNIT_NOTE = ("Values are as in the source workbook. The workbook states no unit; they look like crore rupees "
             "(1 crore = 10 million). Do not state a unit with certainty.")
GROUP_TYPE = {"Banks": "bank", "Finance": "finance", "Insurance": "insurance"}
FINANCIAL_WARNING = ("This is a {kind}. Its statement lines mean something different from an industrial company's "
                     "(Sales is total income, Interest is a cost of the business, Borrowings include deposits), so "
                     "operating margin, interest cover, debt to equity and EV to sales are not computed.")


class FundamentalsError(ValueError):
    pass


def cagr(start, end, years):
    """Compound annual growth in percent, or None when it is not defined (start not positive, end negative, no years)."""
    if start is None or end is None or years is None or years <= 0 or start <= 0 or end < 0:
        return None
    return ((end / start) ** (1.0 / years) - 1.0) * 100.0


def _r(value, digits=4):
    return None if value is None else round(float(value), digits)


def _div(a, b):
    return None if a is None or b in (None, 0) else a / b


class Fundamentals:
    def __init__(self, con=None):
        self._con = con or fdb.open_readonly()
        self._groups = {r["symbol"]: r["industry_group"] for r in nifty50_table()}
        self._have = {r[0] for r in self._con.execute("select symbol from fin_meta").fetchall()}

    # ------------------------------------------------------------------ helpers
    def company_type(self, symbol: str) -> str:
        return GROUP_TYPE.get(self._groups.get(symbol.upper(), ""), "industrial")

    def _symbol(self, symbol: str) -> str:
        sym = (symbol or "").strip().upper()
        if sym not in nifty50_symbols():
            raise FundamentalsError(f"{symbol!r} is not one of the Nifty 50 stocks.")
        if sym not in self._have:
            raise FundamentalsError(f"There is no financial workbook for {sym}, so no statement data is available.")
        return sym

    def _series(self, sym: str, section: str, label: str) -> dict:
        rows = self._con.execute(
            "select cast(period_end as varchar), value from fin_values where symbol=? and section=? and label=? "
            "order by period_end", [sym, section, label]).fetchall()
        return {d: v for d, v in rows}

    def _labels(self, sym: str, section: str) -> list[str]:
        return [r[0] for r in self._con.execute(
            "select distinct label from fin_values where symbol=? and section=? order by label", [sym, section]).fetchall()]

    def _meta(self, sym: str) -> dict:
        return {"caveat": UNIT_NOTE, "company_type": self.company_type(sym)}

    # ------------------------------------------------------------------ tools
    def coverage(self) -> dict:
        everyone = nifty50_symbols()
        return {"with_workbook": len(self._have & set(everyone)),
                "without_workbook": sorted(s for s in everyone if s not in self._have),
                "note": "Stocks without a workbook have no statement data. Say so; do not guess."}

    def list_line_items(self, symbol: str) -> dict:
        sym = self._symbol(symbol)
        out = {sec: self._labels(sym, sec) for sec in SECTIONS}
        return {"symbol": sym, **out, "unit_note": UNIT_NOTE}

    def get_financials(self, symbol: str, section: str, labels: list[str] | None = None, periods: int = 5) -> dict:
        sym = self._symbol(symbol)
        if section not in SECTIONS:
            raise FundamentalsError(f"unknown section {section!r}; use one of {', '.join(SECTIONS)}")
        known = self._labels(sym, section)
        wanted = list(labels) if labels else known
        bad = [x for x in wanted if x not in known]
        if bad:
            raise FundamentalsError(f"unknown label {bad}; labels in {section} are: {', '.join(known)}")
        periods = max(1, min(int(periods), 40))
        rows = []
        for label in wanted:
            for day, value in list(self._series(sym, section, label).items())[-periods:]:
                rows.append({"label": label, "period_end": day, "value": _r(value, 4)})
        return {"symbol": sym, "section": section, "rows": rows, "unit_note": UNIT_NOTE, **self._meta(sym)}

    def get_quarterly(self, symbol: str, quarters: int = 4) -> dict:
        sym = self._symbol(symbol)
        quarters = max(1, min(int(quarters), 40))
        by_day: dict[str, dict] = {}
        for label in self._labels(sym, "quarters"):
            for day, value in self._series(sym, "quarters", label).items():
                by_day.setdefault(day, {"period_end": day})[label] = _r(value, 4)
        rows = [by_day[d] for d in sorted(by_day)][-quarters:]
        return {"symbol": sym, "rows": rows, "unit_note": UNIT_NOTE, **self._meta(sym)}

    def compute_growth(self, symbol: str, label: str, years: int = 1, section: str = "profit_loss") -> dict:
        sym = self._symbol(symbol)
        if section not in ("profit_loss", "balance_sheet", "cash_flow"):
            raise FundamentalsError("growth is computed on annual sections: profit_loss, balance_sheet, cash_flow")
        series = self._series(sym, section, label)
        if not series:
            raise FundamentalsError(f"unknown label {label!r}; labels in {section} are: {', '.join(self._labels(sym, section))}")
        years = max(1, min(int(years), 15))
        days = sorted(series)
        rows = []
        for i in range(years, len(days)):
            start, end = series[days[i - years]], series[days[i]]
            rows.append({"period_end": days[i], "value": _r(end), "value_before": _r(start),
                         "growth_pct": _r(_div(end - start, abs(start)) * 100 if _div(end - start, abs(start)) is not None else None)})
        out = {"symbol": sym, "label": label, "section": section, "years": years, "rows": rows, **self._meta(sym)}
        used = min(years, len(days) - 1)
        if used >= 1:
            start, end = series[days[-1 - used]], series[days[-1]]
            out.update({"start_period": days[-1 - used], "end_period": days[-1], "start_value": _r(start),
                        "end_value": _r(end), "years_used": used, "cagr_pct": _r(cagr(start, end, used))})
            if out["cagr_pct"] is None:
                out["cagr_note"] = "CAGR is not defined because the starting value is zero or negative."
        return out

    def compute_ratios(self, symbol: str, periods: int = 5) -> dict:
        sym = self._symbol(symbol)
        kind = self.company_type(sym)
        pl = {k: self._series(sym, "profit_loss", k) for k in
              ("Sales", "Net profit", "Profit before tax", "Interest", "Depreciation", "Other Income")}
        bs = {k: self._series(sym, "balance_sheet", k) for k in
              ("Equity Share Capital", "Reserves", "Borrowings", "Total assets", "Cash & Bank")}
        days = sorted(pl["Net profit"])[-max(1, min(int(periods), 15)):]
        rows = []
        for d in days:
            equity = (bs["Equity Share Capital"].get(d) or 0) + (bs["Reserves"].get(d) or 0)
            sales, profit = pl["Sales"].get(d), pl["Net profit"].get(d)
            row = {"period_end": d,
                   "net_margin_pct": _r(_pct(profit, sales)),
                   "roe_pct": _r(_pct(profit, equity or None)),
                   "roa_pct": _r(_pct(profit, bs["Total assets"].get(d)))}
            if kind == "industrial":
                pbt, interest, dep, other = (pl["Profit before tax"].get(d), pl["Interest"].get(d) or 0.0,
                                             pl["Depreciation"].get(d) or 0.0, pl["Other Income"].get(d) or 0.0)
                operating = None if pbt is None else pbt + dep + interest - other      # exact in all 49 workbooks (checked on TCS)
                row["operating_margin_pct"] = _r(_pct(operating, sales))
                row["interest_cover"] = _r(_div(None if pbt is None else pbt + interest, interest or None))
                row["debt_to_equity"] = _r(_div(bs["Borrowings"].get(d) or 0.0, equity or None))
            rows.append(row)
        out = {"symbol": sym, "company_type": kind, "ratios": rows, "caveat": UNIT_NOTE,
               "definitions": "ROE = net profit / (share capital + reserves) at year end; ROA = net profit / total assets; "
                              "operating margin = (profit before tax + depreciation + interest - other income) / sales."}
        if kind != "industrial":
            out["warning"] = FINANCIAL_WARNING.format(kind=kind)
        return out

    def get_valuation(self, symbol: str) -> dict:
        sym = self._symbol(symbol)
        kind = self.company_type(sym)
        meta = self._con.execute(
            "select company_name, current_price, market_cap, source_file from fin_meta where symbol=?", [sym]).fetchone()
        name, price, cap, source = meta
        profit = self._series(sym, "profit_loss", "Net profit")
        last = sorted(profit)[-1]
        equity = ((self._series(sym, "balance_sheet", "Equity Share Capital").get(last) or 0)
                  + (self._series(sym, "balance_sheet", "Reserves").get(last) or 0))
        out = {"symbol": sym, "company_name": name, "current_price": price, "market_cap": cap,
               "as_of_financials": last, "net_profit": _r(profit[last]),
               "pe": _r(_div(cap, profit[last]) if profit[last] and profit[last] > 0 else None),
               "price_to_book": _r(_div(cap, equity or None)),
               "dividend_yield_pct": _r(_pct(self._series(sym, "profit_loss", "Dividend Amount").get(last), cap)),
               "company_type": kind,
               "caveat": "Price and market cap come from the workbook (the date it was downloaded), not from the price "
                         "database. " + UNIT_NOTE}
        if kind == "industrial":
            sales = self._series(sym, "profit_loss", "Sales").get(last)
            debt = self._series(sym, "balance_sheet", "Borrowings").get(last) or 0.0
            cash = self._series(sym, "balance_sheet", "Cash & Bank").get(last) or 0.0
            out["ev_to_sales"] = _r(_div((cap or 0) + debt - cash, sales))
        else:
            out["warning"] = FINANCIAL_WARNING.format(kind=kind)
        return out


def _pct(a, b):
    return None if a is None or b in (None, 0) else a / b * 100.0
