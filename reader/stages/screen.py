"""Stage 1 — screen (Haiku 4.5): read every overnight headline and keep what could matter.

High volume, simple judgment, so the cheapest model. It is tuned to keep borderline items:
dropping news here is the one mistake later stages can't repair.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel, Field

from ..config import Settings
from ..llm import LLM, StageError
from .common import AUDIENCE, Session, Window, item_line, ref_of

SYSTEM = f"""You screen overnight news for a markets briefing.

{AUDIENCE}

Score each item for how much the analyst preparing that briefing needs to see it:
3 = likely to move U.S. markets, a major stock or an industry today
2 = useful context for the morning meeting: policy, economic data, deals, notable market moves, large-company news, \
overnight developments in Asia or Europe
1 = marginal
0 = not relevant: lifestyle, personal-finance advice, opinion or features without news, sports, celebrity, \
routine administrative notices, small-company press releases

If you are unsure between 1 and 2, choose 2; an analyst reviews everything scored 2 or 3. Score every item."""


class Score(BaseModel):
    ref: str = Field(description="The item's reference, for example A12")
    score: int


class ScreenOut(BaseModel):
    scores: list[Score]


def screen(llm: LLM, settings: Settings, items: list[dict], window: Window,
           session: Session | None = None) -> tuple[list[dict], dict[str, int]]:
    cfg = settings.stage("screen")
    size = int(cfg.extra.get("batch_size", 60))
    system = SYSTEM + "\n\nThemes this reader follows closely:\n" + "\n".join(f"- {t}" for t in settings.themes)
    batches = [items[i:i + size] for i in range(0, len(items), size)]

    def run(numbered: tuple[int, list[dict]]) -> tuple[list[dict], dict[str, int]]:
        n, chunk = numbered
        refmap = {f"A{i}": it for i, it in enumerate(chunk, start=1)}
        lines = "\n\n".join(item_line(r, it, settings.tz, window.end, 240) for r, it in refmap.items())
        user = f"Overnight window: {window.describe()}."
        if session:
            user += (f" Items published {session.describe()} are from the previous U.S. session, which no brief has "
                     f"covered; score them by the same standard.")
        user += f"\n\nItems:\n\n{lines}"
        try:
            out = llm.call("screen", system, user, ScreenOut, expected_output=14 * len(chunk) + 200,
                           label=f"batch {n} of {len(batches)}")
        except StageError:
            out = None
            if not llm.dry_run:  # fail open: keep the whole batch for the analyst
                return list(chunk), {it["id"]: 2 for it in chunk}
        if out is None:  # dry run
            return [], {}
        got = {ref_of(s.ref, "A"): s.score for s in out.scores if ref_of(s.ref, "A") in refmap}
        kept, scores = [], {}
        for r, it in refmap.items():
            score = got.get(r, 2)  # an item the model skipped is kept, not silently dropped
            scores[it["id"]] = score
            if score >= 2:
                kept.append(it)
        return kept, scores

    kept: list[dict] = []
    scores: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for k, s in pool.map(run, enumerate(batches, start=1)):
            kept.extend(k)
            scores.update(s)
    return kept, scores
