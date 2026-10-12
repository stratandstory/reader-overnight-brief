"""Stage 4 — write (the editor): rank and write the brief from checked claims only.

The editor sees verified claims, never raw feeds, and has no way to fetch anything. It
cites claim ids for the headline and for every sentence, so each line can be audited
against exactly the claims it states. Code attaches the links, publishers and times, and
code enforces what may appear where (unconfirmed reports only under Developing, ceilings).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from ..config import Settings
from ..llm import LLM
from ..store import parse_iso
from ..timewindow import fmt_day, fmt_time, fmt_time_or_day
from .check import CheckedStory, VerifiedClaim
from ..session import settings_for as session_settings
from .common import AUDIENCE, Session, Window, ref_of

SYSTEM = f"""You write the overnight markets brief.

{AUDIENCE}

The reader knows markets well and has three minutes. You receive stories that have passed an independent check. \
Each has verified claims ([V1], [V2] ...) with a status:
- confirmed: established by an official source or by independent outlets
- reported: reported as fact by one outlet
- attributed: an outlet's report of unconfirmed information; name the outlet in the sentence ("Bloomberg reports ...")
- developing: unconfirmed, from a less authoritative source; it may appear only under developing

Write:
- summary: one sentence of at most 30 words on what matters most this morning, with the claims it states. Build \
it from overnight stories; the previous session has its own section.
- top: up to 5 items that matter most for today's U.S. session, most important first.
- second: up to 10 further items worth knowing, most important first.
- developing: up to 5 unconfirmed reports worth watching: items whose claims are all attributed or developing. \
Reported or confirmed news goes in top or second, or is left out.
- session: highlights of the previous trading day: stories marked "previous session", reported during the last U.S. \
session before the overnight window and in no brief yet. At most the number given with the stories, most important \
first, and only those that matter for today. A previous-session story goes only here; every other story is overnight \
news and never goes here.
- calendar: the [K] ids of scheduled events to show, in date order. Include every event within the next five \
trading days that matters for U.S. markets; include later events only if they are strategically important.
These are ceilings. A quiet night gets a short brief. Never pad, and leave out anything that fails the materiality test.

For each item:
- story: the [T] id it comes from. One item per story.
- headline: plain and specific, at most 12 words, with headline_claims: the claims it states.
- what_changed: one to three sentences (one or two for second-tier and developing items), each with the claims \
it states. State only what those claims say, keeping their hedges and attribution.
- why_it_matters: one sentence on what this means for U.S. markets in the next session: the risk it raises, what \
it puts in focus, or the question clients will ask. Reason only from this item's claims. Do not bring in outside or \
historical facts, and do not predict prices or their direction. If the brief's settings switch analysis off, this \
sentence is discarded, so never put a fact only here.
- audiences: who needs it (trading, wealth, banking).
- For a story we reported before, say what is new since then; do not retell the background.

Every headline and sentence must be true on its own terms. Never attach a figure, date or detail from one claim to \
the subject of another, and never make a subject more specific or more general than its claim says (for example, \
"long-term yields" is not "the 10-year yield"). When two claims are about different subjects (the 10-year yield and \
long-term yields; a company and its sector), name each subject in full so a reader cannot take one for the other.

Tense and time: a claim written while something was still under way ("heading for its worst week", "is set to") \
stays that way; never state it as done. Write "today", "this morning", "the open" or "today's session" only when the \
next U.S. session is today; otherwise name the day ("into Monday's open"). Give dates as dates, not weekdays. A \
previous-session story happened during that session: never call it overnight or this morning's.

Register: a senior strategist's morning note. Short declarative sentences, concrete nouns, no filler or stock \
phrases, no exclamation marks, no markdown. Write the brief and nothing else."""

Audience = Literal["trading", "wealth", "banking"]


class Sentence(BaseModel):
    text: str
    claims: list[str] = Field(description="Ids of the verified claims this sentence states, for example ['V4']")


class Item(BaseModel):
    story: str = Field(description="The story's id, for example T3")
    headline: str
    headline_claims: list[str] = Field(description="Ids of the claims the headline states, for example ['V4']")
    what_changed: list[Sentence]
    why_it_matters: str
    audiences: list[Audience]


