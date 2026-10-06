"""Collector: fetch every active source, keep what's in scope, store it. No AI, no cost.

Run it on its own every 30-60 minutes overnight (`./brief collect`) so fast-moving feeds
that only show their latest ~20 items are captured in full by morning. Each check records
the publication times its feed spans; when every entry is newer than anything the previous
check saw, the feed turned over in between and the check is logged as a possible gap.
"""

from __future__ import annotations

import calendar as _calendar
import hashlib
import json
import re
import time as _time
import urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import feedparser

from .config import Settings, Source, company_pattern
from .net import Fetcher, FetchResult, canonical_url, clean_text, html_to_text, page_meta
from .store import Store, iso, parse_iso, utcnow

RETRY_PAUSE = 5  # seconds before the one retry of a failed fetch


# Law-firm solicitations ("investor alert", "class action deadline") name large companies but aren't news.
_SOLICITATION = re.compile(
    r"(?i)\b(?:class action|securities (?:fraud|litigation)|investor alert|shareholder alert|deadline alert|"
    r"lead plaintiff|fiduciary duties|reminds (?:investors|shareholders)|encourages (?:investors|shareholders)|"
    r"notifies (?:investors|shareholders)|on behalf of (?:investors|shareholders)|investigates claims|"
    r"investors? (?:who|with) losses|announces (?:an )?investigation|law firm|INV Deadline)"
)


def item_id(url: str) -> str:
    return "i" + hashlib.sha1(canonical_url(url).encode()).hexdigest()[:10]


@dataclass
class SourceStatus:
    source: Source
    status: str  # ok | error text
    entries: int = 0
    new: int = 0
    kept: int = 0
    gap_since: datetime | None = None  # the feed turned over completely after this earlier check


@dataclass
class Parsed:
    items: list[dict]
    entries: int
    oldest: datetime | None = None  # publication times across every dated entry, kept or not;
    newest: datetime | None = None  # they show whether the feed turned over between two checks

    def see(self, published: datetime) -> None:
        self.oldest = min(self.oldest or published, published)
        self.newest = max(self.newest or published, published)


@dataclass
class CollectReport:
    started: datetime
    statuses: list[SourceStatus] = field(default_factory=list)

    @property
    def new_items(self) -> int:
        return sum(s.new for s in self.statuses)

    @property
    def failures(self) -> list[SourceStatus]:
        return [s for s in self.statuses if s.status != "ok"]

    @property
    def gaps(self) -> list[SourceStatus]:
        return [s for s in self.statuses if s.gap_since]


# ------------------------------------------------------------------ parsers

def _tagged(entry, categories: tuple[str, ...]) -> bool:
    wanted = {c.lower() for c in categories}
    return any((t.get("term") or "").strip().lower() in wanted for t in entry.get("tags") or [])


def day_only_stamp(day: date, now: datetime, tz: ZoneInfo) -> datetime:
    """A publication time for a source that gives only a date. The collector runs every 30 minutes, so
    an item dated today was published within half an hour of its first sighting: stamp it now. An
    older date (the backlog on a first fetch) is stamped at noon, local time, and the item carries
    extra.day_only so the brief prints the day and never the clock time."""
    if day == now.astimezone(tz).date():
        return now
    return datetime(day.year, day.month, day.day, 12, 0, tzinfo=tz).astimezone(timezone.utc)


def parse_feed(src: Source, body: bytes, now: datetime, company_re: re.Pattern | None,
               tz: ZoneInfo | None = None) -> Parsed:
    feed = feedparser.parse(body)
    out = Parsed([], len(feed.entries))
    for e in feed.entries:
        link = (e.get("link") or "").strip()
        title = clean_text(e.get("title"))
        stamp = e.get("published_parsed") or e.get("updated_parsed")
        if not link or not title or not stamp:
            continue  # an undated item can't meet the date standard
        if src.categories and not _tagged(e, src.categories):
            continue
        published = datetime.fromtimestamp(_calendar.timegm(stamp), timezone.utc)
        if published > now + timedelta(hours=1):
            continue  # malformed future timestamp
        extra = {}
        if src.day_only:
            published = day_only_stamp(published.date(), now, tz or ZoneInfo("America/New_York"))
            extra["day_only"] = True
        out.see(published)
        summary = clean_text(e.get("summary") or e.get("description"))[:700]
        if summary.lower() == title.lower():
            summary = ""
        if src.kind == "wire":
            match = company_re.search(f"{title} {summary}") if company_re else None
            if not match or _SOLICITATION.search(f"{title} {summary}"):
                continue
            extra["company"] = match.group(0)
        out.items.append(_item(src, link, title, summary, published, extra))
    return out


