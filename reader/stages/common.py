"""Shared prompt text and formatting for the pipeline stages."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo

from ..store import parse_iso
from ..timewindow import fmt_day, fmt_time, is_trading_day, next_trading_days

AUDIENCE = """The reader is a senior executive at a large U.S. bank. By 7 a.m. New York time they must be ready to lead \
the first pre-market conversation with the heads of equities trading, wealth management and investment banking. \
The test for every story: would the CEO of JPMorgan, Bank of America, Goldman Sachs or Morgan Stanley want it in hand \
before the open? U.S. markets come first; what happened in Asia and Europe overnight matters as context for the U.S. session. \
A development is material if it can move a major stock (roughly S&P 100), a whole industry, or the broad market, \
or if it is a government, central bank, regulatory or court action with a clear path to markets. Politics and foreign \
affairs qualify only through that path: trade, sanctions, fiscal or monetary policy, regulation, supply, a named company \
or a defined sector."""

TIER_LABEL = {0: "primary source", 1: "tier 1 outlet", 2: "tier 2 outlet"}


@dataclass
class Window:
    start: datetime
    end: datetime
    tz: str

    def describe(self) -> str:
        end = self.end.astimezone(ZoneInfo(self.tz))
        return (f"from {fmt_time(self.start, self.tz, self.end)} to {fmt_time(self.end, self.tz)} on "
                f"{end.strftime('%A, %B')} {end.day}, {end.year} (New York time)")

    def today(self) -> str:
        end = self.end.astimezone(ZoneInfo(self.tz))
        return f"{end.strftime('%A, %B')} {end.day}, {end.year}"

    def next_session(self) -> str:
        """'today' when the brief runs before a trading day's open; otherwise the day, e.g. 'Monday, Sep 28'."""
        end = self.end.astimezone(ZoneInfo(self.tz))
        if is_trading_day(end.date()) and end.time() < time(9, 30):
            return "today"
        day = next_trading_days(end.date(), 1)[0]
        return f"{day.strftime('%A')}, {fmt_day(day)[5:]}"


@dataclass
class Session:
    """The previous U.S. trading day's news that no overnight window covers: from that day's brief (or the
    package time, when no brief ran) to the close. See reader/session.py."""
    start: datetime
    end: datetime
    tz: str
    after_brief: bool = False  # the start is when that day's brief was written, not the package time

    def day(self) -> str:
        """'Monday'."""
        return self.end.astimezone(ZoneInfo(self.tz)).strftime("%A")

    def describe(self) -> str:
        """'Monday, October 5, from 9:39 AM to the 4:00 PM close (New York time)'."""
        end = self.end.astimezone(ZoneInfo(self.tz))
        return (f"{end.strftime('%A, %B')} {end.day}, from {fmt_time(self.start, self.tz)} to the "
                f"{fmt_time(self.end, self.tz)} close (New York time)")


def item_line(ref: str, item: dict, tz: str, now: datetime, summary_chars: int) -> str:
    when = fmt_time(parse_iso(item["published_utc"]), tz, now)
    head = f"[{ref}] {item['publisher']} · {item['section']} · {TIER_LABEL.get(item['tier'], '')} · {when}"
    body = item["title"]
    summary = (item.get("summary") or "")[:summary_chars]
    if summary:
        body += f"\n{summary}"
    return f"{head}\n{body}"


def ref_of(value: str | None, prefix: str) -> str | None:
    """Normalise a model-written reference such as '[A12]', 'a12' or 'A12:' to 'A12'."""
    m = re.fullmatch(rf"\s*\[?\s*{prefix}\s*(\d+)\s*\]?\s*[:.]?\s*", value or "", re.I)
    return f"{prefix}{m.group(1)}" if m else None


def refs(prefix: str, rows: list) -> dict[str, object]:
    return {f"{prefix}{i}": row for i, row in enumerate(rows, start=1)}