class WriteOut(BaseModel):
    summary: str
    summary_claims: list[str] = Field(description="Ids of the claims the summary states, for example ['V1', 'V9']")
    top: list[Item]
    second: list[Item]
    developing: list[Item]
    session: list[Item] = Field(description="Previous-session stories only, most important first; empty when none")
    calendar: list[str] = Field(description="Ids of the scheduled events to show, for example ['K1', 'K3']")


@dataclass
class Line:
    text: str
    claims: list[VerifiedClaim]


@dataclass
class BriefItem:
    section: str
    story_key: str
    headline: Line
    sentences: list[Line]
    why_it_matters: str
    audiences: list[str]
    continues: str | None
    notes: list[str] = field(default_factory=list)

    @property
    def claims(self) -> list[VerifiedClaim]:
        seen: dict[str, VerifiedClaim] = {}
        for line in [self.headline, *self.sentences]:
            for c in line.claims:
                seen.setdefault(c.id, c)
        return list(seen.values())

    @property
    def what_changed(self) -> str:
        return " ".join(s.text for s in self.sentences)


@dataclass
class CalendarEntry:
    ref: str
    day: date
    title: str
    publisher: str
    url: str
    later: bool


@dataclass
class Brief:
    summary: Line
    top: list[BriefItem]
    second: list[BriefItem]
    developing: list[BriefItem]
    calendar: list[CalendarEntry]
    notes: list[str] = field(default_factory=list)
    session: list[BriefItem] = field(default_factory=list)  # the previous trading day's highlights

    def items(self) -> list[BriefItem]:
        return self.top + self.second + self.developing + self.session


def _sources(vc: VerifiedClaim, tz: str, now) -> str:
    return "; ".join(f"{ev.publisher}, {fmt_time_or_day(parse_iso(ev.published_utc), tz, now, ev.day_only)}" for ev in vc.evidence)


def write(llm: LLM, settings: Settings, checked: list[CheckedStory], tracked: dict[str, dict],
          calendar: list[CalendarEntry], window: Window, session: Session | None = None,
          session_keys: set[str] = frozenset()) -> Brief | None:
    """`session_keys` are the stories the previous session's section may hold (reader/session.py decides)."""
    stories = [cs for cs in checked if cs.verified]
    session_keys = set(session_keys) if session else set()
    blocks = []
    for cs in stories:
        st = cs.story
        mark = ", previous session" if st.key in session_keys else ""
        lines = [f"[{st.key}] {st.title} — {st.category.replace('_', ' ')}, {st.region.replace('_', '/')}, "
                 f"materiality {st.materiality}/5, audiences: {', '.join(st.audiences) or 'n/a'}{mark}",
                 f"Analyst's note (not a fact): {st.why_it_matters}"]
        prior = tracked.get(st.continues or "")
        if prior:
            last = fmt_day(parse_iso(prior["last_updated_utc"]).date())
            lines.append(f"We last reported this on {last}: {prior['last_state']}")
        lines.append("Verified claims:")
        for vc in cs.verified:
            lines.append(f"  [{vc.id}] ({vc.status}) {vc.text} — {_sources(vc, settings.tz, window.end)}")
        blocks.append("\n".join(lines))
    cal_lines = [
        f"[{c.ref}] {fmt_day(c.day)} — {c.title} ({c.publisher})" + (" [beyond five trading days]" if c.later else "")
        for c in calendar
    ]
    next_open = window.next_session()
    session_line = ("The next U.S. cash session opens today." if next_open == "today"
                    else f"Markets are closed today; the next U.S. cash session opens {next_open}.")
    session_cap = session_settings(settings)["max_stories"]
    previous = (f"Stories marked \"previous session\" were reported {session.describe()}, before the overnight "
                f"window; at most {session_cap} go under session.\n\n") if session_keys else ""
    user = (f"Today is {window.today()}. The overnight window runs {window.describe()}. {session_line}\n\n"
            + previous + "Stories:\n\n" + ("\n\n".join(blocks) or "(none passed the check)") +
            "\n\nScheduled events:\n" + ("\n".join(cal_lines) or "(none)"))

    out = llm.call("write", SYSTEM, user, WriteOut, expected_output=7000, reserve=0.08, label=f"{len(stories)} stories")
    if out is None:
        return None
    return place(out, stories, calendar, settings, session_keys)