_SITEMAP = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9", "n": "http://www.google.com/schemas/sitemap-news/0.9"}


def parse_news_sitemap(src: Source, body: bytes, now: datetime, company_re: re.Pattern | None,
                       tickers: dict[str, str]) -> Parsed:
    """A wire's Google News sitemap: 100 releases to a page, where its RSS feed shows 20.

    Entries carry a title, a publication time and the issuer's stock tickers, but no summary,
    so a release is kept when its title names a watchlist company or its tickers list one.
    English only; the translations repeat the same releases.
    """
    urls = ET.fromstring(body).findall("s:url", _SITEMAP)
    out = Parsed([], len(urls))
    for u in urls:
        link = (u.findtext("s:loc", "", _SITEMAP) or "").strip()
        news = u.find("n:news", _SITEMAP)
        if not link or news is None:
            continue
        title = clean_text(news.findtext("n:title", "", _SITEMAP))
        try:
            published = datetime.fromisoformat((news.findtext("n:publication_date", "", _SITEMAP) or "").strip())
        except ValueError:
            continue
        if not title or published.tzinfo is None:
            continue  # a date with no time zone can't be placed in the window
        published = published.astimezone(timezone.utc)
        if published > now + timedelta(hours=1):
            continue
        out.see(published)
        language = (news.findtext("n:publication/n:language", "", _SITEMAP) or "").lower()
        if language and not language.startswith("en"):
            continue
        match = company_re.search(title) if company_re else None
        company = match.group(0) if match else _ticker_company(news.findtext("n:stock_tickers", "", _SITEMAP) or "", tickers)
        if not company or _SOLICITATION.search(title):
            continue
        out.items.append(_item(src, link, title, "", published, {"company": company}))
    return out


def _ticker_company(field: str, tickers: dict[str, str]) -> str | None:
    """The watchlist company whose U.S. listing is among a release's tickers ("NYSE:JPM,ISIN:...")."""
    for part in field.split(","):
        exchange, _, symbol = part.strip().partition(":")
        if exchange.upper().startswith(("NYSE", "NASDAQ")) and symbol in tickers:
            return tickers[symbol]
    return None


_EJ_EDITION = re.compile(
    r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+(\d{1,2})/(\d{1,2})/(\d{4})\s+(a\.m\.|p\.m\.)\s+(.{8,160}?)\s+[–—]\s"
)


def parse_edward_jones(src: Source, body: bytes, tz: ZoneInfo) -> list[dict]:
    """Title, edition date and author of the current Daily Market Snapshot. The body is discarded."""
    page = body.decode("utf-8", "replace")
    m = _EJ_EDITION.search(html_to_text(page).replace("\n", " "))
    if not m:
        return []
    _, month, day, year, ampm, headline = m.groups()
    edition_day = date(int(year), int(month), int(day))
    # Only the edition (a.m./p.m.) is published, not a clock time; this stamp is used for windowing only.
    stamp = datetime.combine(edition_day, time(16, 30) if ampm == "p.m." else time(9, 0), tz)
    meta = page_meta(page)
    extra = {"edition": f"{edition_day.isoformat()} {ampm}", "author": meta.get("author", "")}
    edition_key = f"{src.url}?edition={edition_day.isoformat()}-{ampm[0]}"
    return [_item(src, src.url, headline.strip(), "", stamp, extra, id_key=edition_key)]


_FOMC_YEAR = re.compile(r"(\d{4}) FOMC Meetings")
_FOMC_ROW = re.compile(
    r"fomc-meeting__month[^>]*>\s*<strong>([^<]+)</strong>.*?fomc-meeting__date[^>]*>([^<]+)<", re.S
)
_MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"], start=1)}


def parse_fomc(src: Source, body: bytes) -> list[dict]:
    page = body.decode("utf-8", "replace")
    events = []
    heads = list(_FOMC_YEAR.finditer(page))
    for i, head in enumerate(heads):
        year = int(head.group(1))
        segment = page[head.end(): heads[i + 1].start() if i + 1 < len(heads) else len(page)]
        for month_text, days_text in _FOMC_ROW.findall(segment):
            months = [m.strip() for m in month_text.split("/")]
            days = re.findall(r"\d{1,2}", days_text)
            if not days or months[-1] not in _MONTHS:
                continue
            decision_day = date(year, _MONTHS[months[-1]], int(days[-1]))
            projections = "*" in days_text
            title = "FOMC rate decision" + (" and economic projections" if projections else "")
            events.append({
                "id": f"fomc-{decision_day.isoformat()}",
                "event_date": decision_day.isoformat(),
                "title": title,
                "source_id": src.id, "publisher": src.publisher, "url": src.url, "origin": "schedule",
            })
    return events


