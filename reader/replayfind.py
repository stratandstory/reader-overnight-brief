"""`./brief replay-find <run-id>`: re-run the analyst on a past morning's exact items.

The find stage is the one place grouping happens, and nothing downstream re-examines it, so the
way to judge a prompt or model change to the analyst is to replay a real morning and read the
stories it makes. The inputs are rebuilt from the run's window and its saved screen scores; the
output goes to data/runs/<run-id>/find-replays/ as a readable listing plus the raw stories.
Costs what one find call costs (about $0.35 on Opus 5.5, $1 on Fable 5.1 at 140 items).
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .budget import Budget
from .config import DATA_DIR, Settings
from .llm import LLM, StageError
from .stages import find as find_stage
from .stages.common import Window
from .store import Store, parse_iso
from .timewindow import fmt_time


def replay(settings: Settings, store: Store, run_id: str, model: str | None = None, label: str | None = None,
           max_usd: float = 3.0) -> int:
    run_dir = DATA_DIR / "runs" / run_id
    screen_path = run_dir / "1-screen.json"
    if not screen_path.exists():
        print(f"No screen output for run {run_id} ({screen_path}).")
        return 1
    rows = store._all("SELECT * FROM runs WHERE id = ?", (run_id,))
    if not rows:
        print(f"Run {run_id} is not in the database.")
        return 1
    run = rows[0]
    if model:
        settings.raw["models"]["find"]["model"] = model
    model = settings.stage("find").model
    label = label or model.replace("claude-", "")

    start, end = parse_iso(run["window_start_utc"]), parse_iso(run["window_end_utc"])
    window = Window(start, end, settings.tz)
    now = parse_iso(run["started_utc"])
    in_window = store.items_in_window(start, end)
    for it in in_window:
        it["extra"] = json.loads(it.get("extra") or "{}")
    items = [i for i in in_window if i["model_ok"] and i["kind"] != "institutional"]
    scores = {r["id"]: (r["score"] if r["score"] is not None else 2) for r in json.loads(screen_path.read_text())}
    unscored = [i for i in items if i["id"] not in scores]  # stored after the run, or re-keyed since
    kept = [i for i in items if scores.get(i["id"], 2) >= 2]
    groups = find_stage.select_groups(kept, scores, int(settings.stage("find").extra.get("max_items", 140)), settings)
    to_find = [it for g in groups for it in g]
    local_now = now.astimezone(ZoneInfo(settings.tz))
    day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    tracked = store.tracked_before(day_start, now - timedelta(days=14))
    print(f"Replaying the analyst on run {run_id}: {len(items)} items in the window, {len(kept)} kept by the screen, "
          f"{len(to_find)} to the analyst, {len(tracked)} tracked stories; model {model}."
          + (f" {len(unscored)} items stored after the run have no screen score and count as kept." if unscored else ""))

    budget = Budget(settings, max_usd)
    try:
        llm = LLM(settings, budget)
        stories, notes = find_stage.find(llm, settings, to_find, tracked, window, groups=groups)
    except StageError as e:
        print(e)
        return 1

    by_id = {i["id"]: i for i in items}
    out_dir = run_dir / "find-replays"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now(ZoneInfo(settings.tz)).strftime("%Y%m%d-%H%M%S")
    lines = [f"# Analyst replay: {label} on run {run_id} ({stamp})",
             f"Model {model}; {len(to_find)} items; {len(stories)} stories; cost ${budget.spent:.3f}", ""]
    for st in stories:
        lines.append(f"[{st.key}] mat {st.materiality} · {st.category} · {st.region} — {st.title}")
        lines.append(f"    why: {st.why_it_matters}")
        for c in st.claims:
            srcs = "; ".join(f"{by_id[i]['publisher']} {fmt_time(parse_iso(by_id[i]['published_utc']), settings.tz, end)}"
                             for i in c.item_ids if i in by_id)
            lines.append(f"  - ({c.kind}) {c.text}  [{srcs}]")
        lines.append("")
    if notes:
        lines.append("Notes: " + " | ".join(notes))
    md = out_dir / f"{label}-{stamp}.md"
    md.write_text("\n".join(lines) + "\n")
    (out_dir / f"{label}-{stamp}.json").write_text(json.dumps(
        {"label": label, "model": model, "run_id": run_id, "cost": budget.spent, "calls": llm.calls, "notes": notes,
         "stories": [asdict(s) for s in stories]}, indent=2, ensure_ascii=False, default=str))
    print(f"{len(stories)} stories, ${budget.spent:.3f}. Listing: {md}")
    return 0
