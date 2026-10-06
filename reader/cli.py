"""Command line entry point: ./brief <command>."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from .config import BRIEFS_DIR, DATA_DIR, POLICIES, TERMS, load_env, load_settings, set_local
from .net import Fetcher
from .store import Store, parse_iso, utcnow
from .timewindow import fmt_time


def _open_store() -> Store:
    return Store(DATA_DIR / "reader.db")


def cmd_collect(settings, store) -> int:
    from .collect import collect

    fetcher = Fetcher(settings.user_agent, settings.raw["network"]["timeout_seconds"])
    report = collect(settings, store, fetcher)
    ok = len(report.statuses) - len(report.failures)
    stamp = utcnow().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    print(f"{stamp}  Checked {len(report.statuses)} sources: {ok} ok, {len(report.failures)} unavailable. "
          f"{report.new_items} new items stored.")
    for s in report.failures:
        print(f"  unavailable: {s.source.label} — {s.status}")
    for s in report.gaps:
        print(f"  possible gap: {s.source.label} — every entry is newer than the check at "
              f"{fmt_time(s.gap_since, settings.tz)}; items in between may be missing")
    return 0


def cmd_sources(settings, store) -> int:
    latest = store.latest_fetches()
    if not latest:
        print("No collection yet. Run: ./brief collect")
        return 0
    now = utcnow()
    since = now - timedelta(hours=24)
    gaps = Counter(g["source_id"] for g in store.gaps_since(since))
    print(f"{'Source':46} {'Terms':9} {'Last check':>12}  {'Status':<34} {'Kept':>5} {'Gaps 24h':>9}")
    for src in settings.sources:
        row = latest.get(src.id)
        if not src.enabled:
            state = "off (see config/sources.toml)"
        elif not settings.policy_allows(src):
            state = f"not read (policy: {settings.source_policy})"
        elif src.needs_contact and not settings.has_contact:
            state = "not used (needs contact email)"
        else:
            state = ""
        if state or not row:
            print(f"{src.label[:46]:46} {src.terms:9} {'-':>12}  {state or 'never checked':<34}")
            continue
        when = fmt_time(parse_iso(row["fetched_utc"]), settings.tz, now)
        print(f"{src.label[:46]:46} {src.terms:9} {when:>12}  {row['status'][:34]:<34} {row['kept']:>5} "
              f"{gaps[src.id] or '':>9}")
    print(f"\nFetches in the last 24 hours: {len(store.fetches_since(since))}")
    if gaps:
        print("Gaps: a check found every entry newer than anything the previous good check saw; "
              "items in between may be missing.")
    return 0


POLICY_TEXT = {
    "official": "Central banks, regulators and government only.",
    "unrestricted": "Official sources, plus news publishers whose terms of use have no clause against automated "
                    "reading or AI use.",
    "all": "Every source whose robots.txt allows Reader, including publishers whose terms restrict automated or AI "
           "use. Choosing it is your judgment that one person's brief (headlines and summaries only, links back, "
           "nothing republished) is personal use.",
}


def _policy_sources(settings, policy: str) -> list:
    off = settings.raw.get("sources", {}).get("off", [])
    return [s for s in settings.sources if s.enabled and not (s.needs_contact and not settings.has_contact)
            and s.terms in POLICIES[policy] and s.id not in off]


def cmd_choose_sources(settings, choice: str | None) -> int:
    """Which sources this machine reads, by what their publishers' terms say. Written to config/local.toml."""
    if choice is None:
        current = settings.source_policy or "not chosen yet"
        print(f"Which sources may Reader read on this Mac? Current choice: {current}\n")
        before: set[str] = set()
        for policy in POLICIES:
            sources = _policy_sources(settings, policy)
            publishers = list(dict.fromkeys(s.publisher for s in sources if s.publisher not in before))
            print(f"  {policy:13} {len(sources):3} sources. {POLICY_TEXT[policy]}")
            print(f"  {'':13}     {'Adds' if before else 'Includes'}: {', '.join(publishers)}\n")
            before |= {s.publisher for s in sources}
        print("What each publisher's terms say: config/sources.toml (terms_note), or ./brief sources for a summary.")
        if not sys.stdin.isatty():
            print("To choose: ./brief choose-sources official | unrestricted | all")
            return 0
        choice = input("Type official, unrestricted or all (or press Return to leave it as it is): ").strip().lower()
        if not choice:
            return 0
    if choice not in POLICIES:
        print(f"Not a choice: {choice}. Use one of: {', '.join(POLICIES)}")
        return 1
    set_local("sources", "policy", choice)
    print(f"Saved in config/local.toml: Reader reads {len(_policy_sources(settings, choice))} sources ({choice}). "
          f"{POLICY_TEXT[choice]}")
    print("Change it at any time with ./brief choose-sources.")
    return 0