def parse_treasury_auctions(src: Source, body: bytes) -> list[dict]:
    try:
        rows = json.loads(body)
    except ValueError:
        return []
    events = []
    for r in rows:
        kind = (r.get("securityType") or "").strip()
        if kind not in ("Note", "Bond", "TIPS", "FRN"):
            continue  # bills are routine
        auction = (r.get("auctionDate") or "")[:10]
        term = (r.get("securityTerm") or "").strip()
        if not auction or not term:
            continue
        label = f"{term} {'TIPS' if kind == 'TIPS' else kind.lower() + 's'}".replace("-Year", "-year")
        events.append({
            "id": f"ust-{r.get('cusip', '')}-{auction}",
            "event_date": auction,
            "title": f"Treasury auction: {label}",
            "source_id": src.id, "publisher": src.publisher,
            "url": "https://www.treasurydirect.gov/auctions/upcoming/", "origin": "schedule",
        })
    return events


def _item(src: Source, link: str, title: str, summary: str, published: datetime, extra: dict,
          id_key: str | None = None) -> dict:
    return {
        "id": item_id(id_key or link),
        "source_id": src.id,
        "publisher": src.publisher,
        "section": src.section,
        "kind": src.kind,
        "tier": src.tier,
        "owner": src.owner,
        "title": title,
        "summary": summary,
        "url": link,
        "published_utc": iso(published),
        "model_ok": src.model_ok,
        "extra": extra,
    }


_FDIC_ROW = re.compile(r'<time datetime="(\d{4}-\d{2}-\d{2})"[^>]*>.*?<a href="([^"]+)" rel="bookmark">\s*<span>(.*?)</span>', re.S)
_NYFED_ROW = re.compile(r'<tr class="\s*([^"]*?)\s*" valign="top">\s*<td[^>]*>\s*<div>\s*([A-Z][a-z]{2} \d{1,2}, \d{4})\s*</div>\s*</td>'
                        r'.*?<a href="([^"]+)" class="paraHeader">(.*?)</a>', re.S)
NYFED_SECTIONS = ("Markets", "Banking", "Research")


def parse_fdic_press(src: Source, body: bytes, now: datetime, tz: ZoneInfo) -> Parsed:
    """The FDIC's press-release index page (fdic.gov/news/press-releases): date and title per row, no time."""
    page = body.decode("utf-8", "replace")
    out = Parsed([], 0)
    for day_text, href, title in _FDIC_ROW.findall(page):
        out.entries += 1
        day = date.fromisoformat(day_text)
        published = day_only_stamp(day, now, tz)
        out.see(published)
        out.items.append(_item(src, urllib.parse.urljoin(src.url, href), clean_text(title), "", published, {"day_only": True}))
    return out


def parse_nyfed_news(src: Source, body: bytes, now: datetime, tz: ZoneInfo, days: int = 10,
                     sections: tuple[str, ...] = NYFED_SECTIONS) -> Parsed:
    """The New York Fed's news index (newyorkfed.org/newsevents/news): years of rows, dated without times.
    Keeps rows from the last `days` days in the given sections; an empty `sections` keeps every row, which
    is how the speeches page (newyorkfed.org/newsevents/speeches), same markup and no sections, is read."""
    page = body.decode("utf-8", "replace")
    out = Parsed([], 0)
    floor = now.astimezone(tz).date() - timedelta(days=days)
    for classes, day_text, href, title in _NYFED_ROW.findall(page):
        out.entries += 1
        try:
            day = datetime.strptime(day_text, "%b %d, %Y").date()
        except ValueError:
            continue
        if day < floor or (sections and not any(s in classes for s in sections)):
            continue
        published = day_only_stamp(day, now, tz)
        out.see(published)
        extra = {"day_only": True}
        if sections:
            extra["nyfed_section"] = next(s for s in sections if s in classes)
        out.items.append(_item(src, urllib.parse.urljoin(src.url, href), clean_text(title), "", published, extra))
    return out


