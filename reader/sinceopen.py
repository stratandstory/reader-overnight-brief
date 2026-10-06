"""`./brief since HH:MM`: run every stage over today's news since a given time, as an experiment.

Reader's job is the pre-open brief. This runs the same six stages over a same-day window (for
example 9:30 AM to now) so the overnight framing can be read against what the wires reported
after the open. It writes only to data/runs/<id>-<label>/ (stage dumps, brief.md, report.md)
and never touches briefs/, the story memory, the calendar or the runs table, so the next
morning's brief is unaffected. This morning's brief stories are passed to the analyst as tracked,
so it says what is new since them. No calendar is shown. Costs about $1 to $2.
"""

from __future__ import annotations

import json
from dataclasses import asdict, fields, is_dataclass
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from .budget import Budget
from .config import DATA_DIR, Settings
from .guards import set_ordinary_words
from .llm import LLM, StageError
from .net import Fetcher
from .render import render_brief, render_report
from .stages import audit as audit_stage
from .stages import check as check_stage
from .stages import find as find_stage
from .stages import write as write_stage
from .stages.common import Window
from .stages.screen import screen
from .store import Store, utcnow
from .timewindow import overnight_window


def load_dataclass(cls, data):
    """Rebuild a dataclass tree from the JSON a run dumped with asdict(): the way a run resumes from its
    saved stage output instead of paying for the stages again."""
    import types
    import typing
    if data is None:
        return None
    origin = typing.get_origin(cls)
    if origin in (typing.Union, types.UnionType):
        inner = [a for a in typing.get_args(cls) if a is not type(None)]
        return load_dataclass(inner[0], data) if len(inner) == 1 else data
    if origin is list:
        (inner,) = typing.get_args(cls)
        return [load_dataclass(inner, x) for x in data]
    if is_dataclass(cls) and isinstance(data, dict):
        hints = typing.get_type_hints(cls)
        return cls(**{f.name: load_dataclass(hints[f.name], data[f.name]) for f in fields(cls) if f.name in data})
    return data


