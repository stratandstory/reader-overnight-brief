"""Collector: URL dedupe across schemes, the news-sitemap parser, gap detection, retries."""

import tempfile
import unittest
from zoneinfo import ZoneInfo
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from unittest import mock

from reader import collect as collect_mod
from reader import pipeline
from reader.collect import collect, item_id, parse_news_sitemap
from reader.config import company_pattern, load_settings
from reader.net import FetchResult
from reader.store import Store

UTC = timezone.utc
NOW = datetime(2026, 9, 28, 10, 0, tzinfo=UTC)


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, 28, hour, minute, tzinfo=UTC)


def rss(*stamps: datetime) -> bytes:
    items = "".join(
        f"<item><title>Story {s:%H%M}</title><link>https://bbg.example/{s:%H%M}</link>"
        f"<pubDate>{format_datetime(s)}</pubDate></item>"
        for s in stamps
    )
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>{items}</channel></rss>'.encode()


def sitemap_entry(loc: str, title: str, published: str, language: str = "en", tickers: str = "") -> str:
    ticker_tag = f"<news:stock_tickers>{tickers}</news:stock_tickers>" if tickers else ""
    return (f"<url><loc>{loc}</loc><news:news><news:publication><news:name>PR Newswire</news:name>"
            f"<news:language>{language}</news:language></news:publication>"
            f"<news:publication_date>{published}</news:publication_date><news:title>{title}</news:title>"
            f"{ticker_tag}</news:news></url>")


def sitemap(*entries: str) -> bytes:
    return ('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
            'xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">' + "".join(entries) + "</urlset>").encode()


class FakeFetcher:
    """Answers each URL from a queue of prepared results."""

    def __init__(self, results: list[FetchResult]):
        self.results = list(results)
        self.calls = 0

    def get(self, url, max_bytes=0, accept="*/*"):
        self.calls += 1
        return self.results.pop(0)


class Clock:
    """utcnow for the store: a minute later on every call, so each check has its own time."""

    def __init__(self, start: datetime):
        self.t = start

    def __call__(self) -> datetime:
        self.t += timedelta(minutes=1)
        return self.t


def one_source(source_id: str):
    settings = load_settings()
    settings.sources = [s for s in settings.sources if s.id == source_id]
    return settings


class UrlTest(unittest.TestCase):
    def test_http_and_https_are_the_same_item(self):
        self.assertEqual(item_id("http://www.boj.or.jp/en/statistics/pi/cspi_release/sppi2608.pdf"),
                         item_id("https://www.boj.or.jp/en/statistics/pi/cspi_release/sppi2608.pdf"))
        self.assertNotEqual(item_id("https://www.boj.or.jp/a.htm"), item_id("https://www.boj.or.jp/b.htm"))


class SitemapTest(unittest.TestCase):
    def test_keeps_english_releases_that_name_or_list_a_watchlist_company(self):
        settings = load_settings()
        src = next(s for s in settings.sources if s.id == "prn_sitemap")
        tickers = {c.ticker: c.name for c in settings.companies}
        body = sitemap(
            sitemap_entry("https://prn.example/msft-dividend", "Microsoft Announces Quarterly Dividend",
                          "2026-09-28T06:00:00-04:00"),
            sitemap_entry("https://prn.example/results", "Fourth Quarter Results Announced",
                          "2026-09-28T06:05:00-04:00", tickers="ISIN:US0378331005,NASDAQ:AAPL"),
            sitemap_entry("https://prn.example/msft-de", "Microsoft kündigt Quartalsdividende an",
                          "2026-09-28T06:10:00-04:00", language="de"),
            sitemap_entry("https://prn.example/small", "Small Co Reports Record Results",
                          "2026-09-28T05:00:00-04:00", tickers="NASDAQ:DVLT"),
            sitemap_entry("https://prn.example/alert", "INVESTOR ALERT: Law Firm Investigates Microsoft",
                          "2026-09-28T06:20:00-04:00"),
            sitemap_entry("https://prn.example/undated", "Microsoft Names New Director", "2026-09-28"),
        )
        parsed = parse_news_sitemap(src, body, NOW, company_pattern(settings.companies), tickers)
        kept = {it["url"]: it for it in parsed.items}
        self.assertEqual(set(kept), {"https://prn.example/msft-dividend", "https://prn.example/results"})
        self.assertEqual(kept["https://prn.example/results"]["extra"]["company"], "Apple")
        self.assertEqual(kept["https://prn.example/msft-dividend"]["published_utc"], "2026-09-28T10:00:00+00:00")
        self.assertTrue(all(it["summary"] == "" for it in parsed.items))
        # The span covers every dated entry, kept or not; the undated one is left out.
        self.assertEqual(parsed.entries, 6)
        self.assertEqual((parsed.oldest, parsed.newest), (at(9), at(10, 20)))


class CollectTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "t.db")
        self.clock = mock.patch("reader.store.utcnow", Clock(NOW))
        self.clock.start()

    def tearDown(self):
        self.clock.stop()
        self.store.db.close()
        self.tmp.cleanup()

    def check(self, settings, *results):
        return collect(settings, self.store, FakeFetcher(list(results)), NOW)

    def test_gap_flagged_only_when_the_feed_turned_over(self):
        settings = one_source("bloomberg_markets")
        ok = lambda body: FetchResult("u", 200, body)
        first = self.check(settings, ok(rss(at(1), at(1, 10), at(1, 20))))
        overlapping = self.check(settings, ok(rss(at(1, 10), at(1, 20), at(1, 30), at(1, 40))))
        self.assertEqual(first.gaps + overlapping.gaps, [])
        previous_check = self.store.last_span("bloomberg_markets")["fetched_utc"]

        failed = self.check(settings, FetchResult("u", 502, error="HTTP 502"), FetchResult("u", 502, error="HTTP 502"))
        self.assertEqual(failed.statuses[0].status, "HTTP 502")
        with mock.patch.object(collect_mod, "RETRY_PAUSE", 0):
            turned_over = self.check(settings, ok(rss(at(2), at(2, 10), at(2, 20))))
        # Compared with the last good check, not the failed one in between.
        self.assertEqual([s.source.id for s in turned_over.gaps], ["bloomberg_markets"])
        self.assertEqual(turned_over.gaps[0].gap_since.isoformat(), previous_check)
        self.assertEqual([g["source_id"] for g in self.store.gaps_since(NOW)], ["bloomberg_markets"])
        [line] = pipeline._gaps(self.store, settings, NOW, NOW)
        self.assertRegex(line, r"^Bloomberg · Markets, check at 6:\d\d AM$")

    def test_failed_fetch_is_retried_once(self):
        settings = one_source("bloomberg_markets")
        fetcher = FakeFetcher([FetchResult("u", 404, error="HTTP 404"), FetchResult("u", 200, rss(at(1)))])
        with mock.patch.object(collect_mod, "RETRY_PAUSE", 0):
            report = collect(settings, self.store, fetcher, NOW)
        self.assertEqual((report.statuses[0].status, fetcher.calls), ("ok", 2))

        blocked = FakeFetcher([FetchResult("u", None, error="robots.txt disallows", robots_blocked=True)])
        report = collect(settings, self.store, blocked, NOW)
        self.assertEqual((report.statuses[0].status, blocked.calls), ("robots.txt disallows", 1))

    def test_empty_summary_keeps_the_stored_one(self):
        item = {"id": "i1", "source_id": "prn_all", "publisher": "PR Newswire", "section": "All releases",
                "kind": "wire", "tier": 0, "owner": "PR Newswire", "title": "T", "summary": "From the RSS feed",
                "url": "https://prn.example/a", "published_utc": "2026-09-28T09:00:00+00:00", "extra": {}}
        self.store.upsert_item(item)
        self.store.upsert_item({**item, "source_id": "prn_sitemap", "summary": ""})
        self.assertEqual(self.store.items_by_ids(["i1"])["i1"]["summary"], "From the RSS feed")
        self.store.upsert_item({**item, "summary": "Revised"})
        self.assertEqual(self.store.items_by_ids(["i1"])["i1"]["summary"], "Revised")


if __name__ == "__main__":
    unittest.main()


class CategoryFilterTest(unittest.TestCase):
    def test_only_tagged_entries_are_kept(self):
        from reader.collect import parse_feed
        from reader.config import Source
        src = Source(id="semafor", publisher="Semafor", section="Business", url="https://x.example/rss.xml",
                     kind="news", tier=2, owner="Semafor", categories=["Business", "Energy"])
        body = (b'<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>'
                b'<item><title>Gulf fund buys stake</title><link>https://x.example/1</link>'
                b'<pubDate>Mon, 28 Sep 2026 10:00:00 GMT</pubDate><category>Business</category></item>'
                b'<item><title>Election night</title><link>https://x.example/2</link>'
                b'<pubDate>Mon, 28 Sep 2026 10:05:00 GMT</pubDate><category>Politics</category></item>'
                b'<item><title>Untagged</title><link>https://x.example/3</link>'
                b'<pubDate>Mon, 28 Sep 2026 10:06:00 GMT</pubDate></item>'
                b'</channel></rss>')
        parsed = parse_feed(src, body, at(11), None)
        self.assertEqual([i["title"] for i in parsed.items], ["Gulf fund buys stake"])
        self.assertEqual(parsed.entries, 3)