def parse_treasury_press(src: Source, body: bytes, now: datetime, fetcher=None) -> Parsed:
    """Treasury's press-release listing is JSON: a manifest (`searchShards`) pointing at one file per year,
    each with title, url and a full timestamp. The source URL is the manifest, so no year is typed in;
    the newest shard is fetched through the same fetcher (robots and all)."""
    data = json.loads(body.decode("utf-8", "replace"))
    if "searchShards" in data:
        if fetcher is None:
            raise ValueError("treasury manifest needs a fetcher to follow its newest shard")
        shard = urllib.parse.urljoin(src.url, data["searchShards"][0]["path"])
        res = fetcher.get(shard, accept="application/json")
        if not res.ok:
            raise ValueError(f"shard {shard}: {res.error or res.status}")
        data = json.loads(res.text())
    out = Parsed([], 0)
    for entry in data.get("items", []):
        out.entries += 1
        stamp, title, href = entry.get("datetime"), entry.get("title"), entry.get("url")
        if not (stamp and title and href):
            continue
        published = parse_iso(stamp.replace("Z", "+00:00"))
        if published > now + timedelta(hours=1):
            continue
        out.see(published)
        sub = (entry.get("subcategory") or {}).get("title")
        out.items.append(_item(src, urllib.parse.urljoin(src.url, href), clean_text(title), "", published,
                               {"subcategory": sub} if sub else {}))
    return out


# ------------------------------------------------------------------ collection

def _accept_for(src: Source) -> str:
    if src.format == "rss":
        return "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5"
    if src.format in ("treasury_auctions", "treasury_press"):
        return "application/json"
    if src.format == "news_sitemap":
        return "application/xml, text/xml;q=0.9, */*;q=0.5"
    return "text/html,application/xhtml+xml"


def collect(settings: Settings, store: Store, fetcher: Fetcher, now: datetime | None = None) -> CollectReport:
    now = now or utcnow()
    tz = ZoneInfo(settings.tz)
    report = CollectReport(started=now)
    sources = settings.active_sources()
    company_re = company_pattern(settings.companies)
    tickers = {c.ticker: c.name for c in settings.companies}

    def fetch(src: Source) -> tuple[Source, FetchResult]:
        res = fetcher.get(src.url, accept=_accept_for(src))
        if not res.ok and not res.robots_blocked:
            _time.sleep(RETRY_PAUSE)  # a 502, a timeout or a stray 404 usually clears within seconds
            res = fetcher.get(src.url, accept=_accept_for(src))
        return src, res

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(fetch, sources))

    for src, res in results:
        if not res.ok:
            status = SourceStatus(src, res.error or f"HTTP {res.status}")
            report.statuses.append(status)
            store.log_fetch(src.id, status.status, 0, 0, 0)
            continue
        try:
            if src.format == "rss":
                parsed = parse_feed(src, res.body, now, company_re if src.kind == "wire" else None, tz)
            elif src.format == "fdic_press":
                parsed = parse_fdic_press(src, res.body, now, tz)
            elif src.format == "nyfed_news":
                parsed = parse_nyfed_news(src, res.body, now, tz)
            elif src.format == "nyfed_speeches":
                parsed = parse_nyfed_news(src, res.body, now, tz, sections=())
            elif src.format == "treasury_press":
                parsed = parse_treasury_press(src, res.body, now, fetcher)
            elif src.format == "news_sitemap":
                parsed = parse_news_sitemap(src, res.body, now, company_re, tickers)
            elif src.format == "edward_jones":
                items = parse_edward_jones(src, res.body, tz)
                parsed = Parsed(items, len(items))
            elif src.format == "fomc":
                events = parse_fomc(src, res.body)
                for ev in events:
                    store.upsert_calendar(ev)
                report.statuses.append(SourceStatus(src, "ok", len(events), 0, len(events)))
                store.log_fetch(src.id, "ok", len(events), 0, len(events))
                continue
            elif src.format == "treasury_auctions":
                events = parse_treasury_auctions(src, res.body)
                for ev in events:
                    store.upsert_calendar(ev)
                report.statuses.append(SourceStatus(src, "ok", len(events), 0, len(events)))
                store.log_fetch(src.id, "ok", len(events), 0, len(events))
                continue
            else:
                raise ValueError(f"unknown format {src.format}")
        except Exception as e:  # a malformed feed shouldn't stop the others
            status = SourceStatus(src, f"parse error: {type(e).__name__}: {e}"[:160])
            report.statuses.append(status)
            store.log_fetch(src.id, status.status, 0, 0, 0)
            continue
        gap_since = None
        if parsed.oldest:
            last = store.last_span(src.id)
            if last and parsed.oldest > parse_iso(last["newest_utc"]):
                gap_since = parse_iso(last["fetched_utc"])  # every entry is newer than anything seen then
        new = sum(store.upsert_item(it) for it in parsed.items)
        report.statuses.append(SourceStatus(src, "ok", parsed.entries, new, len(parsed.items), gap_since))
        store.log_fetch(src.id, "ok", parsed.entries, new, len(parsed.items),
                        parsed.oldest, parsed.newest, gap=gap_since is not None)
    return report