def run_since(settings: Settings, store: Store, start_hhmm: str, label: str = "since", dry_run: bool = False,
              resume: str | None = None) -> int:
    """With `resume`, a run id whose 3-check.json exists: skip screen, find and check, and write, audit and
    render from the saved checker output into the same run folder (a writer failure costs the writer only)."""
    from .pipeline import _by_owner, dry_run_projection

    def dump(path, obj):
        def default(o):
            if is_dataclass(o): return asdict(o)
            if isinstance(o, date): return o.isoformat()
            return str(o)
        path.write_text(json.dumps(obj, indent=2, default=default, ensure_ascii=False))

    tz = settings.tz
    now = utcnow()
    set_ordinary_words(store.ordinary_words())
    local = now.astimezone(ZoneInfo(tz))
    if start_hhmm == "close":  # the overnight window itself, outside the brief: a comparison run
        start = overnight_window(now, tz, settings.raw["window"]["close_hour"], settings.raw["window"]["max_lookback_hours"])[0]
    else:
        hh, mm = map(int, start_hhmm.split(":"))
        start = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
    window = Window(start, now, tz)
    in_window = store.items_in_window(start, now)
    for it in in_window:
        it["extra"] = json.loads(it.get("extra") or "{}")
    items = [i for i in in_window if i["model_ok"] and i["kind"] != "institutional"]
    print(f"{len(items)} items published {window.describe()}.", flush=True)
    if not items:
        return 1

    run_id = resume or (local.strftime("%Y%m%d-%H%M%S") + "-" + label)
    run_dir = DATA_DIR / "runs" / run_id
    if resume and not (run_dir / "3-check.json").exists():
        print(f"Nothing to resume: {run_dir / '3-check.json'} does not exist.")
        return 1
    budget = Budget(settings, float(settings.raw["budget"]["max_run_usd"]))
    llm = LLM(settings, budget, dry_run=dry_run)
    fetcher = Fetcher(settings.user_agent, settings.raw["network"]["timeout_seconds"])
    stats = {"items_in_window": len(items), "sources_ok": len({i["source_id"] for i in items}), "feed_gaps": 0}
    notes, checked, brief = [], [], None
    status = "failed"
    if not dry_run:
        run_dir.mkdir(parents=True, exist_ok=True)
    try:
        if resume:
            from .stages.check import CheckedStory
            screened = json.loads((run_dir / "1-screen.json").read_text())
            stats["items_in_window"] = len(screened)
            stats["items_kept"] = sum(1 for x in screened if (x["score"] or 0) >= 2)
            stats["stories_found"] = len(json.loads((run_dir / "2-find.json").read_text()))
            checked = [load_dataclass(CheckedStory, cs) for cs in json.loads((run_dir / "3-check.json").read_text())]
            stats["items_to_find"] = len({i for st in json.loads((run_dir / '2-find.json').read_text()) for c in st['claims'] for i in c['item_ids']})
            stats["stories_checked"] = len(checked)
            stats["claims_checked"] = sum(len(cs.verified) + len(cs.rejected) for cs in checked)
            stats["claims_verified"] = sum(len(cs.verified) for cs in checked)
            stats["claims_narrowed"] = sum(1 for cs in checked for vc in cs.verified if vc.text != vc.original)
            tracked_rows = store.tracked_before(now, now - timedelta(days=14))
            tracked = {r["id"]: r for r in tracked_rows}
            notes.append(f"Resumed from the saved checker output of run {run_id}; screen, find and check were not re-run")
            print(f"Resuming {run_id} from its saved checker output: {len(checked)} checked stories.", flush=True)
            raise _Resume
        print(f"Screening {len(items)} items with {settings.stage('screen').model}...", flush=True)
        kept, scores = screen(llm, settings, items, window)
        if dry_run:
            dry_run_projection(settings, budget, items)
            return 0
        stats["items_kept"] = len(kept)
        dump(run_dir / "1-screen.json", [{"id": i["id"], "score": scores.get(i["id"]), "publisher": i["publisher"], "title": i["title"]} for i in items])
        groups = find_stage.select_groups(kept, scores, int(settings.stage("find").extra.get("max_items", 140)), settings)
        to_find = [it for g in groups for it in g]
        stats["items_to_find"] = len(to_find)
        stats["groups_to_find"] = len(groups)
        stats["find_owners"] = _by_owner(to_find)
        # cutoff = now, so this morning's brief stories count as tracked and the analyst says what is new since them
        tracked_rows = store.tracked_before(now, now - timedelta(days=14))
        tracked = {r["id"]: r for r in tracked_rows}
        print(f"Finding stories in {len(to_find)} items with {settings.stage('find').model} ({len(tracked_rows)} tracked)...", flush=True)
        stories, find_notes = find_stage.find(llm, settings, to_find, tracked_rows, window, groups=groups)
        notes += find_notes
        stats["stories_found"] = len(stories)
        stats["claims_drafted"] = sum(len(s.claims) for s in stories)
        dump(run_dir / "2-find.json", stories)
        items_by_id = {i["id"]: i for i in items}
        print(f"Checking {min(len(stories), int(settings.stage('check').extra.get('max_stories', 18)))} stories with {settings.stage('check').model}...", flush=True)
        checked, check_notes = check_stage.check(llm, settings, stories, items_by_id, fetcher, reserve=0.30)
        notes += check_notes
        stats["stories_checked"] = len(checked)
        stats["claims_checked"] = sum(len(cs.verified) + len(cs.rejected) for cs in checked)
        stats["claims_verified"] = sum(len(cs.verified) for cs in checked)
        stats["claims_narrowed"] = sum(1 for cs in checked for vc in cs.verified if vc.text != vc.original)
        dump(run_dir / "3-check.json", checked)
        raise _Resume
    except _Resume:
        pass
    except StageError as e:
        notes.append(f"Run stopped: {e}")
        print(f"\nStopped: {e}")
        _finish(run_dir, run_id, now, start, tz, stats, budget, checked, brief, notes, llm, status, dry_run)
        return 1
    try:
        print(f"Writing with {settings.stage('write').model}...", flush=True)
        brief = write_stage.write(llm, settings, checked, tracked, [], window)
        notes += brief.notes
        print(f"Auditing with {settings.stage('audit').model}...", flush=True)
        audit_notes = audit_stage.audit(llm, settings, brief)
        notes += audit_notes
        stats["lines_corrected"] = sum(1 for n in audit_notes if not n.startswith("Model audit unavailable"))
        stats["items_published"] = len(brief.items())
        published = {it.story_key for it in brief.items()}
        stats["stories_unpublished"] = sum(1 for cs in checked if cs.verified and cs.story.key not in published)
        for cs in checked:
            if cs.verified and cs.story.key not in published:
                notes.append(f"Editor left out a checked story: {cs.story.title} (materiality {cs.story.materiality})")
        dump(run_dir / "4-brief.json", brief)
        text = render_brief(brief, now=now, window_start=start, tz=tz, tracked=tracked, institutional=[], stats=stats,
                            unavailable=[], run_id=run_id)
        (run_dir / "brief.md").write_text(text)
        status = "ok"
    except StageError as e:
        notes.append(f"Run stopped: {e}")
        print(f"\nStopped: {e}")
    _finish(run_dir, run_id, now, start, tz, stats, budget, checked, brief, notes, llm, status, dry_run)
    return 0 if status == "ok" else 1


class _Resume(Exception):
    """Control flow only: jump from the stage sequence to the writing half."""


def _finish(run_dir, run_id, now, start, tz, stats, budget, checked, brief, notes, llm, status, dry_run) -> None:
    if dry_run:
        return
    def default(o):
        if is_dataclass(o): return asdict(o)
        if isinstance(o, date): return o.isoformat()
        return str(o)
    usage = budget.summary_rows()
    (run_dir / "model-outputs.json").write_text(json.dumps(llm.outputs, indent=2, default=default, ensure_ascii=False))
    (run_dir / "report.md").write_text(render_report(
        run_id=run_id, now=now, window_start=start, tz=tz, stats=stats, usage=usage, budget_max=budget.max_usd,
        checked=checked, brief=brief, notes=notes, statuses=[], calls=llm.calls,
        brief_path=(run_dir / "brief.md") if status == "ok" else None, gaps=[]))
    print(f"\nCost ${budget.spent:.2f}. Run dir: {run_dir}")
