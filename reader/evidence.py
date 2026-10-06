"""Independent re-retrieval of the sources behind each claim, for the checker.

The checker never reuses the analyst's view of a source. For journalism it re-reads the
publisher's own feed (or, failing that, checks the article page's title); for official
sources and company releases it reads the page itself. Article bodies from news sites are
never fetched for the model.
"""

from __future__ import annotations

import json

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import feedparser

from .config import Settings
from .guards import excerpt, title_similarity
from .net import Fetcher, canonical_url, clean_text, html_to_text, page_meta
from .store import parse_iso, utcnow
from .timewindow import fmt_time


@dataclass
class Evidence:
    item_id: str
    publisher: str
    section: str
    tier: int
    owner: str
    kind: str
    url: str
    published_utc: str
    title: str
    text: str
    note: str
    reconfirmed: bool
    day_only: bool = False  # the source gave a date, not a time; the brief prints the day


def _extra(item: dict) -> dict:
    extra = item.get("extra") or {}
    return json.loads(extra) if isinstance(extra, str) else extra


class _FeedCache:
    """One fresh fetch per feed during the check stage, shared across threads."""

    def __init__(self, fetcher: Fetcher):
        self.fetcher = fetcher
        self.cache: dict[str, dict[str, tuple[str, str]] | None] = {}
        self.locks: dict[str, threading.Lock] = {}
        self.guard = threading.Lock()

    def entries(self, url: str) -> dict[str, tuple[str, str]] | None:
        with self.guard:
            lock = self.locks.setdefault(url, threading.Lock())
        with lock:
            if url not in self.cache:
                res = self.fetcher.get(url, accept="application/rss+xml, application/xml;q=0.9, */*;q=0.5")
                if not res.ok:
                    self.cache[url] = None
                else:
                    feed = feedparser.parse(res.body)
                    self.cache[url] = {
                        canonical_url(e.get("link", "")): (clean_text(e.get("title")), clean_text(e.get("summary") or e.get("description"))[:700])
                        for e in feed.entries if e.get("link")
                    }
            return self.cache[url]


def gather(items: list[dict], settings: Settings, fetcher: Fetcher, queries: dict[str, list[str]]) -> dict[str, Evidence]:
    feeds = _FeedCache(fetcher)
    tz = settings.tz

    def one(item: dict) -> Evidence:
        src = settings.source(item["source_id"])
        now = utcnow()
        clock = fmt_time(now, tz)
        title, summary = item["title"], item.get("summary") or ""
        reconfirmed = False
        if item["kind"] == "news":
            entries = feeds.entries(src.url)
            fresh = entries.get(canonical_url(item["url"])) if entries else None
            if fresh:
                title, summary = fresh[0] or title, fresh[1]
                note = f"Re-read in the publisher's feed at {clock}"
                reconfirmed = True
            else:
                res = fetcher.get(item["url"], max_bytes=400_000, accept="text/html")
                if res.ok and title_similarity(page_meta(res.text()).get("title", ""), item["title"]) >= 0.5:
                    note = f"No longer in the feed; article page checked at {clock}, title matches"
                    reconfirmed = True
                elif res.ok:
                    note = "No longer in the feed; article page title differs from the feed copy"
                else:
                    first_seen = fmt_time(parse_iso(item["first_seen_utc"]), tz, now)
                    note = f"No longer in the feed and the page can't be checked ({res.error}); using the feed copy collected {first_seen}"
            text = title + (f"\n{summary}" if summary else "")
        else:
            res = fetcher.get(item["url"], max_bytes=2_000_000, accept="text/html,application/xhtml+xml")
            if res.ok and res.is_html:
                body = excerpt(html_to_text(res.text()), queries.get(item["id"], []) + [item["title"]])
                text = f"{title}\n{body}"
                note = f"Source page read directly at {clock}"
                reconfirmed = True
            else:
                why = "linked file is not a web page" if res.ok else (res.error or "unavailable")
                text = title + (f"\n{summary}" if summary else "")
                note = f"Source page not read ({why}); using the feed copy"
        return Evidence(
            item_id=item["id"], publisher=item["publisher"], section=item["section"], tier=item["tier"],
            owner=item["owner"], kind=item["kind"], url=item["url"], published_utc=item["published_utc"],
            title=title, text=text, note=note, reconfirmed=reconfirmed, day_only=bool(_extra(item).get("day_only")),
        )

    with ThreadPoolExecutor(max_workers=6) as pool:
        return {ev.item_id: ev for ev in pool.map(one, items)}
