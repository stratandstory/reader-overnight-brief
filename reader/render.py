"""Markdown output: the brief itself and the run report behind it."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .store import parse_iso
from .timewindow import fmt_day, fmt_time, fmt_time_or_day

SHORT = {
    "The Wall Street Journal": "WSJ",
    "Financial Times": "FT",
    "The New York Times": "NYT",
    "Federal Reserve Board": "Federal Reserve",
    "U.S. Securities and Exchange Commission": "SEC",
    "South China Morning Post": "SCMP",
    "BBC News": "BBC",
    "European Central Bank": "ECB",
    "Federal Trade Commission": "FTC",
}
AUDIENCE = {"trading": "Trading", "wealth": "Wealth", "banking": "Banking"}


def short(publisher: str) -> str:
    return SHORT.get(publisher, publisher)


def brief_filename(now: datetime, tz: str, late: bool = False) -> str:
    """'Tue, Sep 29, 6.30 AM.md'; a brief written late from a morning package adds ' (late)'."""
    local = now.astimezone(ZoneInfo(tz))
    clock = local.strftime("%I.%M %p").lstrip("0")
    return f"{local.strftime('%a')}, {local.strftime('%b')} {local.day}, {clock}{' (late)' if late else ''}.md"


def _links(item, tz: str, now: datetime) -> str:
    """Every source behind the item, earliest first."""
    docs = {ev.url: ev for claim in item.claims for ev in claim.evidence}
    ordered = sorted(docs.values(), key=lambda ev: ev.published_utc)
    return ", ".join(f"[{short(ev.publisher)}, {fmt_time_or_day(parse_iso(ev.published_utc), tz, now, ev.day_only)}]({ev.url})" for ev in ordered)


def _caveat(item) -> str:
    """Only when the whole item rests on unconfirmed reports; sentence-level attribution covers the rest."""
    if not item.claims or any(c.status not in ("attributed", "developing") for c in item.claims):
        return ""
    who = sorted({short(ev.publisher) for c in item.claims for ev in c.evidence if ev.tier > 0})
    return f"Based on unconfirmed reports ({', '.join(who)}); not yet confirmed by an official source."


def _single_source(item) -> bool:
    """True when no claim in the item is confirmed by a primary source or two independent owners."""
    return bool(item.claims) and all(c.status != "confirmed" for c in item.claims)


def _item_block(n: int | None, item, tz: str, now: datetime, tracked: dict) -> str:
    """Numbered block for top stories; a bullet for the other sections. The sourced text and the editor's
    why-it-matters line (when analysis is on) are kept visibly apart."""
    text = item.what_changed
    why = f"*Why it matters: {item.why_it_matters}*" if item.why_it_matters else ""
    meta = [" · ".join(AUDIENCE[a] for a in item.audiences if a in AUDIENCE)]
    if _single_source(item) and not _caveat(item):
        meta.append("single source")
    prior = tracked.get(item.continues or "")
    if prior:
        meta.append(f"update since {fmt_day(parse_iso(prior['last_updated_utc']).date())}")
    meta_text = " — ".join(m for m in meta if m)
    sources = (f"*{meta_text}* — " if meta_text else "") + _links(item, tz, now)
    caveat = _caveat(item)
    if n:
        lines = [f"**{n}. {item.headline.text}**  ", f"{text}  "]
        if why:
            lines.append(f"{why}  ")
        lines.append(sources + ("  " if caveat else ""))
        if caveat:
            lines.append(f"_{caveat}_")
    else:
        lines = [f"- **{item.headline.text.rstrip('.')}.** {text}  "]
        if why:
            lines.append(f"  {why}  ")
        lines.append(f"  {sources}" + ("  " if caveat else ""))
        if caveat:
            lines.append(f"  _{caveat}_")
    return "\n".join(lines)


def session_heading(session) -> tuple[str, str]:
    """The previous trading day's section: its heading and the line under it that says what it covers. Named by
    the day, not "yesterday": on a Monday morning the previous session is Friday's."""
    day = session.day()
    close = fmt_time(session.end, session.tz)
    span = (f"after {day}'s brief ({fmt_time(session.start, session.tz)}) and before the {close} close" if session.after_brief
            else f"between {fmt_time(session.start, session.tz)} and the {close} close")
    return (f"## Highlights from {day}'s trading day",
            f"_Reported {day} {span}, so no brief has carried them. The few that matter most for today; everything "
            f"else in this brief is overnight news._")


