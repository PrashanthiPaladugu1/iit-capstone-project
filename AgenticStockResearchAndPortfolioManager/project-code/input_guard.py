"""input_guard: built-in checks on the QUESTION TEXT, in plain code, before any router, agent or model runs.

    guard = load_default()
    result = guard.check("Create a portfolio of 10 stocks", portfolio=True)
    result.blocked  -> True        result.alerts -> ["G2: ..."]        result.blocks -> [{"id": "G2", "text": ..., "count": 10}]

G1  a stock outside the Nifty 50 is named              (block)
G2  a portfolio question asks for more than 6 stocks    (block)
G3  a portfolio question asks for fewer than 4 stocks   (block)

Why here and not only in the tools: a tool check sees what the model passes. The model can change "10" to "5" or drop a
stock before any tool runs. Only this layer sees the user's exact words.

A block stops the question. Carrying on would answer a different question from the one the user asked.

No model is involved, so a guardrail cannot be talked out of a rule. The checks refuse only on a confident match,
because a wrong refusal is also a failure:
- Nifty 50 names, aliases and codes are removed from the text first, so "Tata Motors" (TMPV here) is never blocked.
- A stock code counts only when typed in capitals and at least 4 characters long (APOLLO, FORTIS and BRITANNIA are
  also ordinary words).
- A single-word company name counts only at 4 or more characters and when it is not an everyday word (AMBIGUOUS).
- A multi-word name counts as a whole phrase, longest first.
Not caught: a misspelt name, a 3-letter code, a name only written in short form in the list ("Adani Enterp.").
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from guardrails import MAX_STOCKS, MIN_STOCKS

ALERT_ID_NAMES, ALERT_ID_SIZE = "G1", "G2/G3"

# Single-word company names that are also everyday words. Matching them would refuse ordinary questions.
AMBIGUOUS = frozenset({
    "airan", "alembic", "antarctica", "astral", "bosch", "cupid", "ethos", "falcon", "gee", "glottis", "ist", "mazda",
    "midwest", "moil", "nile", "omnipotent", "premier", "raymond", "sis", "skipper", "symphony", "take", "til",
    "trident", "ucal"})

# Words that look like a stock code or name but are market words, so they never count as a stock.
MARKET_WORDS = frozenset({"nifty", "sensex", "ndtv", "niit", "nse", "bse", "etf", "ipo", "ebitda", "macd", "news",
                          "bank", "gold", "cash", "data", "risk", "total", "retail", "global", "current", "focus",
                          "trust", "wealth", "service", "master", "star", "idea", "deep", "fact", "race", "rain"})

# Stocks the user may ask about that the lists do not carry under the name people use.
HAND_NAMES = {"tesla": "Tesla", "microsoft": "Microsoft", "amazon": "Amazon", "nvidia": "Nvidia", "netflix": "Netflix",
              "google": "Google", "alphabet": "Alphabet", "adani gas": "Adani Gas", "paytm": "Paytm",
              "britannia": "Britannia"}
HAND_CODES = {"ADANIGAS": "ADANIGAS"}

_NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
                 "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "fifty": 50}
_STOCK_WORDS = frozenset({"stock", "stocks", "share", "shares", "company", "companies", "equity", "equities", "scrip",
                          "scrips"})
_BREAKERS = frozenset({"portfolio", "portfolios", "idea", "ideas", "option", "options", "sector", "sectors", "of", "from",
                       "in", "out", "with", "for", "and", "or", "to", "by", "at", "the", "nifty"})
_MAX_FILLER = 3
_MAX_NAME_WORDS = 8


class InputGuardError(RuntimeError):
    pass


@dataclass
class InputResult:
    blocks: list[dict] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return bool(self.blocks)

    @property
    def alerts(self) -> list[str]:
        return [b["text"] for b in self.blocks]


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _edge(words: list[str], flags: int):
    words = sorted({w for w in words if w}, key=len, reverse=True)
    if not words:
        return None
    return re.compile(r"(?<![A-Za-z0-9])(?:" + "|".join(re.escape(w) for w in words) + r")(?![A-Za-z0-9])", flags)


class InputGuard:
    CHECKS = ("G1 stock names", "G2/G3 portfolio size")

    def __init__(self, nifty_rows: list[dict], all_rows: list[dict], aliases: dict):
        nifty_codes = {(r.get("NSE Code") or "").strip() for r in nifty_rows} - {""}
        names = [(r.get("Name") or "").strip() for r in nifty_rows]
        exact = list(nifty_codes)
        for alias_names, alias_exact, _drop in aliases.values():
            names += list(alias_names)
            exact += list(alias_exact)
        self._mask_names = _edge(names, re.I)
        self._mask_exact = _edge(exact, 0)
        self._names: dict[str, str] = {}
        self._codes: dict[str, str] = {}
        for row in all_rows:
            name, code = (row.get("Name") or "").strip(), (row.get("NSE Code") or "").strip()
            if code and code not in nifty_codes and len(code) >= 4 and code == code.upper() \
                    and code.lower() not in MARKET_WORDS:
                self._codes[code] = code
            key = _norm(name)
            if not key or code in nifty_codes:
                continue
            words = key.split()
            if len(words) == 1 and (len(key) < 4 or key in AMBIGUOUS or key in MARKET_WORDS):
                continue
            self._names.setdefault(key, name)
        for key, shown in HAND_NAMES.items():
            self._names[key] = shown
        self._codes.update(HAND_CODES)
        self._longest = min(_MAX_NAME_WORDS, max((len(k.split()) for k in self._names), default=1))

    # ------------------------------------------------------------------------------------------------ public
    def check(self, question: str, *, portfolio: bool = False) -> InputResult:
        result = InputResult()
        text = question or ""
        outside = self._outside_stocks(text)
        if outside:
            many = len(outside) > 1
            result.blocks.append({
                "id": "G1", "names": outside,
                "text": f"G1: {', '.join(outside)} {'are' if many else 'is'} not in the Nifty 50. "
                        f"This app covers the Nifty 50 only, so it cannot answer about "
                        f"{'them' if many else 'it'}. Ask again with Nifty 50 stocks."})
        if portfolio:
            count = self._portfolio_count(text)
            if count is not None and count > MAX_STOCKS:
                result.blocks.append({
                    "id": "G2", "count": count,
                    "text": f"G2: A portfolio holds {MIN_STOCKS} to {MAX_STOCKS} stocks. You asked for {count}. "
                            f"Ask again with {MIN_STOCKS} to {MAX_STOCKS} stocks."})
            elif count is not None and count < MIN_STOCKS:
                result.blocks.append({
                    "id": "G3", "count": count,
                    "text": f"G3: A portfolio holds {MIN_STOCKS} to {MAX_STOCKS} stocks. You asked for {count}. "
                            f"Ask again with {MIN_STOCKS} to {MAX_STOCKS} stocks."})
        return result

    # ------------------------------------------------------------------------------------------------ G1
    def _mask(self, text: str) -> str:
        if self._mask_names:
            text = self._mask_names.sub(" ", text)
        if self._mask_exact:
            text = self._mask_exact.sub(" ", text)
        return text

    def _outside_stocks(self, text: str) -> list[str]:
        masked = self._mask(text)
        found: list[str] = []
        for token in re.findall(r"(?<![A-Za-z0-9])[A-Z0-9]{4,}(?![A-Za-z0-9])", masked):
            shown = self._codes.get(token)
            if shown and shown not in found:
                found.append(shown)
        words = _norm(masked).split()
        i = 0
        while i < len(words):
            for size in range(min(self._longest, len(words) - i), 0, -1):
                shown = self._names.get(" ".join(words[i:i + size]))
                if shown:
                    if shown.lower() not in {f.lower() for f in found}:
                        found.append(shown)
                    i += size - 1
                    break
            i += 1
        return found

    # ------------------------------------------------------------------------------------------------ G2 / G3
    @staticmethod
    def _portfolio_count(text: str) -> int | None:
        tokens = re.findall(r"[a-z]+|\d+", text.lower())
        counts: set[int] = set()
        for i, tok in enumerate(tokens):
            value = int(tok) if tok.isdigit() else _NUMBER_WORDS.get(tok)
            if value is None or (i and tokens[i - 1] == "nifty"):
                continue
            for look in tokens[i + 1:i + 2 + _MAX_FILLER]:
                if look in _STOCK_WORDS:
                    counts.add(value)
                    break
                if look in _BREAKERS or look.isdigit() or look in _NUMBER_WORDS:
                    break
        return counts.pop() if len(counts) == 1 else None


def _read(path: Path) -> list[dict]:
    try:
        with open(path, encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    except OSError as exc:
        raise InputGuardError(f"stock list not readable: {path} ({exc})") from exc


def load_default() -> InputGuard:
    """The guard built from the project's own lists (paths come from config/paths.json)."""
    import config
    import news_tools
    try:
        nifty, everything = _read(config.nifty50_list()), _read(config.all_stocks_list())
    except config.PathsError as exc:
        raise InputGuardError(str(exc)) from exc
    return InputGuard(nifty, everything, news_tools.ALIASES)


@lru_cache(maxsize=1)
def default_guard() -> InputGuard:
    """Built once per process. Raises InputGuardError when a list is missing."""
    return load_default()
