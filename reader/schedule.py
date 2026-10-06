"""Hand-entered release schedule (config/calendar.toml) for calendars that refuse automated access.

BLS, BEA and TreasuryDirect publish their schedules once a year, so the dates are typed in by hand
with the page they came from. Code cites that page; no model touches this file.
"""

from __future__ import annotations

import hashlib
import tomllib
from datetime import date

from .config import CONFIG_DIR
from .store import Store


def load_static_calendar(store: Store, path=CONFIG_DIR / "calendar.toml") -> list[str]:
    """Upserts every event in the file into the calendar table; returns notes on anything skipped."""
    if not path.exists():
        return []
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    notes: list[str] = []
    for ev in raw.get("event", []):
        try:
            day = ev["date"] if isinstance(ev["date"], date) else date.fromisoformat(str(ev["date"]))
            title, publisher, url = ev["title"].strip(), ev["publisher"].strip(), ev["url"].strip()
        except (KeyError, ValueError, AttributeError) as e:
            notes.append(f"calendar.toml: skipped an entry ({e}): {ev}")
            continue
        store.upsert_calendar({
            "id": "config-" + hashlib.sha1(f"{day.isoformat()}|{title}".encode()).hexdigest()[:10],
            "event_date": day.isoformat(), "title": title, "source_id": None,
            "publisher": publisher, "url": url, "origin": "config",
        })
    return notes
