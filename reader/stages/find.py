"""Stage 2 — find (the analyst): decide what the night's stories are and draft narrow, checkable claims.

This is the judgment step: what the developments of the night are, which matter for the morning
meeting, and what exactly the sources say about them. Grouping happens here and nowhere else, so
the stage gets an Opus-class model (config/settings.toml; `./brief replay-find` measures it). It never sees the checker's work and
cannot publish anything; every claim it drafts is re-checked from the sources by a different model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from .. import cluster
from ..config import Settings
from ..llm import LLM
from ..session import settings_for as session_settings
from ..store import parse_iso
from ..timewindow import fmt_day
from .common import AUDIENCE, Session, Window, item_line, ref_of

SYSTEM = f"""You are the markets analyst on the overnight desk for a morning briefing.

{AUDIENCE}

You receive headlines and summaries collected overnight from publishers' own feeds and from official sources, \
each with a reference like [A12]. Decide what the stories of the night are and state what is known about each \
as narrow claims that a checker can confirm from the cited items alone.

Read the whole night before deciding anything. Work out what the threads are: what happened, and what the \
sources say it moved. Rates, policy, commodities, currencies and geopolitics move each other, and you know how, \
but the brief says only what the sources say. A story is one development and what the cited items themselves \
attribute to it. Items that share a theme or a vocabulary but not a driver are different stories; a chain of \
moves that the sources connect is one story, built around what drove it. The title is the frame the reader \
sees and must be true of every claim under it. Know which way an argument points before it joins a story. \
When the sources do not say what caused what, neither do the claims.

Then:
1. Keep only stories that pass the materiality test above, most important first. Leave the rest out.
2. For each story write one to four claims. Each claim states one fact; if you would join two facts with \
"and", "while" or "with", write two claims.
   - Use only what the cited items say: no background knowledge, no inferred causes, and no figures or dates that \
are not in the items.
   - Preserve hedges and attribution. If an item says "people familiar with the matter", "is said to", \
"plans to" or "according to", the claim says so too.
   - Cite every item that directly supports the claim, including items from other publishers that report \
the same fact.
   - kind: "event" for something that happened or was announced; "report" for an outlet's report of \
unconfirmed information; "scheduled" for a future event with a stated date (earnings, votes, deadlines, \
court dates, data releases), with that date in event_date as YYYY-MM-DD; "market_move" for price or \
market moves as reported. event_date is null unless kind is "scheduled".
3. If a story continues one we have been tracking, put its id in `continues` and make the claims about what is new.
4. For each story also give a short title, category, region, the audiences it matters to, materiality \
from 1 to 5 (5 = likely to move the broad market, 3 = moves a sector or a major stock, 1 = background), \
and one sentence on why it matters for U.S. markets. That sentence is your analysis; it is never printed as fact.

Items that look like reports of the same development are listed together under a "Same development" heading. That \
grouping is mechanical, by headline similarity, and is only a hint: you decide what the stories are, and outlets \
listed apart may well be reporting one development.

Return at most 25 stories."""

Category = Literal[
    "central_banks_rates", "economic_data", "trade_geopolitics", "corporate", "deals_capital_markets",
    "regulation_legal", "markets", "energy_commodities", "other",
]
Audience = Literal["trading", "wealth", "banking"]


class FoundClaim(BaseModel):
    text: str
    refs: list[str] = Field(description="References of the items that support the claim, for example ['A3', 'A17']")
    kind: Literal["event", "report", "scheduled", "market_move"]
    event_date: str | None


class FoundStory(BaseModel):
    title: str
    continues: str | None = Field(description="Id of the tracked story this continues, for example S2; null if new")
    category: Category
    region: Literal["us", "asia", "europe_uk", "global"]
    audiences: list[Audience]
    materiality: int
    why_it_matters: str
    claims: list[FoundClaim]


class FindOut(BaseModel):
    stories: list[FoundStory]


@dataclass
class Claim:
    text: str
    item_ids: list[str]
    kind: str
    event_date: str | None


@dataclass
class Story:
    key: str
    title: str
    continues: str | None  # stored story id
    category: str
    region: str
    audiences: list[str]
    materiality: int
    why_it_matters: str
    claims: list[Claim] = field(default_factory=list)
    session: bool = False  # every cited item is from the previous session (reader/session.py)


_COMPOUND = re.compile(r",\s+(?:with|while|as)\s|;\s")


def select_groups(kept: list[dict], scores: dict[str, int], limit: int, settings: Settings) -> list[list[dict]]:
    """The analyst's input as groups of same-development items (reader/cluster.py), at most `limit` items."""
    extra = settings.stage("find").extra
    return cluster.select_groups(kept, scores, limit, float(extra.get("group_threshold", 0.45)),
                                 int(extra.get("group_size", 3)), int(extra.get("owner_floor", 0)))


