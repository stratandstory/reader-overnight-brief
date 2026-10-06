"""Copies the finished brief to a workbench: a flat folder (a synced drive, say) to open from any device.

The copy follows simple filing rules: everything at the top level, the project in the filename, a
provenance block at the head of every file, and never overwrite. The brief in briefs/ stays the record;
the workbench copy is the one to grab. The folder is `workbench` in settings, usually set in local.toml.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT = "reader"
SLUG = "overnight-markets-brief"


def workbench_filename(workbench: Path, now: datetime, tz: str) -> Path:
    """YYYY-MM-DD-reader-overnight-markets-brief.md; a second brief the same day gets -v2, then -v3."""
    day = now.astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d")
    stem = f"{day}-{PROJECT}-{SLUG}"
    path = workbench / f"{stem}.md"
    version = 1
    while path.exists():
        version += 1
        path = workbench / f"{stem}-v{version}.md"
    return path


def provenance(now: datetime, tz: str, version: int, brief_path: Path, run_id: str, note: str | None = None,
               owner: str = "") -> str:
    local = now.astimezone(ZoneInfo(tz))
    what = "v1" if version == 1 else f"v{version} — a later run the same morning; supersedes v{version - 1}"
    if note:
        what += f". {note}"
    who = f"**For:** {owner}\n" if owner else ""
    by = f"**Commissioned by:** {owner.split()[0]} direct\n" if owner else ""
    return (
        who
        + "**Produced by:** Reader (the overnight markets brief pipeline)\n"
        + by
        + f"**Date:** {local.strftime('%Y-%m-%d')}\n"
        + f"**Version:** {what}\n"
        + f"**Project:** {PROJECT}\n"
        + "**Related:**\n"
        + f"- Committed copy: `Reader/briefs/{brief_path.name}`\n"
        + f"- Run report and audit trail: `Reader/data/runs/{run_id}/report.md`\n"
        + "\n---\n\n"
    )


def copy_to_workbench(text: str, brief_path: Path, now: datetime, tz: str, run_id: str, workbench: Path,
                      note: str | None = None, owner: str = "") -> Path:
    """Writes the brief, headed by the workbench's provenance block, and returns the new path.
    Raises if the folder is missing (Drive not mounted): the caller decides how loudly to say so."""
    if not workbench.is_dir():
        raise FileNotFoundError(f"workbench folder not found: {workbench}")
    path = workbench_filename(workbench, now, tz)
    version = 1 if path.stem.endswith(SLUG) else int(path.stem.rsplit("-v", 1)[1])
    path.write_text(provenance(now, tz, version, brief_path, run_id, note, owner) + text)
    return path
