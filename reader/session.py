"""The previous trading day's highlights: news that no overnight window covers.

The brief covers the time since the U.S. close, and each brief's window ends when it is written, so news
reported during the trading day reached no brief at all: about as many items as a night holds. On Monday,
October 5, that was the Pentagon dropping Anthropic's tools (BBC, 12:13 PM) and Microsoft cutting its
internal Claude spending by a third (The Information, 2:14 PM); DealBook led with both the next morning.

The previous session runs from that day's brief (or the package time, when no brief ran) to the close.
Its items go through the same screen, analyst, checker, editor and audit as the night's, in the same calls,
so the analyst sees a session story and its overnight follow-up together and makes them one story. Code then
decides, from the sources behind each story, which stories are the session's own: those whose every source
was published in the session. At most `max_stories` of them, each at or above `min_materiality`, are printed
in a section of their own; a story with any overnight source is overnight news.
"""

from __future__ import annotations

import json
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from .config import Settings
from .stages.common import Session, Window
from .store import Store, iso
from .timewindow import previous_close


def settings_for(settings: Settings) -> dict:
    cfg = settings.raw.get("session", {})
    return {"enabled": bool(cfg.get("enabled", False)), "analyst_items": int(cfg.get("analyst_items", 60)),
            "min_materiality": int(cfg.get("min_materiality", 3)), "max_stories": int(cfg.get("max_stories", 3))}


def bounds(settings: Settings, store: Store, window: Window) -> Session | None:
    """The session before `window`, or None when it is switched off or would be empty. A window the lookback cap
    shortened (a long market closure) gets no session: that trading day is too far back to brief."""
    if not settings_for(settings)["enabled"]:
        return None
    tz = ZoneInfo(settings.tz)
    close = previous_close(window.end, tz, settings.raw["window"]["close_hour"])
    if abs((close - window.start).total_seconds()) > 60:
        return None
    hour, minute = (int(x) for x in settings.raw["window"].get("package_time", "06:30").split(":"))
    start = datetime.combine(close.date(), time(hour, minute), tz)
    last = store.last_brief_end(start, close)
    if last:
        start = last
    if start >= close:
        return None
    return Session(start.astimezone(timezone.utc), close.astimezone(timezone.utc), settings.tz, after_brief=last is not None)


def items(store: Store, session: Session) -> list[dict]:
    """The session's items. Both ends are open: an item at the start was in that day's brief, and one at the
    close opens the overnight window."""
    lo, hi = iso(session.start), iso(session.end)
    rows = [r for r in store.items_in_window(session.start, session.end) if lo < r["published_utc"] < hi]
    for r in rows:
        r["extra"] = json.loads(r.get("extra") or "{}") if isinstance(r.get("extra"), str) else (r.get("extra") or {})
    return rows


def select(stories: list, settings: Settings, check_limit: int) -> tuple[list, list[str]]:
    """What goes to the checker: the overnight stories up to its limit, then the session's own stories (all of
    whose cited items are from the session) at or above the bar, up to the ceiling. Stories arrive most
    material first."""
    cfg = settings_for(settings)
    overnight = [s for s in stories if not s.session]
    session = [s for s in stories if s.session]
    keep = [s for s in session if s.materiality >= cfg["min_materiality"]][:cfg["max_stories"]]
    notes = []
    if len(overnight) > check_limit:
        notes.append(f"{len(overnight) - check_limit} lower-materiality stories not checked (limit {check_limit})")
    for s in session:
        if s not in keep:
            why = (f"below its bar of {cfg['min_materiality']}" if s.materiality < cfg["min_materiality"]
                   else f"past its ceiling of {cfg['max_stories']}")
            notes.append(f"Previous-session story not checked, {why}: {s.title} (materiality {s.materiality})")
    return overnight[:check_limit] + keep, notes


def route(checked: list, session_ids: set[str], settings: Settings) -> tuple[set[str], list, list[str]]:
    """(keys of the stories the session section may hold, the checked stories the editor sees, notes).

    Decided from the sources behind what passed the check: a story belongs to the session when every verified
    claim rests only on session items. A story the analyst built with overnight items can end up there when only
    its session claims passed; it then needs the bar as well, or it is left out, because printed among the
    overnight news it would be misdated."""
    bar = settings_for(settings)["min_materiality"]
    keys: set[str] = set()
    keep, notes = [], []
    for cs in checked:
        sources = [e.item_id for vc in cs.verified for e in vc.evidence]
        if sources and all(i in session_ids for i in sources):
            if cs.story.materiality < bar:
                notes.append(f"Left out a story whose verified claims all come from the previous session, below its "
                             f"bar of {bar}: {cs.story.title} (materiality {cs.story.materiality})")
                continue
            keys.add(cs.story.key)
        keep.append(cs)
    return keys, keep, notes
