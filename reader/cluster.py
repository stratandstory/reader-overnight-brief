"""Near-duplicate grouping of screened items, so the analyst's cap counts developments, not copies.

Several outlets report the same development, and each copy took a slot at the analyst's item cap
(`max_items` in settings.toml), so the cap cut distinct stories while keeping duplicates. This
groups the kept items by headline-and-summary similarity, deterministically, before the cap is
applied. Nothing here decides what a story is: that stays with the analyst, which still sees every
member of a group and cites each one. The threshold was tuned against the analyst's own groupings
on five live mornings (the author's development log, 2026-10-02).
"""

from __future__ import annotations

import math
import re
from collections import Counter

STOP = frozenset("""
a an the and or but of to in on at for with by from as is are was were be been being has have had do does did
will would could should may might can this that these those it its into over under after before than then there
their they them he she his her we our you your not no nor so if while about up down out new says said say amid
also more most just than via per vs
""".split())

_TOKEN = re.compile(r"[a-z0-9][a-z0-9'.-]*[a-z0-9]|[a-z0-9]")


def tokens(text: str) -> list[str]:
    out = []
    for t in _TOKEN.findall((text or "").replace("’", "'").lower()):
        t = t.strip(".'-")
        if t.endswith("'s"):
            t = t[:-2]
        if len(t) < 2 or t in STOP:
            continue
        out.append(t)
    return out


def _counts(item: dict) -> Counter:
    c = Counter(tokens(item["title"]))
    for t in list(c):
        c[t] *= 2  # the headline counts double
    c.update(tokens((item.get("summary") or "")[:400]))
    return c


def vectors(items: list[dict]) -> dict[str, dict[str, float]]:
    """TF-IDF over this night's items, L2-normalised, keyed by item id."""
    raw = {it["id"]: _counts(it) for it in items}
    df: Counter = Counter()
    for c in raw.values():
        df.update(c.keys())
    n = len(items)
    out = {}
    for iid, c in raw.items():
        v = {t: w * (math.log((1 + n) / (1 + df[t])) + 1) for t, w in c.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        out[iid] = {t: x / norm for t, x in v.items()}
    return out


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(x * b[t] for t, x in a.items() if t in b)


def group(items: list[dict], threshold: float) -> list[list[dict]]:
    """Leader clustering in the given order: an item joins the first group whose leader it resembles
    at or above the threshold, else starts a group. Order the items best first, so the leader of each
    group is its best member. No chaining: membership is always judged against the leader."""
    vecs = vectors(items)
    groups: list[list[dict]] = []
    leaders: list[dict[str, float]] = []
    for it in items:
        v = vecs[it["id"]]
        best, best_sim = None, threshold
        for g, lv in zip(groups, leaders):
            s = cosine(v, lv)
            if s >= best_sim:
                best, best_sim = g, s
        if best is None:
            groups.append([it])
            leaders.append(v)
        else:
            best.append(it)
    return groups


def rank(kept: list[dict], scores: dict[str, int], owner_floor: int = 0) -> list[dict]:
    """Highest screen score first. Within a score, each owner's `owner_floor` newest items come first,
    owners taking turns (primary sources first in each turn); then the rest by tier and recency.

    Without the floor, tier decided every tie: on Mon Oct 5 the 200-item cap had 121 slots for 259
    score-2 items, Bloomberg, Dow Jones and the FT (tier 1) had 185 of them, and none of the 73 from
    the nine other owners led a development."""
    newest_first = sorted(kept, key=lambda it: it["published_utc"], reverse=True)
    turn: dict[str, int] = {}
    seen: Counter = Counter()
    for it in newest_first:
        key = (scores.get(it["id"], 2), it.get("owner"))
        turn[it["id"]] = seen[key]
        seen[key] += 1

    def order(it: dict) -> tuple:
        t = turn[it["id"]]
        if t < owner_floor:
            return (-scores.get(it["id"], 2), 0, t, it["tier"])
        return (-scores.get(it["id"], 2), 1, it["tier"], 0)

    return sorted(newest_first, key=order)  # stable: ties stay newest first


def select_groups(kept: list[dict], scores: dict[str, int], limit: int, threshold: float,
                  per_group: int = 6, owner_floor: int = 0) -> list[list[dict]]:
    """The analyst's input as groups of same-development items, best group first, at most `limit`
    items in all. Groups are ranked by their leader (see `rank`); within a group, members from owners
    not yet represented come first, so a development reported by five outlets shows the analyst
    several owners rather than one owner's five sections."""
    ranked = rank(kept, scores, owner_floor)
    out: list[list[dict]] = []
    n = 0
    for g in group(ranked, threshold):
        if n >= limit:
            break
        chosen, seen_owners, rest = [], set(), []
        for it in g:  # g is already in rank order
            (chosen if it.get("owner") not in seen_owners else rest).append(it)
            seen_owners.add(it.get("owner"))
        members = (chosen + rest)[:min(per_group, limit - n)]
        members.sort(key=lambda it: it["published_utc"], reverse=True)
        out.append(members)
        n += len(members)
    return out
