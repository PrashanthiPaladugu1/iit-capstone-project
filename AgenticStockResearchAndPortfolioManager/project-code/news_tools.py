"""news_tools: Indian market headlines from publisher RSS feeds, matched to Nifty 50 stocks. No model is used here
except to label a headline positive, negative or neutral, and only through the gateway (role "sentiment").

What it reads: the title, link, date and source of each RSS item. It never downloads an article page.
What the numbers are: counts are added up by code. The model only labels each headline.

    tools = NewsTools()
    tools.search("TCS", days=7)          # headlines that name the stock
    tools.market(days=1)                 # latest market headlines, any stock
    tools.sentiment("Infosys", days=7)   # positive / negative / neutral counts
"""
from __future__ import annotations

import csv
import email.utils
import html
import json
import re
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx

import config
from gateway import GatewayError

IST = timezone(timedelta(hours=5, minutes=30))
CACHE_SECONDS = 15 * 60            # a feed is downloaded at most once in 15 minutes
FETCH_TIMEOUT_S = 12.0
MAX_PER_SITE = 4                   # in one answer, so one publisher cannot fill the list
MAX_SENTIMENT_HEADLINES = 12
LABELS = ("positive", "negative", "neutral")
USER_AGENT = "Mozilla/5.0 (compatible; ARPM-news/1.0)"

NOTE = ("Headlines only (title, source, date, link) from publisher RSS feeds, never the full articles. "
        "No headline can mean the stock was not in these feeds, not that nothing happened.")


class NewsError(ValueError):
    pass


@dataclass(frozen=True)
class Feed:
    site: str
    name: str
    url: str