def place(out: WriteOut, stories: list[CheckedStory], calendar: list[CalendarEntry], settings: Settings,
          session_keys: set[str] = frozenset()) -> Brief:
    """Enforce, in code, what the editor may put where and what each line may cite. The previous session's
    section holds `session_keys` stories and nothing else, wherever the editor filed them."""
    brief_cfg = settings.raw["brief"]
    analysis = brief_cfg.get("analysis", "off")
    by_story = {cs.story.key: cs for cs in stories}
    claims = {vc.id: vc for cs in stories for vc in cs.verified}
    notes: list[str] = []

    def resolve(ids: list[str], story_key: str | None) -> list[VerifiedClaim]:
        refs = dict.fromkeys(ref_of(c, "V") for c in ids)
        return [claims[r] for r in refs if r in claims and (story_key is None or claims[r].story_key == story_key)]

    placed: dict[str, list[BriefItem]] = {"top": [], "second": [], "developing": [], "session": []}
    moved: list[BriefItem] = []  # filed under Developing but not unconfirmed; they keep their place in the brief's length
    seen: set[str] = set()
    for filed in ("top", "second", "developing", "session"):
        for it in getattr(out, filed):
            section = filed
            key = ref_of(it.story, "T")
            cs = by_story.get(key)
            if cs is None or key in seen:
                continue
            sentences = []
            for s in it.what_changed:
                cited = resolve(s.claims, key)
                if cited:
                    sentences.append(Line(s.text.strip(), cited))
                else:
                    notes.append(f"Dropped a sentence citing no verified claim of its story: {s.text}")
            if not sentences:
                notes.append(f"Dropped '{it.headline}': no sentence rests on a verified claim")
                continue
            head_claims = resolve(it.headline_claims, key) or [c for s in sentences for c in s.claims]
            item = BriefItem(
                section=section, story_key=key, headline=Line(it.headline.strip(), head_claims), sentences=sentences,
                why_it_matters=it.why_it_matters.strip() if analysis != "off" else "",
                audiences=list(dict.fromkeys(it.audiences)),
                continues=cs.story.continues,
            )
            if key in session_keys:
                if filed != "session":
                    notes.append(f"Moved '{it.headline}' to the previous session's highlights: all its sources are "
                                 f"from that session")
                item.section = "session"
                placed["session"].append(item)
                seen.add(key)
                continue
            if filed == "session":
                section = item.section = "second"
                notes.append(f"Moved '{it.headline}' out of the previous session's highlights: it has overnight sources")
            if section != "developing" and all(c.status == "developing" for c in item.claims):
                item.section = "developing"
                notes.append(f"Moved '{it.headline}' to Developing: its only support is an unconfirmed report")
            elif section == "developing" and any(c.status in ("reported", "confirmed") for c in item.claims):
                # Developing is headed "not yet confirmed"; Mon Oct 5 the editor filed Bolsonaro's first-round
                # lead there, reported by Bloomberg, WSJ and the FT
                item.section = "second"
                moved.append(item)
                notes.append(f"Moved '{it.headline}' out of Developing: its claims are reported, not unconfirmed")
                seen.add(key)
                continue
            placed[item.section].append(item)
            seen.add(key)
    top_max, second_max, dev_max = brief_cfg["top_max"], brief_cfg["second_max"], brief_cfg["developing_max"]
    overflow = placed["top"][top_max:]
    for item in overflow:
        item.section = "second"
    placed["second"] = (overflow + placed["second"])[:second_max] + moved[:dev_max]
    placed["top"] = placed["top"][:top_max]
    placed["developing"] = placed["developing"][:dev_max]
    session_max = session_settings(settings)["max_stories"]
    for item in placed["session"][session_max:]:
        notes.append(f"Left out '{item.headline.text}': past the previous session's ceiling of {session_max}")
    placed["session"] = placed["session"][:session_max]

    cal_by_ref = {c.ref: c for c in calendar}
    chosen = [cal_by_ref[r] for r in dict.fromkeys(ref_of(c, "K") for c in out.calendar) if r in cal_by_ref]
    chosen.sort(key=lambda c: (c.day, c.title))
    summary = Line(out.summary.strip(), resolve(out.summary_claims, None))
    return Brief(summary=summary, top=placed["top"], second=placed["second"],
                 developing=placed["developing"], calendar=chosen, notes=notes, session=placed["session"])
