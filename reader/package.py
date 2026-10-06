"""The morning package: the window a brief would cover, frozen when the brief is due. No model calls; free.

A morning nobody ran the brief is still a window of news. At the package time on a weekday this records
the window's bounds, every item in it as collected, and the feeds' health over it, plus a plain headline
list anyone can read with no model involved. `./brief run --package <date>` writes that morning's brief
later, from the frozen items, labelled as written late.

Item text is frozen when the package is written, not at the window's end: a feed can revise a headline
after it is first collected, and the store keeps only the latest wording. The package says when it was
written so the gap is visible.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import DATA_DIR, Settings
from .store import Store, iso, parse_iso
from .timewindow import fmt_day, fmt_time, overnight_window

PACKAGES_DIR = DATA_DIR / "packages"


def package_end(day: date, settings: Settings) -> datetime:
    """The package time on `day`, New York, in UTC."""
    hour, minute = (int(x) for x in settings.raw["window"].get("package_time", "06:30").split(":"))
    return datetime.combine(day, time(hour, minute), ZoneInfo(settings.tz)).astimezone(timezone.utc)


def package_dir(day: date, root: Path | None = None) -> Path:
    return (root or PACKAGES_DIR) / day.isoformat()


def make_package(settings: Settings, store: Store, day: date, now: datetime,
                 root: Path | None = None) -> tuple[Path, bool]:
    """Writes the package for `day` and returns (folder, True); returns (folder, False) if it already exists.
    A package is never rewritten. Raises ValueError before the package time."""
    folder = package_dir(day, root)
    if (folder / "package.json").exists():
        return folder, False
    end = package_end(day, settings)
    if now < end:
        raise ValueError(f"The package for {fmt_day(day)} covers news to {fmt_time(end, settings.tz)}; it is not that time yet.")
    start, end = overnight_window(end, settings.tz, settings.raw["window"]["close_hour"],
                                  settings.raw["window"]["max_lookback_hours"])
    items = store.items_in_window(start, end)
    for it in items:
        it["extra"] = json.loads(it.get("extra") or "{}")
    labels = {s.id: s for s in settings.sources}
    last = store.latest_fetches(before=end)
    sources = [{"source_id": sid, "label": labels[sid].label, "publisher": labels[sid].publisher,
                "kind": labels[sid].kind, "status": row["status"], "fetched_utc": row["fetched_utc"], "kept": row["kept"]}
               for sid, row in last.items() if sid in labels]
    gaps = [{"source_id": g["source_id"], "label": labels[g["source_id"]].label if g["source_id"] in labels else g["source_id"],
             "fetched_utc": g["fetched_utc"]} for g in store.gaps_between(start, end)]
    data = {"day": day.isoformat(), "window_start": iso(start), "window_end": iso(end), "packaged_utc": iso(now),
            "items": items, "sources": sources, "gaps": gaps}
    folder.mkdir(parents=True, exist_ok=True)
    order = list(dict.fromkeys(s.publisher for s in settings.sources))
    (folder / "headlines.md").write_text(render_headlines(data, settings.tz, order))
    (folder / "package.json").write_text(json.dumps(data, indent=1, ensure_ascii=False))
    return folder, True


def load_package(day: date, root: Path | None = None) -> dict:
    path = package_dir(day, root) / "package.json"
    if not path.exists():
        raise FileNotFoundError(f"No package for {fmt_day(day)}. Make one with: ./brief package --date {day.isoformat()}")
    data = json.loads(path.read_text())
    for key in ("window_start", "window_end", "packaged_utc"):
        data[key] = parse_iso(data[key])
    return data


def gap_lines(data: dict, tz: str) -> list[str]:
    end = data["window_end"]
    end = parse_iso(end) if isinstance(end, str) else end
    return [f"{g['label']}, check at {fmt_time(parse_iso(g['fetched_utc']), tz, end)}" for g in data["gaps"]]


def unavailable(data: dict) -> list[str]:
    """Publishers none of whose feeds answered at their last check before the window's end."""
    by_pub: dict[str, list[bool]] = {}
    for s in data["sources"]:
        if s["kind"] == "calendar":
            continue
        by_pub.setdefault(s["publisher"], []).append(s["status"] == "ok")
    return sorted(p for p, oks in by_pub.items() if not any(oks))


def render_headlines(data: dict, tz: str, order: list[str] | None = None) -> str:
    """Every item in the window as its publisher wrote it, grouped by publisher in the source registry's
    order, newest first."""
    start, end = parse_iso(data["window_start"]), parse_iso(data["window_end"])
    packaged = parse_iso(data["packaged_utc"])
    day = date.fromisoformat(data["day"])
    items = data["items"]
    rank = {p: n for n, p in enumerate(order or [])}
    publishers = sorted({i["publisher"] for i in items}, key=lambda p: (rank.get(p, len(rank)), p))
    out = [f"# Overnight news, {fmt_day(day)}", "",
           f"Everything collected from {fmt_time(start, tz, end)} to {fmt_time(end, tz)} (New York): "
           f"{len(items)} items from {len(publishers)} publishers. Headlines and summaries are the publishers' own, "
           f"as last collected by {fmt_time(packaged, tz, end)}. No model has read or written any of this list.", ""]
    if data["gaps"]:
        out += ["Possible gaps (a feed turned over completely between two checks; items in between may be missing):", ""]
        out += [f"- {g}" for g in gap_lines(data, tz)] + [""]
    for pub in publishers:
        out += [f"## {pub}", ""]
        for i in sorted((i for i in items if i["publisher"] == pub), key=lambda i: i["published_utc"], reverse=True):
            when = fmt_time(parse_iso(i["published_utc"]), tz, end)
            section = f" · {i['section']}" if i.get("section") else ""
            out.append(f"- {when}{section} — [{i['title']}]({i['url']})")
        out.append("")
    return "\n".join(out)