def render_brief(brief, *, now: datetime, window_start: datetime, tz: str, tracked: dict, institutional: list[dict],
                 stats: dict, unavailable: list[str], run_id: str, late_note: str | None = None,
                 session=None) -> str:
    """`session` (reader/stages/common.py Session) names the previous trading day the brief's session section covers."""
    local = now.astimezone(ZoneInfo(tz))
    printed = session if session and getattr(brief, "session", None) else None  # the section, when it has items
    covers = f"news since {fmt_time(window_start, tz, now)}"
    if printed:
        covers += f", plus highlights from {session.day()} {fmt_time(session.start, tz)} to {fmt_time(session.end, tz)}"
    out = [
        "# Overnight Markets Brief",
        "",
        f"**{local.strftime('%A, %B')} {local.day}, {local.year} · {fmt_time(now, tz)} New York** · {covers}",
        "",
    ]
    if late_note:
        out += [f"_{late_note}_", ""]
    out += [
        f"**{brief.summary.text}**",
        "",
    ]
    counts = Counter()
    for item in brief.items():
        for url, pub in {(ev.url, ev.publisher) for c in item.claims for ev in c.evidence}:
            counts[short(pub)] += 1
    if counts:
        out += ["Sources in this brief: " + " · ".join(f"{p} {n}" for p, n in counts.most_common()), ""]

    if brief.top:
        out += ["## Top stories", ""]
        for n, item in enumerate(brief.top, start=1):
            out += [_item_block(n, item, tz, now, tracked), ""]
    else:
        out += ["## Top stories", "", "Nothing material passed the evidence check this morning.", ""]
    if printed:
        heading, scope = session_heading(session)
        out += [heading, "", scope, ""]
        out += [_item_block(None, item, tz, now, tracked) for item in brief.session] + [""]
    if brief.second:
        out += ["## Also worth knowing", ""]
        out += [_item_block(None, item, tz, now, tracked) for item in brief.second] + [""]
    if brief.developing:
        out += ["## Developing", "", "_Single-source reports, not yet confirmed._", ""]
        out += [_item_block(None, item, tz, now, tracked) for item in brief.developing] + [""]

    soon = [c for c in brief.calendar if not c.later]
    later = [c for c in brief.calendar if c.later]
    out += ["## Next five trading days", ""]
    if soon:
        out += [f"- **{fmt_day(c.day)}** — {c.title} ([{short(c.publisher)}]({c.url}))" for c in soon]
    else:
        out.append("No scheduled events in our sources for the next five trading days. Economic-data calendars "
                   "(BLS, BEA) refuse automated access, so check releases separately.")
    if later:
        out += ["", "Further out:"] + [f"- **{fmt_day(c.day)}** — {c.title} ([{short(c.publisher)}]({c.url}))" for c in later]
    out.append("")

    if institutional:
        out += ["## Institutional view", ""]
        for it in institutional:
            extra = it.get("extra") or {}
            edition = extra.get("edition", "")
            day_part, _, ampm = edition.partition(" ")
            label = f"{fmt_day(datetime.fromisoformat(day_part).date())} {ampm}".strip() if day_part else ""
            author = f", {extra['author']}" if extra.get("author") else ""
            out.append(f"- {it['publisher']}, {it['section']} ({label}{author}): \"{it['title']}\" — [read]({it['url']})")
        out.append("")

    checked = stats.get("claims_checked", 0)
    passed = stats.get("claims_verified", 0)
    narrowed = stats.get("claims_narrowed", 0)
    corrected = stats.get("lines_corrected", 0)
    left_out = stats.get("stories_unpublished", 0)
    screened = f"{stats.get('items_in_window', 0)} items from {stats.get('sources_ok', 0)} sources were screened"
    if session and stats.get("items_in_session"):
        screened = (f"{stats.get('items_in_window', 0)} overnight items and {stats['items_in_session']} from "
                    f"{session.day()}'s session, from {stats.get('sources_ok', 0)} sources, were screened")
    footer = (f"_How this brief was checked: {screened}. {checked} factual claims were checked by a separate model against the publisher's own "
              f"headline and summary (official pages and company releases in full): {passed} passed, "
              f"{checked - passed} dropped, {narrowed} narrowed to what the source says. A final read corrected "
              f"{corrected} line{'s' if corrected != 1 else ''}"
              + (f" and left out {left_out} checked stor{'ies' if left_out != 1 else 'y'}" if left_out else "")
              + ". Every figure and name in the text appears in a verified claim; items resting on one outlet are "
              "marked single source. Analysis lines, where shown, are the editor's and are not sourced.")
    if unavailable:
        footer += f" Not reachable this morning: {', '.join(unavailable)}."
    footer += f" Audit trail: data/runs/{run_id}/report.md_"
    out += ["---", "", footer, ""]
    return "\n".join(out)


