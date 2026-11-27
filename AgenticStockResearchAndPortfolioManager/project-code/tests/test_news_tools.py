"""news_tools and mcp_news: feed parsing, matching headlines to Nifty 50 stocks, dedupe, cache, sentiment counts.

No network and no model: feeds come from a fake fetch and labels from a scripted gateway.
"""
import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import news_tools  # noqa: E402
from gateway import GatewayError  # noqa: E402
from news_tools import ALIASES, Feed, NewsError, NewsTools, mentions, parse_feed, pick, resolve  # noqa: E402
from providers import ChatResult  # noqa: E402

NOW = datetime(2026, 11, 26, 9, 0, tzinfo=timezone.utc)
FEED_A = Feed("Economic Times", "Markets", "https://a.test/rss")
FEED_B = Feed("Mint", "Markets", "https://b.test/rss")


def rss(*items):
    body = "".join(f"<item><title>{t}</title><link>https://x.test/{n}</link><pubDate>{d}</pubDate></item>"
                   for n, (t, d) in enumerate(items))
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title>{body}</channel></rss>'.encode()


def ago(**delta):
    return (NOW - timedelta(**delta)).strftime("%a, %d %b %Y %H:%M:%S +0000")


class FakeFetch:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def __call__(self, url):
        self.calls.append(url)
        page = self.pages[url]
        if isinstance(page, Exception):
            raise page
        return page


class Clock:
    def __init__(self):
        self.now = NOW.timestamp()

    def __call__(self):
        return self.now


class Labeller:
    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def chat(self, role, messages, tools=None, **kw):
        self.calls.append({"role": role, "prompt": messages[0]["content"], **kw})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return ChatResult(text=reply, tokens_in=100, tokens_out=10)


def tools_with(pages, gateway=None, feeds=None):
    fetch, clock = FakeFetch(pages), Clock()
    return NewsTools(fetch=fetch, gateway=gateway, clock=clock, feeds=feeds or [FEED_A, FEED_B]), fetch, clock


# ------------------------------------------------------------------------------------------------ matching
@pytest.mark.parametrize("symbol,title", [
    ("TCS", "TCS wins a large deal in Europe"),
    ("TCS", "Tata Consultancy Services Q2 profit rises"),
    ("INFY", "Infosys raises its revenue guidance"),
    ("HDFCBANK", "HDFC Bank shares fall after results"),
    ("LT", "L&T bags a big order"),
    ("M&M", "M&M sales rise in October"),
    ("ITC", "ITC shares gain on cigarette volume growth"),
    ("SBIN", "SBI raises lending rate"),
    ("RELIANCE", "Reliance Industries and Jio plan a listing"),
])
def test_headline_that_names_the_stock_matches(symbol, title):
    assert mentions(symbol, title)


@pytest.mark.parametrize("symbol,title", [
    ("TCS", "Tcs is a stock ticker in this word list"),            # exact capitals required for the short name
    ("ITC", "The itch to buy small caps is back"),
    ("ITC", "ITC Hotels demerger gets a new date"),                 # a different company
    ("SBIN", "SBI Life posts record premium"),                      # SBI Life is its own Nifty stock
    ("SBIN", "SBI Cards net profit slips"),
    ("TRENT", "The current trend in midcaps is up"),
    ("BSE", "Sensex and Nifty rise as BSE benchmark gains"),        # the exchange, not the company
    ("NTPC", "NTPC Green Energy lists at a premium"),
    ("TCS", "Infosys and Wipro rally"),
])
def test_headline_that_only_looks_similar_does_not_match(symbol, title):
    assert not mentions(symbol, title)


def test_every_stock_in_the_nifty_50_file_has_an_alias_entry_and_nothing_extra():
    assert set(news_tools.nifty50_symbols()) == set(ALIASES)


def test_every_alias_entry_can_match_something():
    for symbol, (names, exact, _) in ALIASES.items():
        assert names or exact, symbol


@pytest.mark.parametrize("text,expected", [("TCS", "TCS"), ("tcs", "TCS"), ("Infosys", "INFY"), ("infosys", "INFY"),
                                           ("Tata Consultancy Services", "TCS"), ("hdfc bank", "HDFCBANK"),
                                           ("  ITC ", "ITC"), ("Reliance Industries", "RELIANCE")])
def test_resolve_accepts_a_symbol_or_a_company_name(text, expected):
    assert resolve(text) == expected


@pytest.mark.parametrize("text", ["", "   ", "Wipro", "Tata"])
def test_resolve_refuses_unknown_or_ambiguous_names(text):
    with pytest.raises(NewsError):
        resolve(text)


