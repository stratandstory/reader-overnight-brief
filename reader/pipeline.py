"""The morning run: collect → screen → find → check → write → audit → render → remember."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
from dataclasses import asdict, is_dataclass
from datetime import date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import session as session_mod
from .budget import Budget
from .collect import collect
from .config import BRIEFS_DIR, DATA_DIR, Settings
from .llm import LLM, OutputTruncated, StageError
from .net import Fetcher
from .render import brief_filename, render_brief, render_report
from .schedule import load_static_calendar
from .stages import audit as audit_stage
from .stages import check as check_stage
from .stages import find as find_stage
from .stages import write as write_stage
from .stages.common import Session, Window
from .stages.screen import screen
from .stages.write import CalendarEntry
from .store import Store, parse_iso, utcnow
from .guards import set_ordinary_words
from .package import gap_lines, load_package, make_package, package_end, unavailable
from .timewindow import fmt_day, fmt_time, is_trading_day, next_trading_days, overnight_window
from .workbench import copy_to_workbench


def _by_owner(items: list[dict]) -> dict[str, int]:
    """Items per owner, most first: the run report's instrument for how concentrated the analyst's input is."""
    counts: dict[str, int] = {}
    for it in items:
        key = it.get("owner") or it["publisher"]
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def say(msg: str) -> None:
    print(msg, flush=True)


def _dump(path: Path, obj) -> None:
    def default(o):
        if is_dataclass(o):
            return asdict(o)
        if isinstance(o, (date,)):
            return o.isoformat()
        return str(o)
    path.write_text(json.dumps(obj, indent=2, default=default, ensure_ascii=False))


def _unavailable(statuses) -> list[str]:
    """Publishers none of whose feeds answered (a single failed section isn't worth flagging)."""
    by_pub: dict[str, list[bool]] = {}
    for s in statuses:
        if s.source.kind == "calendar":
            continue
        by_pub.setdefault(s.source.publisher, []).append(s.status == "ok")
    return sorted(p for p, oks in by_pub.items() if not any(oks))


def _gaps(store: Store, settings: Settings, since, now) -> list[str]:
    """Checks in the window after which a feed had turned over completely: items may be missing there."""
    labels = {s.id: s.label for s in settings.sources}
    return [f"{labels.get(g['source_id'], g['source_id'])}, check at {fmt_time(parse_iso(g['fetched_utc']), settings.tz, now)}"
            for g in store.gaps_since(since)]


def build_calendar(store: Store, checked, settings: Settings, now) -> list[CalendarEntry]:
    tz = ZoneInfo(settings.tz)
    today = now.astimezone(tz).date()
    horizon = next_trading_days(today, int(settings.raw["brief"]["calendar_trading_days"]))[-1]
    for cs in checked:
        for vc in cs.verified:
            if vc.kind != "scheduled" or not vc.event_date:
                continue
            try:
                day = date.fromisoformat(vc.event_date[:10])
            except ValueError:
                continue
            if day < today:
                continue
            ev = vc.evidence[0]
            store.upsert_calendar({
                "id": "claim-" + hashlib.sha1(f"{vc.text}|{day}".encode()).hexdigest()[:10],
                "event_date": day.isoformat(), "title": vc.text.rstrip("."), "source_id": None,
                "publisher": ev.publisher, "url": ev.url, "origin": "claim",
            })
    rows = store.calendar_between(today.isoformat(), (today + timedelta(days=45)).isoformat())
    return [
        CalendarEntry(ref=f"K{i}", day=date.fromisoformat(r["event_date"]), title=r["title"],
                      publisher=r["publisher"] or "", url=r["url"] or "", later=date.fromisoformat(r["event_date"]) > horizon)
        for i, r in enumerate(rows, start=1)
    ]


def _story_id(headline: str, now) -> str:
    words = re.findall(r"[a-z0-9]+", headline.lower())[:6]
    return "-".join(words) + "-" + now.strftime("%Y%m%d")


def remember(store: Store, run_id: str, brief, checked, now, day_start, stories: bool = True) -> None:
    """Saves the run's claims; with `stories`, also what the brief reported, for the next brief's update tags.
    A brief written late leaves story memory alone: the briefs after it went out without it."""
    if stories:
        store.forget_same_day(day_start, run_id)
        by_key = {cs.story.key: cs for cs in checked}
        for item in brief.items():
            cs = by_key.get(item.story_key)
            story_id = item.continues or _story_id(item.headline.text, now)
            store.record_story(story_id, item.headline.text, cs.story.category if cs else "", item.what_changed, run_id,
                               [f"{run_id}-{c.id}" for c in item.claims])
    rows = []
    for cs in checked:
        for vc in cs.verified:
            rows.append({"id": f"{run_id}-{vc.id}", "story_key": cs.story.key, "text": vc.text, "verdict": "verified",
                         "status": vc.status, "item_ids": [e.item_id for e in vc.evidence], "quotes": vc.quotes})
        for n, r in enumerate(cs.rejected, start=1):
            rows.append({"id": f"{run_id}-{cs.story.key}-x{n}", "story_key": cs.story.key, "text": r["claim"],
                         "verdict": "rejected", "status": None, "item_ids": [], "note": r["reason"]})
    store.save_claims(run_id, rows)
    if stories:
        store.close_stale_stories(now - timedelta(days=30))


def dry_run_projection(settings: Settings, budget: Budget, items: list[dict], n_session: int = 0) -> None:
    """Screening is projected from the real items; later stages from typical proportions. `items` includes the
    previous session's `n_session` items, which have their own allowance at the analyst and the checker."""
    avg = sum(len(i["title"]) + min(len(i.get("summary") or ""), 500) + 80 for i in items) / max(1, len(items))
    n_find = min(int((len(items) - n_session) * 0.35), int(settings.stage("find").extra.get("max_items", 140)))
    cfg = session_mod.settings_for(settings)
    if n_session:
        n_find += min(int(n_session * 0.35), cfg["analyst_items"])
    budget.project("find", settings.stage("find").model, len(find_stage.SYSTEM) + int(n_find * avg) + 3000, 9000,
                   note=f"~{n_find} items, assuming a third are kept")
    n_st = min(int(settings.stage("check").extra.get("max_stories", 18)), 24)  # weekday analysts return 20 to 25
    if n_session:
        n_st += cfg["max_stories"]
    budget.project("check", settings.stage("check").model, n_st * (len(check_stage.SYSTEM) + 3000), n_st * 1500,
                   calls=n_st, note=f"~{n_st} stories (cache savings not counted)")
    budget.project("write", settings.stage("write").model, len(write_stage.SYSTEM) + 16000, 6000)
    budget.project("audit", settings.stage("audit").model, len(audit_stage.SYSTEM) + 9000, 2500)
    say("\nProjected cost of a full run (no API calls were made):\n")
    say(f"  {'Stage':8} {'Model':18} {'Calls':>5} {'Input tok':>10} {'Output tok':>10} {'Cost':>8}")
    rows: dict[str, dict] = {}
    for p in budget.projected:
        r = rows.setdefault(p["stage"], {"model": p["model"], "calls": 0, "input": 0, "output": 0, "cost": 0.0, "note": p["note"]})
        r["calls"] += p["calls"]
        r["input"] += p["input"]
        r["output"] += p["output"]
        r["cost"] += p["cost"]
    for stage, r in rows.items():
        say(f"  {stage:8} {r['model']:18} {r['calls']:>5} {r['input']:>10,} {r['output']:>10,} ${r['cost']:>7.3f}")
    total = sum(r["cost"] for r in rows.values())
    say(f"  {'total':8} {'':18} {'':>5} {'':>10} {'':>10} ${total:>7.3f}   (budget ceiling ${budget.max_usd:.2f})")
    say("\nOutput tokens include the models' reasoning. Actual costs appear in each run report.")


def notify(title: str, message: str) -> None:
    """Mac notification; silently skipped where osascript isn't available."""
    script = f'display notification {json.dumps(message)} with title {json.dumps(title)}'
    subprocess.run(["osascript", "-e", script], check=False, capture_output=True)


def _package_today(settings: Settings, store: Store, now) -> None:
    """Writes this morning's package if it is due and missing, so a run on time leaves one too."""
    today = now.astimezone(ZoneInfo(settings.tz)).date()
    if not is_trading_day(today) or now < package_end(today, settings):
        return
    try:
        folder, made = make_package(settings, store, today, now, root=DATA_DIR / "packages")
        if made:
            say(f"  Morning package written: {folder}")
    except OSError as e:
        say(f"  Could not write the morning package: {e}")


def run_brief(settings: Settings, store: Store, dry_run: bool = False, collect_first: bool = True,
              notify_when_done: bool = False, package_day: date | None = None) -> int:
    """The brief for the window from the previous close to now; with `package_day`, the brief that morning's
    package would have produced, written late from its frozen items."""
    started = time.time()
    now = utcnow()
    tz = settings.tz
    fetcher = Fetcher(settings.user_agent, settings.raw["network"]["timeout_seconds"])
    set_ordinary_words(store.ordinary_words())

    statuses = []
    pkg = None
    session: Session | None = None
    session_in: list[dict] = []
    if package_day:
        try:
            pkg = load_package(package_day, root=DATA_DIR / "packages")
        except FileNotFoundError as e:
            say(str(e))
            return 1
        start, end = pkg["window_start"], pkg["window_end"]
        in_window = pkg["items"]
        if pkg.get("session") and session_mod.settings_for(settings)["enabled"]:
            sd = pkg["session"]  # packages from before 2026-10-06 have none
            session = Session(parse_iso(sd["start"]), parse_iso(sd["end"]), tz, bool(sd.get("after_brief")))
            session_in = pkg.get("session_items", [])
        say(f"Writing the brief for {fmt_day(package_day)} late, from its morning package "
            f"(packaged {fmt_time(pkg['packaged_utc'], tz, now)}).")
    else:
        if collect_first:
            say("Collecting overnight news...")
            report = collect(settings, store, fetcher, now)
            statuses = report.statuses
            say(f"  {len(statuses) - len(report.failures)} of {len(statuses)} sources answered; {report.new_items} new items.")
        if not dry_run:
            _package_today(settings, store, now)
        start, end = overnight_window(now, tz, settings.raw["window"]["close_hour"], settings.raw["window"]["max_lookback_hours"])
        in_window = store.items_in_window(start, end)
        for it in in_window:
            it["extra"] = json.loads(it.get("extra") or "{}")
    asof = end  # the moment the brief speaks from: now, or the package time for a late brief
    run_id = now.astimezone(ZoneInfo(tz)).strftime("%Y%m%d-%H%M%S")
    if pkg:
        run_id += f"-for-{package_day:%Y%m%d}"
    window = Window(start, end, tz)
    if not pkg:
        session = session_mod.bounds(settings, store, window)
        session_in = session_mod.items(store, session) if session else []
    local_asof = asof.astimezone(ZoneInfo(tz))
    day_start = local_asof.replace(hour=0, minute=0, second=0, microsecond=0)
    items = [i for i in in_window if i["model_ok"] and i["kind"] != "institutional"]
    institutional = [i for i in in_window if i["kind"] == "institutional"][:1]
    session_items = [i for i in session_in if i["model_ok"] and i["kind"] != "institutional"]
    session_ids = {i["id"] for i in session_items}
    if not session_items:
        session = None
    say(f"{len(items)} items published {window.describe()}.")
    if session:
        say(f"{len(session_items)} more from the previous session, {session.describe()}.")
    if not items:
        say("Nothing in the window to brief. Try ./brief collect, then run again.")
        return 1

    budget = Budget(settings, float(settings.raw["budget"]["max_run_usd"]))
    try:
        llm = LLM(settings, budget, dry_run=dry_run)
    except StageError as e:
        say(str(e))
        return 1

    stats = {"items_in_window": len(items),
             "sources_ok": len({s.source.id for s in statuses if s.status == "ok"})
             or len({i["source_id"] for i in items + session_items})}
    if session:
        stats["items_in_session"] = len(session_items)
    gaps = gap_lines(pkg, tz) if pkg else _gaps(store, settings, start, now)
    stats["feed_gaps"] = len(gaps)
    run_dir = DATA_DIR / "runs" / run_id
    notes: list[str] = []
    checked: list = []
    brief = None
    brief_path = None
    status = "failed"
    if not dry_run:
        run_dir.mkdir(parents=True, exist_ok=True)
        store.start_run(run_id, start, end)

    try:
        say(f"Screening {len(items) + len(session_items)} items with {settings.stage('screen').model}...")
        kept_all, scores = screen(llm, settings, items + session_items, window, session)
        if dry_run:
            dry_run_projection(settings, budget, items + session_items, len(session_items))
            return 0
        kept = [i for i in kept_all if i["id"] not in session_ids]
        session_kept = [i for i in kept_all if i["id"] in session_ids]
        stats["items_kept"] = len(kept)
        if session:
            stats["session_kept"] = len(session_kept)
        _dump(run_dir / "1-screen.json", [{"id": i["id"], "score": scores.get(i["id"]), "publisher": i["publisher"],
                                           "title": i["title"], **({"session": True} if i["id"] in session_ids else {})}
                                          for i in items + session_items])

        max_items = int(settings.stage("find").extra.get("max_items", 140))
        session_cap = session_mod.settings_for(settings)["analyst_items"]
        groups = find_stage.select_groups(kept, scores, max_items, settings)
        session_groups = find_stage.select_groups(session_kept, scores, session_cap, settings) if session_kept else []
        to_find = [it for g in groups for it in g]
        session_to_find = [it for g in session_groups for it in g]
        stats["items_to_find"] = len(to_find)
        stats["groups_to_find"] = len(groups)
        stats["find_owners"] = _by_owner(to_find)
        if session:
            stats["session_to_find"] = len(session_to_find)
        tracked_rows = store.tracked_before(day_start, asof - timedelta(days=14))
        tracked = {r["id"]: r for r in tracked_rows}
        say(f"Finding stories in {len(to_find) + len(session_to_find)} items with {settings.stage('find').model}...")
        try:
            stories, find_notes = find_stage.find(llm, settings, to_find + session_to_find, tracked_rows, window,
                                                  groups=groups, session=session, session_groups=session_groups)
        except OutputTruncated:
            groups = find_stage.select_groups(kept, scores, int(len(to_find) * 0.6), settings)
            to_find = [it for g in groups for it in g]
            if session_kept:
                session_groups = find_stage.select_groups(session_kept, scores, int(len(session_to_find) * 0.6), settings)
                session_to_find = [it for g in session_groups for it in g]
            notes.append(f"Analyst output was cut off; retried with the top {len(to_find) + len(session_to_find)} items")
            say(f"  Analyst output was cut off; retrying with the top {len(to_find) + len(session_to_find)} items...")
            stories, find_notes = find_stage.find(llm, settings, to_find + session_to_find, tracked_rows, window,
                                                  groups=groups, session=session, session_groups=session_groups)
        notes += find_notes
        stats["stories_found"] = len(stories)
        stats["claims_drafted"] = sum(len(s.claims) for s in stories)
        if session:
            stats["session_stories_found"] = sum(1 for s in stories if s.session)
        _dump(run_dir / "2-find.json", stories)

        items_by_id = {i["id"]: i for i in items + session_items}
        to_check, select_notes = session_mod.select(stories, settings,
                                                    int(settings.stage("check").extra.get("max_stories", 18)))
        notes += select_notes
        say(f"Checking {len(to_check)} stories independently with {settings.stage('check').model}...")
        checked, check_notes = check_stage.check(llm, settings, to_check, items_by_id, fetcher, reserve=0.30,
                                                 today=window.today(), limit=len(to_check))
        notes += check_notes
        if session:
            stats["session_stories_checked"] = sum(1 for cs in checked if cs.story.session)
        stats["stories_checked"] = len(checked)
        stats["claims_checked"] = sum(len(cs.verified) + len(cs.rejected) for cs in checked)
        stats["claims_verified"] = sum(len(cs.verified) for cs in checked)
        _dump(run_dir / "3-check.json", checked)

        stats["claims_narrowed"] = sum(1 for cs in checked for vc in cs.verified if vc.text != vc.original)
        notes += load_static_calendar(store)
        calendar = build_calendar(store, checked, settings, asof)
        session_keys, for_writer, route_notes = (session_mod.route(checked, session_ids, settings) if session
                                                 else (set(), checked, []))
        notes += route_notes
        say(f"Writing the brief with {settings.stage('write').model}...")
        brief = write_stage.write(llm, settings, for_writer, tracked, calendar, window, session=session,
                                  session_keys=session_keys)
        notes += brief.notes
        say(f"Auditing the draft with {settings.stage('audit').model}...")
        audit_notes = audit_stage.audit(llm, settings, brief)
        notes += audit_notes
        stats["lines_corrected"] = sum(1 for n in audit_notes if not n.startswith("Model audit unavailable"))
        stats["items_published"] = len(brief.items())
        if session:
            stats["session_published"] = len(brief.session)
        published = {it.story_key for it in brief.items()}
        stats["stories_unpublished"] = sum(1 for cs in for_writer if cs.verified and cs.story.key not in published)
        for cs in for_writer:
            if cs.verified and cs.story.key not in published:
                notes.append(f"Editor left out a checked story: {cs.story.title} (materiality {cs.story.materiality})")
        _dump(run_dir / "4-brief.json", brief)

        BRIEFS_DIR.mkdir(exist_ok=True)
        brief_path = BRIEFS_DIR / brief_filename(asof, tz, late=bool(pkg))
        late_note = (f"Written late, {fmt_day(now.astimezone(ZoneInfo(tz)).date())} at {fmt_time(now, tz)}, from the {fmt_time(asof, tz)} "
                     f"morning package. Sources were re-checked when it was written.") if pkg else None
        brief_path.write_text(render_brief(
            brief, now=asof, window_start=start, tz=tz, tracked=tracked, institutional=institutional,
            stats=stats, unavailable=unavailable(pkg) if pkg else _unavailable(statuses), run_id=run_id,
            late_note=late_note, session=session,
        ))
        workbench_path = None
        if settings.raw["brief"].get("workbench"):
            try:
                workbench_path = copy_to_workbench(brief_path.read_text(), brief_path, asof, tz, run_id,
                                                   Path(settings.raw["brief"]["workbench"]), note=late_note)
                notes.append(f"Copied to the workbench: {workbench_path.name}")
            except OSError as e:
                notes.append(f"Workbench copy failed: {e}")
                say(f"  Could not copy the brief to the workbench: {e}")
        remember(store, run_id, brief, checked, now, day_start, stories=not pkg)
        if pkg:
            notes.append(f"Written late for {fmt_day(package_day)}: story memory left as it was, so later briefs are unaffected")
        status = "ok"
    except StageError as e:
        notes.append(f"Run stopped: {e}")
        say(f"\nStopped: {e}")
    finally:
        if not dry_run:
            usage = budget.summary_rows()
            store.save_usage(run_id, usage)
            _dump(run_dir / "model-outputs.json", getattr(llm, "outputs", []))
            (run_dir / "report.md").write_text(render_report(
                run_id=run_id, now=asof, window_start=start, tz=tz, stats=stats, usage=usage,
                budget_max=budget.max_usd, checked=checked, brief=brief, notes=notes, statuses=statuses,
                calls=llm.calls, brief_path=brief_path, gaps=gaps, session=session,
            ))
            store.finish_run(run_id, status, budget.spent, str(brief_path) if brief_path else None,
                             brief.summary.text if brief else None, stats)

    minutes = (time.time() - started) / 60
    if status != "ok":
        say(f"  Spent ${budget.spent:.2f}. Details: {run_dir / 'report.md'}")
        if notify_when_done:
            notify("Overnight brief did not complete", f"See the run report in data/runs/{run_id}")
        return 1
    if notify_when_done:
        notify("Overnight brief ready", f"{len(brief.top)} top stories · {brief_path.stem}")
    say(f"\nBrief: {brief_path}")
    if workbench_path:
        say(f"  Workbench: {workbench_path}")
    say(f"  {len(brief.top)} top stories, {len(brief.second)} more, {len(brief.developing)} developing, "
        + (f"{len(brief.session)} from {session.day()}'s session, " if session else "")
        + f"{len(brief.calendar)} calendar entries")
    say(f"  {stats.get('claims_checked', 0)} claims checked, {stats.get('claims_verified', 0)} passed")
    say(f"  Cost ${budget.spent:.2f} (ceiling ${budget.max_usd:.2f}); {minutes:.1f} minutes")
    say(f"  Run report: {run_dir / 'report.md'}")
    return 0 if status == "ok" else 1