def render_report(*, run_id: str, now: datetime, window_start: datetime, tz: str, stats: dict, usage: list[dict],
                  budget_max: float, checked, brief, notes: list[str], statuses, calls: list[dict],
                  brief_path: Path | None, gaps: list[str] | None = None, session=None) -> str:
    out = [f"# Run {run_id}", "",
           f"Window: {fmt_time(window_start, tz, now)} to {fmt_time(now, tz)} (New York)  "]
    if session:
        out.append(f"Previous session: {fmt_time(session.start, tz, now)} to {fmt_time(session.end, tz, now)}"
                   + (" (from that day's brief to the close)" if session.after_brief else " (from the package time to the close)")
                   + "  ")
    out += [f"Brief: {brief_path.name if brief_path else 'not written'}", ""]
    out += ["## Funnel", "", "| Stage | Count |", "|---|---:|"]
    for label, key in [("Items in window", "items_in_window"), ("Kept by screen", "items_kept"),
                       ("Sent to analyst", "items_to_find"), ("Stories found", "stories_found"),
                       ("Stories checked", "stories_checked"), ("Claims checked", "claims_checked"),
                       ("Claims verified", "claims_verified"), ("Claims narrowed by the checker", "claims_narrowed"),
                       ("Lines corrected by the audit", "lines_corrected"), ("Items published", "items_published"),
                       ("Checked stories left out", "stories_unpublished"),
                       ("Previous session: items", "items_in_session"), ("Previous session: kept by screen", "session_kept"),
                       ("Previous session: sent to analyst", "session_to_find"),
                       ("Previous session: stories found", "session_stories_found"),
                       ("Previous session: stories checked", "session_stories_checked"),
                       ("Previous session: items published", "session_published")]:
        if key not in stats and key.startswith(("session", "items_in_session")):
            continue
        value = str(stats.get(key, 0))
        if key == "items_to_find" and stats.get("groups_to_find"):
            value += f" (in {stats['groups_to_find']} developments)"
        out.append(f"| {label} | {value} |")
    if stats.get("find_owners"):
        out += ["", "Analyst input by owner: " + ", ".join(f"{o} {n}" for o, n in stats["find_owners"].items())]
    total = sum(r["cost"] for r in usage)
    out += ["", "## Cost", "", "| Stage | Model | Calls | Input | Output | Cache read | Cache write | Cost |",
            "|---|---|---:|---:|---:|---:|---:|---:|"]
    for r in usage:
        out.append(f"| {r['stage']} | {r['model']} | {r['calls']} | {r['input']:,} | {r['output']:,} | "
                   f"{r['cache_read']:,} | {r['cache_write']:,} | ${r['cost']:.3f} |")
    out += [f"| **Total** | | | | | | | **${total:.3f}** (budget ${budget_max:.2f}) |", ""]

    if checked:
        out += ["## Claims", ""]
        for cs in checked:
            marker = ", previous session" if getattr(cs.story, "session", False) else ""
            out.append(f"### {cs.story.key} {cs.story.title} (materiality {cs.story.materiality}{marker})")
            for vc in cs.verified:
                src = "; ".join(f"{ev.publisher} — {ev.note}" for ev in vc.evidence)
                changed = f" (analyst wrote: \"{vc.original}\")" if vc.original != vc.text else ""
                out.append(f"- PASS [{vc.id}] ({vc.status}) {vc.text}{changed}  \n  Sources: {src}")
            for r in cs.rejected:
                out.append(f"- DROP {r['claim']}  \n  Reason: {r['reason']}")
            out.append("")
    if notes:
        out += ["## Edits and exclusions", ""] + [f"- {n}" for n in notes] + [""]
    if gaps:
        out += ["## Possible gaps", "",
                "Checks in the window where every entry in a feed was newer than anything the previous good check "
                "saw, so items published in between may never have been collected:", ""]
        out += [f"- {g}" for g in gaps] + [""]
    if statuses:
        out += ["## Sources", "", "| Source | Status | Kept this fetch |", "|---|---|---:|"]
        for s in statuses:
            out.append(f"| {s.source.label} | {s.status} | {s.kept} |")
        out.append("")
    if calls:
        out += ["## API calls", "", "| Stage | Label | Model | Stop | In | Out | Cost |", "|---|---|---|---|---:|---:|---:|"]
        for c in calls:
            out.append(f"| {c['stage']} | {c['label'][:50]} | {c['model']} | {c['stop_reason']} | {c['input']:,} | "
                       f"{c['output']:,} | ${c['cost']:.4f} |")
        out.append("")
    return "\n".join(out)