# ------------------------------------------------------------------------------------------------ feed parsing
def test_parse_feed_reads_title_link_date_and_source():
    items = parse_feed(rss(("TCS wins deal", ago(hours=2))), FEED_A)
    assert len(items) == 1
    assert (items[0].site, items[0].feed, items[0].title) == ("Economic Times", "Markets", "TCS wins deal")
    assert items[0].link == "https://x.test/0" and items[0].published == NOW - timedelta(hours=2)


def test_parse_feed_unescapes_html_and_drops_items_without_a_readable_date():
    raw = rss(("Market &amp; rupee: Nifty up", ago(hours=1)), ("No date item", ""), ("Bad date", "yesterday-ish"))
    assert [i.title for i in parse_feed(raw, FEED_A)] == ["Market & rupee: Nifty up"]


def test_parse_feed_treats_a_date_without_a_zone_as_indian_time():
    items = parse_feed(rss(("TCS", "Thu, 26 Nov 2026 10:00:00")), FEED_A)
    assert items[0].published.utcoffset() == timedelta(hours=5, minutes=30)


def test_parse_feed_rejects_text_that_is_not_xml():
    with pytest.raises(Exception):
        parse_feed(b"<html>blocked</html", FEED_A)

@pytest.mark.parametrize("title", [
    "TCS Share Price Highlights: Nifty ends flat",
    "Infosys Stock Price History: 5 year chart",
    "Reliance share price today: live updates",
    "TCS SHARE PRICE LIVE: stock slips",
    "Stock Market LIVE Updates: Sensex, Nifty",
    "Sensex Today | Nifty 50 live blog",
])
def test_parse_feed_drops_live_blog_and_price_page_titles(title):
    assert parse_feed(rss((title, ago(hours=1))), FEED_A) == []


def test_parse_feed_keeps_real_news_that_only_mentions_a_price():
    raw = rss(("TCS shares rise 3% after deal win", ago(hours=1)), ("Infosys Q2 profit beats estimates", ago(hours=2)))
    assert len(parse_feed(raw, FEED_A)) == 2




# ------------------------------------------------------------------------------------------------ pick / dedupe
def item(title, hours, site="Mint"):
    return news_tools.Item(site, "Markets", title, "https://x.test", NOW - timedelta(hours=hours))


def test_pick_orders_newest_first_and_removes_the_same_story_from_two_feeds():
    out = pick([item("TCS wins deal!", 5), item("TCS Wins Deal", 3, "Economic Times"), item("Infosys up", 1)], 10)
    assert [i.title for i in out] == ["Infosys up", "TCS Wins Deal"]


def test_pick_caps_each_publisher_so_one_site_cannot_fill_the_list():
    items = [item(f"TCS story {n}", n, "Economic Times") for n in range(1, 9)] + [item("TCS other site", 20, "Mint")]
    out = pick(items, 10, per_site=4)
    assert sum(1 for i in out if i.site == "Economic Times") == 4 and any(i.site == "Mint" for i in out)


def test_pick_stops_at_the_limit():
    assert len(pick([item(f"s{n}", n, f"site{n}") for n in range(1, 9)], 3)) == 3


# ------------------------------------------------------------------------------------------------ search / market
def pages(a=None, b=None):
    return {FEED_A.url: rss(*(a or [])), FEED_B.url: rss(*(b or []))}


def test_search_returns_only_headlines_that_name_the_stock_inside_the_day_window():
    t, _, _ = tools_with(pages(
        a=[("TCS wins a big deal", ago(hours=3)), ("Infosys results beat estimates", ago(hours=4)),
           ("TCS old story", ago(days=10))],
        b=[("Tata Consultancy Services hires 5,000 freshers", ago(hours=6))]))
    out = t.search("TCS", days=2)
    assert out["symbol"] == "TCS" and out["headlines_found"] == 2 and out["shown"] == 2
    assert [h["title"] for h in out["headlines"]] == ["TCS wins a big deal", "Tata Consultancy Services hires 5,000 freshers"]
    assert out["headlines"][0]["source"] == "Economic Times (Markets)" and out["headlines"][0]["link"].startswith("https://")
    assert "Headlines only" in out["note"] and out["feeds_checked"] == 2 and out["feeds_failed"] == []


def test_search_with_no_match_says_so_with_zero_headlines_not_an_error():
    t, _, _ = tools_with(pages(a=[("Sensex ends flat", ago(hours=1))]))
    out = t.search("Infosys", days=7)
    assert out["headlines_found"] == 0 and out["headlines"] == [] and "not that nothing happened" in out["note"]