# Checked on 26 Nov 2026: every one answered with items dated that day. Moneycontrol (last item April 2024), Financial Express
# (invalid XML) and Zee Business (HTTP 403) were left out.
FEEDS = [
    Feed("Economic Times", "Markets (stocks)", "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms"),
    Feed("Economic Times", "Markets (all)", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
    Feed("Economic Times", "Company news", "https://economictimes.indiatimes.com/news/company/rssfeeds/2143429.cms"),
    Feed("Economic Times", "Industry", "https://economictimes.indiatimes.com/industry/rssfeeds/13352306.cms"),
    Feed("Economic Times", "Tech and IT", "https://economictimes.indiatimes.com/tech/rssfeeds/13357270.cms"),
    Feed("Economic Times", "Economy", "https://economictimes.indiatimes.com/news/economy/rssfeeds/1373380680.cms"),
    Feed("Mint", "Markets", "https://www.livemint.com/rss/markets"),
    Feed("Business Standard", "Markets", "https://www.business-standard.com/rss/markets-106.rss"),
    Feed("Hindu BusinessLine", "Markets", "https://www.thehindubusinessline.com/markets/feeder/default.rss"),
    Feed("NDTV Profit", "Latest", "https://feeds.feedburner.com/ndtvprofit-latest"),
]

# symbol: (names matched ignoring case, exact words matched with their capitals, phrases removed before matching).
# A short name such as ITC or Trent is matched with its capitals so ordinary words do not match.
# Known gaps: "Reliance" alone is not matched (it could be Reliance Power or Infra); say "Reliance Industries" or RIL.
ALIASES: dict[str, tuple[list[str], list[str], list[str]]] = {
    "ADANIENT": (["Adani Enterprises"], [], []),
    "ADANIPORTS": (["Adani Ports"], [], []),
    "APOLLOHOSP": (["Apollo Hospitals"], [], []),
    "ASIANPAINT": (["Asian Paints"], [], []),
    "AXISBANK": (["Axis Bank"], [], []),
    "BAJAJ-AUTO": (["Bajaj Auto"], [], []),
    "BAJFINANCE": (["Bajaj Finance"], [], []),
    "BAJAJFINSV": (["Bajaj Finserv"], [], []),
    "BEL": (["Bharat Electronics"], ["BEL"], []),
    "BHARTIARTL": (["Bharti Airtel", "Airtel"], [], []),
    "BSE": (["BSE Ltd", "BSE Limited", "BSE share", "BSE shares", "BSE stock"], [], []),   # BSE alone is the exchange
    "CIPLA": (["Cipla"], [], []),
    "COALINDIA": (["Coal India"], [], []),
    "DRREDDY": (["Dr Reddy", "Dr. Reddy"], [], []),
    "EICHERMOT": (["Eicher Motors", "Royal Enfield"], [], []),
    "ETERNAL": (["Zomato"], ["Eternal"], []),
    "GRASIM": (["Grasim"], [], []),
    "HCLTECH": (["HCL Technologies", "HCL Tech", "HCLTech"], [], []),
    "HDFCBANK": (["HDFC Bank"], [], []),
    "HDFCLIFE": (["HDFC Life"], [], []),
    "HINDUNILVR": (["Hindustan Unilever"], ["HUL"], []),
    "HINDALCO": (["Hindalco"], [], []),
    "ICICIBANK": (["ICICI Bank"], [], []),
    "INFY": (["Infosys"], ["INFY"], []),
    "INDIGO": (["IndiGo", "InterGlobe Aviation"], [], []),
    "ITC": ([], ["ITC"], ["ITC Hotels"]),
    "JIOFIN": (["Jio Financial"], [], []),
    "JSWSTEEL": (["JSW Steel"], [], []),
    "KOTAKBANK": (["Kotak Mahindra Bank", "Kotak Bank"], [], []),
    "LT": (["Larsen & Toubro", "Larsen and Toubro", "L&T"], [], []),
    "M&M": (["Mahindra & Mahindra", "Mahindra and Mahindra", "M&M"], [], []),
    "MARUTI": (["Maruti Suzuki", "Maruti"], [], []),
    "MAXHEALTH": (["Max Healthcare"], [], []),
    "NESTLEIND": (["Nestle India", "Nestlé India"], [], []),
    "NTPC": ([], ["NTPC"], ["NTPC Green"]),
    "ONGC": (["Oil and Natural Gas Corporation"], ["ONGC"], []),
    "POWERGRID": (["Power Grid"], [], []),
    "RELIANCE": (["Reliance Industries"], ["RIL"], []),
    "SBIN": (["State Bank of India"], ["SBI"], ["SBI Life", "SBI Card", "SBI Cards", "SBI Mutual", "SBI MF", "SBI General"]),
    "SBILIFE": (["SBI Life"], [], []),
    "SHRIRAMFIN": (["Shriram Finance"], [], []),
    "SUNPHARMA": (["Sun Pharma"], [], []),
    "TATACONSUM": (["Tata Consumer"], [], []),
    "TMPV": (["Tata Motors"], [], []),
    "TATASTEEL": (["Tata Steel"], [], []),
    "TCS": (["Tata Consultancy Services", "Tata Consultancy"], ["TCS"], []),
    "TECHM": (["Tech Mahindra"], [], []),
    "TITAN": (["Titan Company"], ["Titan"], []),
    "TRENT": ([], ["Trent"], []),
    "ULTRACEMCO": (["UltraTech Cement", "UltraTech"], [], []),
}

_EDGE_BEFORE, _EDGE_AFTER = r"(?<![A-Za-z0-9])", r"(?![A-Za-z0-9])"


def _compile(words: list[str], flags: int):
    if not words:
        return None
    return re.compile(_EDGE_BEFORE + "(?:" + "|".join(re.escape(w) for w in words) + ")" + _EDGE_AFTER, flags)


_MATCHERS = {sym: (_compile(names, re.I), _compile(exact, 0), [p.lower() for p in drop])
             for sym, (names, exact, drop) in ALIASES.items()}


def mentions(symbol: str, title: str) -> bool:
    """True when the headline names this Nifty 50 stock."""
    names, exact, drop = _MATCHERS[symbol]
    text = title
    for phrase in drop:
        text = re.sub(re.escape(phrase), " ", text, flags=re.I)
    return bool((names and names.search(text)) or (exact and exact.search(text)))


def resolve(text: str) -> str:
    """A Nifty 50 symbol from a symbol or a company name ("INFY", "Infosys", "tata consultancy"). Raises NewsError."""
    wanted = (text or "").strip()
    if not wanted:
        raise NewsError("name a Nifty 50 stock, for example TCS or Infosys")
    if wanted.upper() in ALIASES:
        return wanted.upper()
    for sym, (names, exact, _) in ALIASES.items():
        if wanted.lower() in {n.lower() for n in names} or wanted in exact:
            return sym
    hits = [sym for sym, (names, _, _) in ALIASES.items() if any(wanted.lower() in n.lower() for n in names)]
    if len(hits) == 1:
        return hits[0]
    raise NewsError(f"'{wanted}' is not a Nifty 50 stock this app covers")


# ------------------------------------------------------------------------------------------------ reading feeds
@dataclass(frozen=True)
class Item:
    site: str
    feed: str
    title: str
    link: str
    published: datetime


# Live blogs and price pages are not news: they carry a price table, not a story, and their text changes all day.
_NOT_NEWS = re.compile(r"share price (highlights|today|live)|stock price (history|today)|\blive (updates|blog)\b"
                       r"|\blive:|\|\s*nifty.*\blive\b", re.I)


def parse_feed(raw: bytes, feed: Feed) -> list[Item]:
    """RSS 2.0 items with a title and a readable date. An item with no date is dropped (a stale feed cannot pass as new).
    Live-blog and price-page titles are dropped too."""
    items = []
    for node in ET.fromstring(raw).findall(".//item"):
        title = html.unescape((node.findtext("title") or "").strip())
        stamp = (node.findtext("pubDate") or "").strip()
        if not title or not stamp or _NOT_NEWS.search(title):
            continue
        try:
            when = email.utils.parsedate_to_datetime(stamp)
        except (TypeError, ValueError):
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=IST)
        items.append(Item(feed.site, feed.name, title, (node.findtext("link") or "").strip(), when))
    return items


