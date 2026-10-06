"""The overnight window and the U.S. trading calendar."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

# NYSE full-day closures. Check nyse.com when adding a year.
NYSE_HOLIDAYS = {
    date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3),
    date(2026, 5, 25), date(2026, 6, 19), date(2026, 7, 3), date(2026, 9, 7),
    date(2026, 11, 26), date(2026, 12, 25),
    date(2027, 1, 1), date(2027, 1, 18), date(2027, 2, 15), date(2027, 3, 26),
    date(2027, 5, 31), date(2027, 6, 18), date(2027, 7, 5), date(2027, 9, 6),
    date(2027, 11, 25), date(2027, 12, 24),
}


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in NYSE_HOLIDAYS


def previous_close(now: datetime, tz: ZoneInfo, close_hour: int) -> datetime:
    """Most recent U.S. cash close at or before `now`."""
    local = now.astimezone(tz)
    d = local.date()
    close_today = datetime.combine(d, time(close_hour), tz)
    if is_trading_day(d) and local >= close_today:
        return close_today
    d -= timedelta(days=1)
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return datetime.combine(d, time(close_hour), tz)


def overnight_window(now: datetime, tz_name: str, close_hour: int, max_lookback_hours: int) -> tuple[datetime, datetime]:
    """(start, end) in UTC: from the previous U.S. close to now, capped for long weekends."""
    tz = ZoneInfo(tz_name)
    start = previous_close(now, tz, close_hour)
    floor = now - timedelta(hours=max_lookback_hours)
    start = max(start, floor)
    return start.astimezone(timezone.utc), now.astimezone(timezone.utc)


def next_trading_days(after: date, n: int) -> list[date]:
    out: list[date] = []
    d = after
    while len(out) < n:
        d += timedelta(days=1)
        if is_trading_day(d):
            out.append(d)
    return out


def fmt_time_or_day(dt: datetime, tz_name: str, now: datetime | None, day_only: bool) -> str:
    """fmt_time, except that a source which gave only a date is printed as a day ('today', 'Thu')."""
    if not day_only:
        return fmt_time(dt, tz_name, now)
    tz = ZoneInfo(tz_name)
    local = dt.astimezone(tz)
    if now is not None and local.date() == now.astimezone(tz).date():
        return "today"
    return local.strftime("%a")


def fmt_time(dt: datetime, tz_name: str, now: datetime | None = None) -> str:
    """'2:14 AM' for today (NY), 'Fri 4:05 PM' for earlier days."""
    tz = ZoneInfo(tz_name)
    local = dt.astimezone(tz)
    clock = local.strftime("%I:%M %p").lstrip("0")
    if now is not None and local.date() != now.astimezone(tz).date():
        return f"{local.strftime('%a')} {clock}"
    return clock


def fmt_day(d: date) -> str:
    return f"{d.strftime('%a')}, {d.strftime('%b')} {d.day}"