def test_search_accepts_a_company_name_and_reports_the_symbol():
    t, _, _ = tools_with(pages(a=[("Infosys wins a deal", ago(hours=1))]))
    assert t.search("infosys")["symbol"] == "INFY"


@pytest.mark.parametrize("days", [0, 31, -1, 2.5, "7", True, None])
def test_days_must_be_a_whole_number_from_1_to_30(days):
    t, _, _ = tools_with(pages())
    with pytest.raises(NewsError):
        t.search("TCS", days=days)


def test_search_limit_is_kept_between_1_and_20():
    items = [(f"TCS story number {n} about deals", ago(hours=n)) for n in range(1, 30)]
    t, _, _ = tools_with(pages(a=items[:15], b=items[15:]))
    assert t.search("TCS", days=7, limit=100)["shown"] <= 20
    assert t.search("TCS", days=7, limit=0)["shown"] == 1


def test_market_lists_latest_headlines_without_a_stock():
    t, _, _ = tools_with(pages(a=[("Nifty hits a 26-week high", ago(hours=1)), ("Rupee slips to 92.40", ago(hours=2))],
                               b=[("Gold eases", ago(hours=3))]))
    out = t.market(days=1)
    assert [h["title"] for h in out["headlines"]] == ["Nifty hits a 26-week high", "Rupee slips to 92.40", "Gold eases"]


# ------------------------------------------------------------------------------------------------ cache and failures
def test_a_feed_is_downloaded_once_in_15_minutes_and_again_after():
    t, fetch, clock = tools_with(pages(a=[("TCS wins deal", ago(hours=1))]))
    t.search("TCS")
    t.search("Infosys")
    assert sorted(fetch.calls) == [FEED_A.url, FEED_B.url]            # two feeds, once each
    clock.now += 14 * 60
    t.search("TCS")
    assert len(fetch.calls) == 2
    clock.now += 2 * 60
    t.search("TCS")
    assert len(fetch.calls) == 4


def test_one_broken_feed_is_named_and_the_others_still_answer():
    page = pages(a=[("TCS wins deal", ago(hours=1))])
    page[FEED_B.url] = ConnectionError("blocked")
    t, _, _ = tools_with(page)
    out = t.search("TCS")
    assert out["headlines_found"] == 1 and out["feeds_failed"] == ["Mint Markets"]


def test_a_feed_that_returns_bad_xml_counts_as_failed():
    page = pages(a=[("TCS wins deal", ago(hours=1))])
    page[FEED_B.url] = b"<html>403 Forbidden"
    t, _, _ = tools_with(page)
    assert t.search("TCS")["feeds_failed"] == ["Mint Markets"]


def test_all_feeds_failing_gives_an_empty_answer_that_names_them_all():
    t, _, _ = tools_with({FEED_A.url: OSError("down"), FEED_B.url: OSError("down")})
    out = t.search("TCS")
    assert out["headlines"] == [] and len(out["feeds_failed"]) == 2


def test_fetched_at_is_shown_in_indian_time():
    t, _, _ = tools_with(pages())
    assert t.search("TCS")["fetched_at"] == "2026-11-26T14:30+05:30"   # 09:00 UTC is 14:30 IST


def test_the_real_feed_list_uses_only_the_five_checked_sites():
    assert {f.site for f in news_tools.FEEDS} == {"Economic Times", "Mint", "Business Standard", "Hindu BusinessLine",
                                                   "NDTV Profit"}
    assert all(f.url.startswith("https://") for f in news_tools.FEEDS)
    assert not any("moneycontrol" in f.url or "zeebiz" in f.url or "google" in f.url for f in news_tools.FEEDS)


# ------------------------------------------------------------------------------------------------ sentiment
STORIES = [("TCS wins a large deal", ago(hours=1)), ("TCS shares slump after weak guidance", ago(hours=2)),
           ("TCS holds its annual meeting", ago(hours=3))]


def test_sentiment_counts_are_added_up_by_code_from_the_model_labels():
    gw = Labeller('{"1": "positive", "2": "negative", "3": "neutral"}')
    t, _, _ = tools_with(pages(a=STORIES), gateway=gw)
    out = t.sentiment("TCS")
    assert (out["positive"], out["negative"], out["neutral"], out["unlabelled"]) == (1, 1, 1, 0)
    assert {h["title"]: h["sentiment"] for h in out["headlines"]} == {
        "TCS wins a large deal": "positive", "TCS shares slump after weak guidance": "negative",
        "TCS holds its annual meeting": "neutral"}
    assert "not a forecast" in out["method"]
    assert gw.calls[0]["role"] == "sentiment" and gw.calls[0]["agent"] == "agent_news"