class IndexPageTest(unittest.TestCase):
    """Official sources read from index pages: dated without times, stamped at first sight."""
    NY = ZoneInfo("America/New_York")

    def test_fdic_rows_today_are_stamped_now_and_older_ones_at_noon(self):
        from reader.collect import parse_fdic_press
        settings = load_settings()
        src = next(s for s in settings.sources if s.id == "fdic_press")
        now = datetime(2026, 9, 30, 15, 10, tzinfo=UTC)  # 11:10 AM New York
        body = ('<div class="views-row"><article><p class="news-date"><time datetime="2026-09-30">Sep 30, 2026</time></p>'
                '<p class="news-title"><a href="/news/press-releases/2026/one" rel="bookmark"> <span>FDIC Announces One</span></a></p></article></div>'
                '<div class="views-row"><article><p class="news-date"><time datetime="2026-09-29">Sep 29, 2026</time></p>'
                '<p class="news-title"><a href="/news/press-releases/2026/two" rel="bookmark"><span>Agencies Publish Two</span></a></p></article></div>').encode()
        parsed = parse_fdic_press(src, body, now, self.NY)
        by_title = {i["title"]: i for i in parsed.items}
        self.assertEqual(by_title["FDIC Announces One"]["published_utc"], "2026-09-30T15:10:00+00:00")
        self.assertEqual(by_title["Agencies Publish Two"]["published_utc"], "2026-09-29T16:00:00+00:00")  # noon New York
        self.assertEqual(by_title["FDIC Announces One"]["url"], "https://www.fdic.gov/news/press-releases/2026/one")
        self.assertTrue(all(i["extra"]["day_only"] for i in parsed.items))

    def test_nyfed_keeps_recent_markets_banking_research_rows_only(self):
        from reader.collect import parse_nyfed_news
        settings = load_settings()
        src = next(s for s in settings.sources if s.id == "nyfed_news")
        now = datetime(2026, 10, 2, 13, 0, tzinfo=UTC)
        row = ('<tr class=" {cls}" valign="top"> <td width="96" class="dirColL"> <div> {day} </div> </td> <td class="dirColR">'
               ' <div class="tablTitle"> <a href="{href}" class="paraHeader">{title}</a> </div> </td> </tr>')
        body = (row.format(cls="archive archiveItem Markets", day="Oct 1, 2026", href="/newsevents/news/markets/2026/a", title="Repo operations")
                + row.format(cls="archive archiveItem About", day="Oct 1, 2026", href="/newsevents/news/aboutthefed/2026/b", title="Council appointment")
                + row.format(cls="archive archiveItem Research", day="Sep 8, 2026", href="/newsevents/news/research/2026/c", title="Old survey")).encode()
        parsed = parse_nyfed_news(src, body, now, self.NY)
        self.assertEqual([i["title"] for i in parsed.items], ["Repo operations"])
        self.assertEqual(parsed.items[0]["extra"], {"day_only": True, "nyfed_section": "Markets"})
        self.assertEqual(parsed.entries, 3)
        speeches = parse_nyfed_news(src, body, now, self.NY, sections=())
        self.assertEqual([i["title"] for i in speeches.items], ["Repo operations", "Council appointment"])
        self.assertEqual(speeches.items[0]["extra"], {"day_only": True})

    def test_treasury_manifest_is_followed_to_the_newest_shard(self):
        from reader.collect import parse_treasury_press
        settings = load_settings()
        src = next(s for s in settings.sources if s.id == "treasury_press")
        now = datetime(2026, 10, 2, 13, 0, tzinfo=UTC)
        manifest = b'{"searchShards":[{"name":"2026","path":"/news-data/press-releases/search/2026.json"}]}'
        shard = (b'{"items":[{"datetime":"2026-10-01T17:00:00Z","title":"Treasury Sanctions Network","url":"/news/press-releases/sb0644/",'
                 b'"subcategory":{"title":"Readouts"}},{"datetime":"2026-10-01T23:15:00Z","title":"No link"}]}')
        fetcher = FakeFetcher([FetchResult("https://home.treasury.gov/news-data/press-releases/search/2026.json", 200, shard)])
        parsed = parse_treasury_press(src, manifest, now, fetcher)
        self.assertEqual(len(parsed.items), 1)
        it = parsed.items[0]
        self.assertEqual((it["url"], it["published_utc"], it["extra"]),
                         ("https://home.treasury.gov/news/press-releases/sb0644/", "2026-10-01T17:00:00+00:00", {"subcategory": "Readouts"}))
        self.assertEqual(parsed.entries, 2)

    def test_day_only_rss_source_is_stamped_the_same_way(self):
        from reader.collect import parse_feed
        settings = load_settings()
        src = next(s for s in settings.sources if s.id == "bis_press")
        now = datetime(2026, 10, 1, 14, 0, tzinfo=UTC)
        body = (b'<?xml version="1.0"?><rss version="2.0"><channel><title>t</title><item><title>Basel Committee meets</title>'
                b'<link>https://www.bis.org/press/p261001.htm</link><pubDate>Thu, 01 Oct 2026 00:00:00 GMT</pubDate></item></channel></rss>')
        parsed = parse_feed(src, body, now, None, self.NY)
        self.assertEqual(parsed.items[0]["published_utc"], "2026-10-01T14:00:00+00:00")
        self.assertTrue(parsed.items[0]["extra"]["day_only"])
