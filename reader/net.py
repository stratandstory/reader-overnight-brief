"""Polite fetching: an honest User-Agent, robots.txt respected, timeouts and size caps."""

from __future__ import annotations

import html
import json
import re
import ssl
import threading
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from dataclasses import dataclass


def tls_context() -> ssl.SSLContext:
    """Certificate authorities from certifi when it is installed. Python from python.org on a Mac ships with
    none of its own, and without them every HTTPS fetch, robots.txt included, fails verification."""
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


@dataclass
class FetchResult:
    url: str
    status: int | None
    body: bytes = b""
    error: str | None = None
    robots_blocked: bool = False
    content_type: str = ""

    @property
    def is_html(self) -> bool:
        head = self.body[:2000].lower()
        return "html" in self.content_type or b"<html" in head or b"<!doctype html" in head

    @property
    def ok(self) -> bool:
        return self.status is not None and 200 <= self.status < 300 and not self.error

    def text(self) -> str:
        return self.body.decode("utf-8", "replace")


class Fetcher:
    def __init__(self, user_agent: str, timeout: float = 20):
        self.user_agent = user_agent
        self.timeout = timeout
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._lock = threading.Lock()
        self._tls = tls_context()

    def _robots_for(self, url: str) -> urllib.robotparser.RobotFileParser | None:
        """Parsed robots.txt, or None when the file is unreachable (treated as 'disallow').

        Follows RFC 9309: a 4xx means no restrictions; a 5xx or network failure means
        the crawler must assume it is not allowed.
        """
        parts = urllib.parse.urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        with self._lock:
            if base in self._robots:
                return self._robots[base]
        parser: urllib.robotparser.RobotFileParser | None = urllib.robotparser.RobotFileParser()
        try:
            req = urllib.request.Request(base + "/robots.txt", headers={"User-Agent": self.user_agent})
            with urllib.request.urlopen(req, timeout=self.timeout, context=self._tls) as resp:
                parser.parse(resp.read(500_000).decode("utf-8", "replace").splitlines())
        except urllib.error.HTTPError as e:
            if 400 <= e.code < 500 and e.code != 429:
                parser.parse([])
            else:
                parser = None
        except Exception:
            parser = None
        with self._lock:
            self._robots[base] = parser
        return parser

    def allowed(self, url: str) -> bool:
        parser = self._robots_for(url)
        return parser is not None and parser.can_fetch(self.user_agent, url)

    def get(self, url: str, max_bytes: int = 3_000_000, accept: str = "*/*") -> FetchResult:
        if not self.allowed(url):
            return FetchResult(url, None, error="robots.txt disallows or is unreachable", robots_blocked=True)
        req = urllib.request.Request(url, headers={"User-Agent": self.user_agent, "Accept": accept})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=self._tls) as resp:
                return FetchResult(resp.geturl(), resp.status, resp.read(max_bytes),
                                   content_type=resp.headers.get("Content-Type", "").lower())
        except urllib.error.HTTPError as e:
            return FetchResult(url, e.code, error=f"HTTP {e.code}")
        except Exception as e:  # timeouts, DNS, TLS
            return FetchResult(url, None, error=f"{type(e).__name__}: {e}"[:160])


# ------------------------------------------------------------------ text helpers

_WS = re.compile(r"\s+")
_COMMENT = re.compile(r"(?s)<!--.*?-->")
_TAG = re.compile(r"<[^>]+>")
_DROP_BLOCKS = re.compile(
    r"(?is)<(script|style|noscript|svg|nav|header|footer|aside|form|iframe)\b[^>]*>.*?</\1>"
)
_BREAKS = re.compile(r"(?i)</(p|div|li|h[1-6]|tr|section|article|blockquote)>|<br\s*/?>")


def clean_text(s: str | None) -> str:
    """Strip tags and entities from a feed field; collapse whitespace."""
    if not s:
        return ""
    s = _TAG.sub(" ", s)
    return _WS.sub(" ", html.unescape(s)).strip()


# Where the substance of a page usually starts; site banners and menus come before it.
_CONTENT_START = re.compile(
    r'(?i)<main\b|<article\b|role="main"|id="(?:article|content|main-content|maincontent|main)"'
)


def html_to_text(page: str) -> str:
    """Readable text with paragraph breaks, for primary-source pages, starting at the main content region."""
    page = _COMMENT.sub(" ", page)
    m = _CONTENT_START.search(page)
    if m and len(page) - m.start() > 500:
        page = page[max(0, page.rfind("<", 0, m.start() + 1)):]  # from the start of the enclosing tag
    page = _DROP_BLOCKS.sub(" ", page)
    page = _BREAKS.sub("\n", page)
    page = _TAG.sub(" ", page)
    page = html.unescape(page)
    lines = [_WS.sub(" ", ln).strip() for ln in page.split("\n")]
    return "\n".join(ln for ln in lines if len(ln) > 1)


_META = re.compile(r"<meta\s[^>]*>", re.I)
_ATTR = re.compile(r'([a-zA-Z:_-]+)\s*=\s*("([^"]*)"|\'([^\']*)\')')


def page_meta(page: str) -> dict[str, str]:
    """Title, site name, author and publication times declared in a page's <head>."""
    head = page[:300_000]
    out: dict[str, str] = {}
    wanted = {
        "og:title": "title", "og:site_name": "site", "author": "author",
        "article:published_time": "published", "article:modified_time": "modified",
        "parsely-pub-date": "published_day",
    }
    for tag in _META.findall(head):
        attrs = {m.group(1).lower(): (m.group(3) if m.group(3) is not None else m.group(4)) for m in _ATTR.finditer(tag)}
        key = (attrs.get("property") or attrs.get("name") or attrs.get("itemprop") or "").lower()
        if key in wanted and attrs.get("content") and wanted[key] not in out:
            out[wanted[key]] = html.unescape(attrs["content"]).strip()
    for m in re.finditer(r'(?is)<script[^>]+application/ld\+json[^>]*>(.*?)</script>', head):
        try:
            data = json.loads(m.group(1))
        except Exception:
            continue
        for obj in data if isinstance(data, list) else [data]:
            if isinstance(obj, dict):
                if "published" not in out and isinstance(obj.get("datePublished"), str):
                    out["published"] = obj["datePublished"]
                if "modified" not in out and isinstance(obj.get("dateModified"), str):
                    out["modified"] = obj["dateModified"]
    if "title" not in out:
        m = re.search(r"(?is)<title[^>]*>(.*?)</title>", head)
        if m:
            out["title"] = clean_text(m.group(1))
    return out


def canonical_url(url: str) -> str:
    """Drop fragments and tracking parameters so the same story dedupes across feeds.

    http and https count as one address: the Bank of Japan's feed switches between them
    from one fetch to the next, which stored every item twice.
    """
    parts = urllib.parse.urlsplit(url.strip())
    scheme = parts.scheme.lower()
    if scheme == "http":
        scheme = "https"
    query = [
        (k, v) for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith(("utm_", "mod", "cmpid", "ref", "src", "__"))
    ]
    return urllib.parse.urlunsplit(
        (scheme, parts.netloc.lower(), parts.path, urllib.parse.urlencode(query), "")
    )