def test_the_model_is_asked_once_for_all_headlines_and_not_again_for_a_repeat_question():
    gw = Labeller('{"1": "positive", "2": "negative", "3": "neutral"}')
    t, _, _ = tools_with(pages(a=STORIES), gateway=gw)
    t.sentiment("TCS")
    again = t.sentiment("TCS")
    assert len(gw.calls) == 1 and again["positive"] == 1


def test_an_unusable_label_or_reply_is_counted_as_unlabelled_never_guessed():
    gw = Labeller('{"1": "very bullish", "2": "negative"}')            # 1 not allowed, 3 missing
    t, _, _ = tools_with(pages(a=STORIES), gateway=gw)
    out = t.sentiment("TCS")
    assert (out["positive"], out["negative"], out["neutral"], out["unlabelled"]) == (0, 1, 0, 2)


@pytest.mark.parametrize("reply", ["I cannot do that", "", "[1, 2, 3]", "{not json}"])
def test_a_reply_that_is_not_a_json_object_leaves_every_headline_unlabelled(reply):
    t, _, _ = tools_with(pages(a=STORIES), gateway=Labeller(reply))
    assert t.sentiment("TCS")["unlabelled"] == 3


def test_labels_are_read_even_when_the_model_wraps_the_json_in_text():
    gw = Labeller('Here you go:\n```json\n{"1": "Positive", "2": "NEGATIVE", "3": "neutral"}\n```')
    t, _, _ = tools_with(pages(a=STORIES), gateway=gw)
    out = t.sentiment("TCS")
    assert (out["positive"], out["negative"], out["neutral"]) == (1, 1, 1)


def test_sentiment_with_no_headlines_makes_no_model_call():
    gw = Labeller()
    t, _, _ = tools_with(pages(a=[("Sensex flat", ago(hours=1))]), gateway=gw)
    out = t.sentiment("TCS")
    assert out["headlines_checked"] == 0 and out["positive"] == 0 and gw.calls == []


def test_sentiment_model_failure_is_a_clear_error():
    t, _, _ = tools_with(pages(a=STORIES), gateway=Labeller(GatewayError("connection refused")))
    with pytest.raises(NewsError, match="sentiment model is not available"):
        t.sentiment("TCS")


def test_sentiment_labels_at_most_12_headlines():
    many = [(f"TCS story number {n} on deals", ago(hours=n)) for n in range(1, 40)]
    gw = Labeller("{}")
    t, _, _ = tools_with(pages(a=many[:20], b=many[20:]), gateway=gw)
    assert t.sentiment("TCS")["headlines_checked"] <= 12


def test_the_sentiment_prompt_judges_only_the_named_stock():
    gw = Labeller('{"1": "neutral"}')
    t, _, _ = tools_with(pages(a=[("TCS and Infosys rally", ago(hours=1))]), gateway=gw)
    t.sentiment("TCS")
    assert "only for this one" in gw.calls[0]["prompt"] and "TCS" in gw.calls[0]["prompt"]


# ------------------------------------------------------------------------------------------------ the MCP server
def test_server_lists_the_three_news_tools():
    import mcp_news
    res = asyncio.run(mcp_news.mcp.list_tools())
    assert {t.name for t in (res.tools if hasattr(res, "tools") else res)} == {"news_search", "news_sentiment", "news_market"}


def test_server_returns_errors_as_json_text(monkeypatch):
    import mcp_news
    t, _, _ = tools_with(pages())
    monkeypatch.setattr(mcp_news, "_tools", t)
    assert "not a Nifty 50 stock" in json.loads(mcp_news.news_search("Wipro"))["error"]
    assert "days must be" in json.loads(mcp_news.news_search("TCS", days=99))["error"]
    ok = json.loads(mcp_news.news_search("TCS"))
    assert ok["symbol"] == "TCS" and ok["headlines"] == []


def test_the_sentiment_role_exists_and_defaults_to_the_chat_model(tmp_path):
    from model_settings import ROLES, SettingsStore
    store = SettingsStore(tmp_path / "s.sqlite")
    assert "sentiment" in ROLES
    cfg = store.get_role("sentiment")
    assert (cfg.provider, cfg.model) == ("ollama_local", "gemma4:12b") and cfg.params["temperature"] == 0