def _items_block(refmap: dict[str, dict], groups: list[list[dict]] | None, tz: str, now,
                 skip: set[str] = frozenset()) -> str:
    if not groups:
        return "\n\n".join(item_line(r, it, tz, now, 500) for r, it in refmap.items() if it["id"] not in skip)
    ref_of_id = {it["id"]: r for r, it in refmap.items()}
    blocks = []
    for g in groups:
        lines = "\n\n".join(item_line(ref_of_id[it["id"]], it, tz, now, 500) for it in g)
        blocks.append(f"Same development, {len(g)} items:\n\n{lines}" if len(g) > 1 else lines)
    return "\n\n".join(blocks)


def session_note(session: Session, min_materiality: int, max_stories: int) -> str:
    return (f"Previous session: the items below were published {session.describe()}, before the overnight window, "
            f"and no brief has covered them; the reader may have missed them. Read them with the night's items: when "
            f"an overnight item continues a development from the session, that is one story, and its claims say what "
            f"is new overnight. A story built only from these items is printed in a section of its own. Return one "
            f"only if it has materiality {min_materiality} or more, and at most {max_stories} such stories, within "
            f"the 25.")


def find(llm: LLM, settings: Settings, items: list[dict], tracked: list[dict], window: Window,
         groups: list[list[dict]] | None = None, session: Session | None = None,
         session_groups: list[list[dict]] | None = None) -> tuple[list[Story], list[str]]:
    """Returns the stories plus notes about anything the code had to discard. With `groups` (from
    select_groups) the items are shown to the analyst by development; `items` must be their flattening.
    With `session` and `session_groups`, the previous session's items follow the night's in a block of their
    own, and `items` ends with their flattening; a story citing only those items is marked `session`."""
    refmap = {f"A{i}": it for i, it in enumerate(items, start=1)}
    tracked_map = {f"S{i}": row for i, row in enumerate(tracked, start=1)}

    parts = [f"Today is {window.today()}. The overnight window runs {window.describe()}."]
    if tracked_map:
        lines = []
        for ref, row in tracked_map.items():
            last = parse_iso(row["last_updated_utc"])
            lines.append(f"[{ref}] {row['title']} (last reported {fmt_day(last.date())}): {row['last_state']}")
        parts.append("Stories we have been tracking:\n" + "\n".join(lines))
    parts.append("Themes the reader follows closely:\n" + "\n".join(f"- {t}" for t in settings.themes))
    session_ids = {it["id"] for g in (session_groups or []) for it in g}
    parts.append("Items:\n\n" + _items_block(refmap, groups, settings.tz, window.end, skip=session_ids))
    if session and session_ids:
        cfg = session_settings(settings)
        parts.append(session_note(session, cfg["min_materiality"], cfg["max_stories"]) + "\n\n"
                     + _items_block(refmap, session_groups, settings.tz, window.end))
    user = "\n\n".join(parts)

    out = llm.call("find", SYSTEM, user, FindOut, expected_output=9000, reserve=0.45, label=f"{len(items)} items")
    if out is None:
        return [], []

    notes: list[str] = []
    stories: list[Story] = []
    for n, s in enumerate(out.stories, start=1):
        claims = []
        for c in s.claims:
            norm = [(r, ref_of(r, "A")) for r in c.refs]
            ids = list(dict.fromkeys(refmap[n]["id"] for _, n in norm if n in refmap))
            unknown = [r for r, n in norm if n not in refmap]
            if unknown:
                notes.append(f"Claim cited unknown items {unknown}: {c.text}")
            if not ids:
                notes.append(f"Claim dropped (no valid source): {c.text}")
                continue
            if _COMPOUND.search(c.text):
                notes.append(f"Compound claim (two facts joined; the checker sees it as one): {c.text}")
            claims.append(Claim(c.text.strip(), ids, c.kind, c.event_date if c.kind == "scheduled" else None))
        if not claims:
            continue
        cont = ref_of(s.continues, "S")
        continues = tracked_map[cont]["id"] if cont in tracked_map else None
        stories.append(Story(
            key=f"T{n}", title=s.title.strip(), continues=continues, category=s.category, region=s.region,
            audiences=list(dict.fromkeys(s.audiences)), materiality=min(5, max(1, s.materiality)),
            why_it_matters=s.why_it_matters.strip(), claims=claims,
            session=bool(session_ids) and all(i in session_ids for c in claims for i in c.item_ids),
        ))
    stories.sort(key=lambda st: -st.materiality)
    return stories, notes
