"""Stage 5 — audit (the last reader, plus code): no line of the brief may say more than the claims it cites.

A different model from the writer judges every headline and sentence against exactly the
claims that line cites. Code then applies tests no model can override: every figure in a
line must appear in that line's claims, and a sentence resting on an unconfirmed report must
name the outlet. A line that fails falls back to its verified claims' own wording.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from ..config import Settings
from ..guards import dropped_hedges, unsupported_entities, unsupported_numbers
from ..llm import LLM, StageError
from ..render import short
from .write import Brief, Line

SYSTEM = """You are the last reader before a markets briefing goes out. Every line of the draft is listed with \
the verified claims it rests on. Judge each line only against its own claims.

For a headline, a what-changed sentence or the summary, answer "ok" only if every fact in it (subject, figures, \
dates, direction of change, degree of certainty, attribution) is stated in its claims. Look especially for:
- a figure, date or detail from one claim attached to the subject of another
- a subject made more specific or more general than its claim says ("the 10-year yield" for "long-term yields")
- two facts joined so that one appears to explain or contain the other
- more certainty than the claim carries ("will" for "plans to")
- a missing attribution where a claim is marked attributed or developing
Otherwise answer "fix" with a corrected line that uses only its claims, or "drop".

Then read each item as a whole: its headline and sentences together. If a reader would take away a fact that no \
claim states because of how the lines sit together (one sentence's subject appears to be the subject of the next; \
a figure or record in one sentence reads as belonging to the subject of another; a completed-sounding headline sits \
over a sentence that says "heading for"), answer "fix" on the line that creates the impression, naming both subjects \
in full or restoring the hedge.

Tense: a line must not say something has happened when its claim says it was under way, expected or planned. \
Time words ("Tuesday", "this week", "over the weekend") must match the claim; do not add "today" or "the open" unless \
a claim places the event today.

A why-it-matters line is analysis and may draw implications from its claims. Answer "fix" or "drop" if it states \
a fact that is not in its claims, contradicts them, relies on outside or historical facts, or predicts a price \
move or level.

Return one verdict for every line id, with a reason of at most twelve words."""


class LineCheck(BaseModel):
    line: str = Field(description="The line's id, for example B2.h, B2.s1, B2.w or SUMMARY")
    verdict: Literal["ok", "fix", "drop"]
    fixed: str | None
    reason: str


class AuditOut(BaseModel):
    lines: list[LineCheck]


_LINE_ID = re.compile(r"\b(SUMMARY|B\d+\.(?:h|w|s\d+))\b", re.I)


def _line_id(value: str) -> str | None:
    m = _LINE_ID.search(value or "")
    if not m:
        return None
    ident = m.group(1)
    return "SUMMARY" if ident.upper() == "SUMMARY" else "B" + ident[1:].lower()


def _claim_block(line: Line) -> str:
    return "\n".join(
        f"    [{c.id}] ({c.status}; {', '.join(sorted({e.publisher for e in c.evidence}))}) {c.text}" for c in line.claims
    ) or "    (none)"


def _support(line: Line) -> list[str]:
    """Claim texts, their verbatim quotes, and the publishers behind them (so attribution is never a foreign name)."""
    return ([c.text for c in line.claims] + [q for c in line.claims for q in c.quotes]
            + [f"{e.publisher} {short(e.publisher)}" for c in line.claims for e in c.evidence])


def _claims_wording(line: Line) -> str:
    return " ".join(c.text.rstrip(".") + "." for c in line.claims)


_HEADLINE_WORDS = 22
# "…, the WSJ reported." / "…, Bloomberg and The Straits Times reported." Struck from a headline built from a
# reported or confirmed claim (the item's sentences and links carry the attribution); kept for an unconfirmed one.
_TRAILING_ATTRIBUTION = re.compile(r",\s+(?:the\s+)?(?:(?:[A-Z][\w.&'’-]*|and)\s+){1,6}(?:reported|reports)\.?$")
# Where a claim can end early and still say something whole: a comma (not one before a year), a semicolon,
# or a conjunction that starts a second fact.
_CLAUSE_BREAK = re.compile(r",\s(?!\d{4}\b)|;\s|\s(?:even as|amid|after|while|despite|following|because|as)\s")
# The checker writes resolved dates into claims ("on Wednesday, September 30, to defend"); a headline keeps the weekday.
_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
_WEEKDAY_DATE = re.compile(rf"\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday), (?:{_MONTHS}) \d{{1,2}}(?:, \d{{4}})?,?")
_AS_PHRASE = set("much many well high low long far soon large little early late such known same so just twice "
                 "quickly good big".split())


def _first_clause(text: str) -> str | None:
    """The claim up to its first clean clause break, if that leaves five to twenty words. Skips "as" inside
    "as much as" and the like, and a break that would end on a short aside ("Schneider, the French group")."""
    for m in _CLAUSE_BREAK.finditer(text):
        head = text[:m.start()].rstrip(" ,;")
        if m.group(0).strip() == "as":
            before = head.split()[-1:] or [""]
            after = text[m.end():].split()[:1] or [""]
            if before[0].lower() in _AS_PHRASE or after[0].lower() in _AS_PHRASE:
                continue
        words = head.split()
        if len(words) < 5:
            continue
        segments = re.split(r",\s(?!\d{4}\b)", head)
        if len(segments) > 1 and len(segments[-1].split()) < 4:
            continue
        return head if len(words) <= _HEADLINE_WORDS else None
    return None


def _headline_from(line: Line) -> str:
    """A headline in the claims' own words, for when the writer's and the audit's both fail: the first claim
    that is short enough whole, or that ends cleanly at a clause break; a cut with an ellipsis only if none does."""
    if not line.claims:
        return "Update"
    texts = []
    for c in line.claims:
        t = c.text.strip().rstrip(".")
        if c.status in ("reported", "confirmed"):
            t = _TRAILING_ATTRIBUTION.sub("", t + ".").rstrip(".")
        texts.append(_WEEKDAY_DATE.sub(r"\1", t))
    for t in texts:
        if len(t.split()) <= _HEADLINE_WORDS:
            return t
        clause = _first_clause(t)
        if clause:
            return clause
    words = texts[0].split()[:14]
    while len(words) > 5 and words[-1].lower() in ("the", "a", "an", "of", "for", "and", "to", "in", "with", "on", "by", "at"):
        words.pop()
    return " ".join(words) + "…"


def _claim_outlets(claim) -> list[str]:
    """The outlets (not primary sources) behind an unconfirmed claim: a sentence resting on it must name one."""
    if claim.status not in ("attributed", "developing"):
        return []
    return sorted({e.publisher for e in claim.evidence if e.tier > 0})


def _names_outlet(text: str, outlets: list[str]) -> bool:
    """Whether `text` names one of `outlets`, as whole words: "FT" is not found in "after"."""
    for pub in outlets:
        names = {pub, short(pub), pub.replace("The ", "")}
        if pub == "The Wall Street Journal":
            names.add("the Journal")
        if any(re.search(rf"(?<!\w){re.escape(n)}(?!\w)", text, re.I) for n in names):
            return True
    return False


def _with_outlets(text: str, outlets: list[str]) -> str:
    verb = "report" if len(outlets) > 1 else "reports"
    return f"{' and '.join(short(o) for o in outlets)} {verb}: {text}"


def _attribute(text: str, line: Line) -> tuple[str, str | None]:
    """The sentence with every unconfirmed claim's outlet named, and how: None (already named), "prefixed" or
    "split". A prefix covers the whole sentence, so it is used only when every claim in the sentence rests on
    the outlets it names. Otherwise the sentence falls back to its claims' own wording, one sentence per claim,
    each naming its own outlets: "Bloomberg reports:" must never sit over a claim only the WSJ reported (Tue Oct 6)."""
    unnamed = [c for c in line.claims if _claim_outlets(c) and not _names_outlet(text, _claim_outlets(c))]
    if not unnamed:
        return text, None
    outlets = sorted({o for c in unnamed for o in _claim_outlets(c)})
    if all(set(outlets) <= {e.publisher for e in c.evidence} for c in line.claims):
        return _with_outlets(text, outlets), "prefixed"
    parts = []
    for c in line.claims:
        own = c.text.rstrip(".") + "."
        need = _claim_outlets(c)
        parts.append(_with_outlets(own, need) if need and not _names_outlet(own, need) else own)
    return " ".join(parts), "split"


def audit(llm: LLM, settings: Settings, brief: Brief) -> list[str]:
    """Edits the brief in place; returns notes on every change for the run report."""
    notes: list[str] = []
    items = brief.items()
    refmap = {f"B{i}": it for i, it in enumerate(items, start=1)}

    blocks = [f"[SUMMARY] {brief.summary.text}\n  claims:\n{_claim_block(brief.summary)}"]
    for ref, it in refmap.items():
        parts = [f"[{ref}.h] Headline: {it.headline.text}\n  claims:\n{_claim_block(it.headline)}"]
        for k, s in enumerate(it.sentences, start=1):
            parts.append(f"[{ref}.s{k}] What changed: {s.text}\n  claims:\n{_claim_block(s)}")
        if it.why_it_matters:
            parts.append(f"[{ref}.w] Why it matters: {it.why_it_matters}\n  claims:\n{_claim_block(Line('', it.claims))}")
        blocks.append("\n".join(parts))
    user = "Lines to check:\n\n" + "\n\n".join(blocks)

    verdicts: dict[str, LineCheck] = {}
    try:
        out = llm.call("audit", SYSTEM, user, AuditOut, expected_output=1500 + 60 * len(items) * 4,
                       label=f"{len(items)} items")
        if out is not None:
            for v in out.lines:
                ident = _line_id(v.line)
                if ident and ident not in verdicts:
                    verdicts[ident] = v
    except StageError as e:
        notes.append(f"Model audit unavailable ({e}); mechanical checks still applied")

    def apply(ident: str, line: Line, label: str, fallback: str, allow_drop: bool, factual: bool = True) -> str | None:
        """The audited text for a line, or None to drop it. Factual lines (everything but why-it-matters) are
        also held to the code guards: figures, names and hedges must come from the line's own claims."""
        v = verdicts.get(ident)
        text = line.text
        if v is not None and v.verdict != "ok":
            if v.verdict == "fix" and v.fixed and not unsupported_numbers(v.fixed, _support(line)) \
                    and not (factual and unsupported_entities(v.fixed, _support(line))):
                text = v.fixed.strip()
                notes.append(f"Audit corrected {label}: {v.reason} (was: {line.text})")
            elif v.verdict == "drop" and allow_drop:
                notes.append(f"Audit removed {label}: {v.reason} (was: {line.text})")
                return None
            else:
                text = fallback
                notes.append(f"Audit flagged {label} ({v.reason}); used the verified claims' wording (was: {line.text})")
        bad = unsupported_numbers(text, _support(line)) if text != fallback else set()
        if bad:
            notes.append(f"{label}: figures {sorted(bad)} are not in its claims; used the claims' wording (was: {text})")
            text = fallback
        if factual and text != fallback:
            names = unsupported_entities(text, _support(line))
            if names:
                notes.append(f"{label}: names {sorted(names)} are not in its claims; used the claims' wording (was: {text})")
                text = fallback
        if factual and text != fallback:
            hedges = dropped_hedges(text, [c.text for c in line.claims])
            if hedges:
                notes.append(f"{label}: states as done what its claims hedge ({', '.join(sorted(hedges))}); "
                             f"used the claims' wording (was: {text})")
                text = fallback
        return text

    for ref, it in refmap.items():
        name = f"'{it.headline.text}'"
        it.headline.text = apply(f"{ref}.h", it.headline, f"the headline {name}", _headline_from(it.headline), False)
        kept = []
        for k, s in enumerate(it.sentences, start=1):
            text = apply(f"{ref}.s{k}", s, f"a sentence in {name}", _claims_wording(s), True)
            if text is None:
                continue
            attributed, how = _attribute(text, s)
            if how == "prefixed":
                notes.append(f"Added attribution to a sentence in {name}")
            elif how == "split":
                notes.append(f"A sentence in {name} rests on different outlets for different claims; each claim "
                             f"now names its own (was: {text})")
            s.text = attributed
            kept.append(s)
        it.sentences = kept
        if it.why_it_matters:
            why = apply(f"{ref}.w", Line(it.why_it_matters, it.claims), f"the why-it-matters line of {name}", "", True,
                        factual=False)
            it.why_it_matters = why or ""
        if not it.sentences:
            it.section = "dropped"
            notes.append(f"Dropped {name}: no sentence survived the audit")

    brief.top = [i for i in brief.top if i.section != "dropped"]
    brief.second = [i for i in brief.second if i.section != "dropped"]
    brief.developing = [i for i in brief.developing if i.section != "dropped"]
    brief.session = [i for i in brief.session if i.section != "dropped"]

    lead = next(iter(brief.items()), None)
    lead_sentence = lead.sentences[0].text if lead else "Nothing material passed the evidence check this morning."
    summary = apply("SUMMARY", brief.summary, "the summary line", lead_sentence, False) if brief.summary.claims else None
    if not summary:
        notes.append(f"Summary line cited no verified claims; used the lead item's first sentence (was: {brief.summary.text})")
        summary = lead_sentence
    brief.summary.text = summary
    return notes