def fetch_bytes(url: str, transport: httpx.BaseTransport | None = None) -> bytes:
    with httpx.Client(timeout=FETCH_TIMEOUT_S, follow_redirects=True, transport=transport,
                      headers={"User-Agent": USER_AGENT}) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.content


def _key(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def pick(items: list[Item], limit: int, per_site: int = MAX_PER_SITE) -> list[Item]:
    """Newest first, one story once, and at most `per_site` from any one publisher."""
    seen, count, out = set(), {}, []
    for item in sorted(items, key=lambda i: i.published, reverse=True):
        key = _key(item.title)
        if key in seen or count.get(item.site, 0) >= per_site:
            continue
        seen.add(key)
        count[item.site] = count.get(item.site, 0) + 1
        out.append(item)
        if len(out) >= limit:
            break
    return out


# ------------------------------------------------------------------------------------------------ the tools
class NewsTools:
    def __init__(self, fetch=None, gateway=None, clock=time.time, feeds: list[Feed] | None = None):
        self._fetch = fetch or fetch_bytes             # fetch(url) -> bytes; tests pass a fake
        self._gateway = gateway
        self._clock = clock
        self.feeds = feeds or FEEDS
        self._cache: dict[str, tuple[float, list[Item] | str]] = {}    # url -> (time, items or the error text)
        self._labels: dict[tuple[str, str], str] = {}                  # (symbol, title) -> label
        self._lock = threading.Lock()

    @property
    def gateway(self):
        if self._gateway is None:
            from gateway import Gateway
            self._gateway = Gateway()
        return self._gateway

    # ---------------------------------------------------------------- feeds
    def _load(self) -> tuple[list[Item], list[str], float]:
        """All items from all feeds, the names of the feeds that failed, and when the oldest download happened."""
        with self._lock:
            now = self._clock()
            stale = [f for f in self.feeds if f.url not in self._cache or now - self._cache[f.url][0] > CACHE_SECONDS]
            if stale:
                with ThreadPoolExecutor(max_workers=min(5, len(stale))) as pool:
                    results = list(pool.map(self._download, stale))
                for feed, result in zip(stale, results):
                    self._cache[feed.url] = (now, result)
            items, failed, oldest = [], [], now
            for feed in self.feeds:
                stamp, value = self._cache[feed.url]
                oldest = min(oldest, stamp)
                if isinstance(value, str):
                    failed.append(f"{feed.site} {feed.name}")
                else:
                    items.extend(value)
            return items, failed, oldest

    def _download(self, feed: Feed) -> list[Item] | str:
        try:
            return parse_feed(self._fetch(feed.url), feed)
        except Exception as exc:                          # a bad feed must never stop the others
            return f"{type(exc).__name__}: {exc}"

    def _recent(self, days: int) -> tuple[list[Item], list[str], float]:
        if not isinstance(days, int) or isinstance(days, bool) or not 1 <= days <= 30:
            raise NewsError("days must be a whole number from 1 to 30")
        items, failed, stamp = self._load()
        cutoff = datetime.fromtimestamp(self._clock(), timezone.utc) - timedelta(days=days)
        return [i for i in items if i.published >= cutoff], failed, stamp

    def _out(self, item: Item) -> dict:
        return {"source": f"{item.site} ({item.feed})", "date": item.published.isoformat(timespec="minutes"),
                "title": item.title, "link": item.link}

    def _meta(self, failed: list[str], stamp: float) -> dict:
        return {"feeds_checked": len(self.feeds), "feeds_failed": failed,
                "fetched_at": datetime.fromtimestamp(stamp, IST).isoformat(timespec="minutes"), "note": NOTE}

    # ---------------------------------------------------------------- public
    def search(self, stock: str, days: int = 7, limit: int = 10) -> dict:
        symbol = resolve(stock)
        recent, failed, stamp = self._recent(days)
        matched = [i for i in recent if mentions(symbol, i.title)]
        shown = pick(matched, max(1, min(int(limit), 20)))
        return {"symbol": symbol, "days": days, "headlines_found": len(matched), "shown": len(shown),
                "headlines": [self._out(i) for i in shown], **self._meta(failed, stamp)}

    def market(self, days: int = 1, limit: int = 10) -> dict:
        recent, failed, stamp = self._recent(days)
        shown = pick(recent, max(1, min(int(limit), 20)), per_site=3)
        return {"days": days, "shown": len(shown), "headlines": [self._out(i) for i in shown], **self._meta(failed, stamp)}

    def sentiment(self, stock: str, days: int = 7) -> dict:
        symbol = resolve(stock)
        recent, failed, stamp = self._recent(days)
        chosen = pick([i for i in recent if mentions(symbol, i.title)], MAX_SENTIMENT_HEADLINES)
        labels = self._label(symbol, chosen)
        rows = [{**self._out(i), "sentiment": labels[n]} for n, i in enumerate(chosen)]
        counts = {name: sum(1 for r in rows if r["sentiment"] == name) for name in (*LABELS, "unlabelled")}
        return {"symbol": symbol, "days": days, "headlines_checked": len(rows), **counts, "headlines": rows,
                "method": "Each headline is labelled by a model (gateway role sentiment). The counts are added up by code. "
                          "A rough guide from headlines only, not a measurement and not a forecast.",
                **self._meta(failed, stamp)}

    # ---------------------------------------------------------------- labelling
    def _label(self, symbol: str, items: list[Item]) -> list[str]:
        """One label per item, in order. Labels already given in this session are reused, so a repeat question costs no model call."""
        todo = [n for n, i in enumerate(items) if (symbol, i.title) not in self._labels]
        if todo:
            lines = "\n".join(f"{n + 1}. {items[n].title}" for n in todo)
            prompt = (f"Label each numbered headline as positive, negative or neutral for the share price of {symbol} "
                      f"({(ALIASES[symbol][0] or ALIASES[symbol][1])[0]}). A headline about several stocks is judged only for "
                      f"this one. Reply with JSON only, for example {{\"1\": \"positive\", \"2\": \"neutral\"}}.\n\n{lines}")
            try:
                reply = self.gateway.chat("sentiment", [{"role": "user", "content": prompt}], None,
                                          params={"temperature": 0}, agent="agent_news", node="sentiment", route="news",
                                          preview=symbol).text
            except GatewayError as exc:
                raise NewsError(f"the sentiment model is not available: {exc}") from exc
            parsed = _parse_labels(reply)
            for position, n in enumerate(todo, 1):
                self._labels[(symbol, items[n].title)] = parsed.get(str(position), "unlabelled")
        return [self._labels[(symbol, i.title)] for i in items]


def _parse_labels(text: str) -> dict[str, str]:
    body = text or ""
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        data = json.loads(body[start:end + 1])
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v).strip().lower() for k, v in data.items() if str(v).strip().lower() in LABELS}


def nifty50_symbols() -> list[str]:
    """The symbols in the project's Nifty 50 list (used to check ALIASES covers every stock)."""
    with open(config.nifty50_list(), encoding="utf-8", newline="") as handle:
        return [row["NSE Code"].strip() for row in csv.DictReader(handle) if row.get("NSE Code", "").strip()]