def _day(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a date: {value} (use YYYY-MM-DD)")


def cmd_package(settings, store, day: date | None) -> int:
    """Today's package collects first, so it is as complete as the feeds allow; a past morning's is made
    from what is already stored."""
    from .package import make_package
    from .timewindow import fmt_day

    now = utcnow()
    today = now.astimezone(ZoneInfo(settings.tz)).date()
    day = day or today
    if day == today:
        cmd_collect(settings, store)
    try:
        folder, made = make_package(settings, store, day, now)
    except ValueError as e:
        print(e)
        return 1
    data = json.loads((folder / "package.json").read_text())
    verb = "Packaged" if made else "Already packaged"
    print(f"{verb} {fmt_day(day)}: {len(data['items'])} items from "
          f"{fmt_time(parse_iso(data['window_start']), settings.tz, parse_iso(data['window_end']))} to "
          f"{fmt_time(parse_iso(data['window_end']), settings.tz)}, {len(data['gaps'])} possible gaps.")
    print(f"  Headlines: {folder / 'headlines.md'}")
    return 0


def cmd_doctor(settings) -> int:
    from .llm import check_access

    status = check_access(settings)
    if settings.source_policy in POLICIES:
        print(f"Sources: {settings.source_policy}, {len(settings.active_sources())} sources.")
    else:
        print("Sources: not chosen yet. Run ./brief choose-sources.")
    return status


def cmd_open() -> int:
    briefs = sorted(BRIEFS_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime)
    if not briefs:
        print("No briefs yet. Run: ./brief run")
        return 1
    print(briefs[-1])
    subprocess.run(["open", str(briefs[-1])], check=False)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="brief", description="Overnight markets brief")
    sub = parser.add_subparsers(dest="cmd")
    run = sub.add_parser("run", help="collect overnight news and write today's brief")
    run.add_argument("--no-collect", action="store_true", help="use items already collected")
    run.add_argument("--notify", action="store_true", help="show a Mac notification when the brief is ready")
    run.add_argument("--package", metavar="YYYY-MM-DD", type=_day,
                     help="write that morning's brief late, from its morning package")
    dry = sub.add_parser("dry-run", help="everything except AI calls; shows projected cost")
    dry.add_argument("--package", metavar="YYYY-MM-DD", type=_day, help="project a late brief from a morning package")
    pk = sub.add_parser("package", help="freeze this morning's window: items, feed health, a headline list (no AI, no cost)")
    pk.add_argument("--date", type=_day, help="the morning to package, YYYY-MM-DD (default: today)")
    sub.add_parser("collect", help="fetch feeds only (no AI, no cost)")
    sub.add_parser("sources", help="source health from the latest collection")
    sub.add_parser("doctor", help="check the API key and model access")
    cs = sub.add_parser("choose-sources", help="which sources this Mac reads, by their publishers' terms (free)")
    cs.add_argument("policy", nargs="?", choices=list(POLICIES), help="official, unrestricted or all")
    sub.add_parser("open", help="open the latest brief")
    sub.add_parser("eval-check", help="run the checker against saved cases of past errors (a few cents)")
    rf = sub.add_parser("replay-find", help="re-run the analyst on a past morning's items (about $0.35 on Opus 5.5, $1 on Fable)")
    rf.add_argument("run_id", help="a run id from data/runs/, for example 20260928-064450")
    rf.add_argument("--model", help="model to use instead of the configured analyst")
    rf.add_argument("--label", help="name for the output files (default: the model)")
    since = sub.add_parser("since", help="run every stage over today's news since HH:MM, outside the brief (about $1 to $2)")
    since.add_argument("start", help="window start today, New York time, for example 09:30; or 'close' for the whole overnight window")
    since.add_argument("--label", default="since", help="suffix for the run folder (default: since)")
    since.add_argument("--dry-run", action="store_true", help="no AI calls; projected cost")
    since.add_argument("--resume", metavar="RUN_ID", help="write, audit and render from that run's saved checker output")
    args = parser.parse_args(argv)

    load_env()
    settings = load_settings()
    if args.cmd in (None, "help"):
        parser.print_help()
        return 0
    if args.cmd == "doctor":
        return cmd_doctor(settings)
    if args.cmd == "choose-sources":
        return cmd_choose_sources(settings, args.policy)
    if args.cmd in ("collect", "run", "dry-run", "package", "since"):
        if settings.source_policy not in POLICIES:
            print("Reader has not been told which sources it may read on this Mac, so it has fetched nothing."
                  if not settings.source_policy else f"Unknown sources policy: {settings.source_policy}.")
            print("Run ./brief choose-sources to see the choices.")
            return 2
    if args.cmd == "open":
        return cmd_open()
    if args.cmd == "eval-check":
        from .evalcheck import run_cases

        return run_cases(settings)
    store = _open_store()
    if args.cmd == "collect":
        return cmd_collect(settings, store)
    if args.cmd == "sources":
        return cmd_sources(settings, store)
    if args.cmd == "package":
        return cmd_package(settings, store, args.date)
    if args.cmd == "replay-find":
        from .replayfind import replay

        return replay(settings, store, args.run_id, args.model, args.label)
    if args.cmd == "since":
        from .sinceopen import run_since

        return run_since(settings, store, args.start, args.label, dry_run=args.dry_run, resume=args.resume)
    if args.cmd in ("run", "dry-run"):
        from .pipeline import run_brief

        return run_brief(settings, store, dry_run=(args.cmd == "dry-run"),
                         collect_first=not getattr(args, "no_collect", False),
                         notify_when_done=getattr(args, "notify", False), package_day=args.package)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
