"""`./brief eval-check`: run the checker against saved cases of past errors.

Every error found in a live brief becomes a case in tests/fixtures/checker.json: the claim as the
analyst drafted it, the source text exactly as the checker saw it, and what a correct verdict looks
like. This runs the real checker (a few cents a case) so prompt or model changes can be judged
against the mistakes that mattered, not against a stand-in.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .budget import Budget
from .config import DATA_DIR, ROOT, Settings
from .evidence import Evidence
from .guards import quote_in, set_ordinary_words, unsupported_entities
from .llm import LLM, StageError
from .stages.check import SYSTEM, CheckOut, check_prompt, claim_text, document_block, match_verdicts, support_texts
from .stages.find import Claim

FIXTURES = ROOT / "tests" / "fixtures" / "checker.json"


def run_cases(settings: Settings, path: Path = FIXTURES) -> int:
    cases = json.loads(path.read_text())
    if (DATA_DIR / "reader.db").exists():  # the name guard as the live run applies it
        from .store import Store

        set_ordinary_words(Store(DATA_DIR / "reader.db").ordinary_words())
    budget = Budget(settings, 1.0)
    try:
        llm = LLM(settings, budget)
    except StageError as e:
        print(e)
        return 1
    failed = 0
    for case in cases:
        evs: dict[str, Evidence] = {}
        docs = []
        for i, d in enumerate(case["documents"], start=1):
            ref = f"E{i}"
            evs[ref] = Evidence(item_id=ref, publisher=d["publisher"], section=d.get("section", ""),
                                tier=int(d.get("tier", 1)), owner=d.get("owner", d["publisher"]), kind="news", url="",
                                published_utc=d["published_utc"], title=d["text"].split("\n")[0], text=d["text"],
                                note="fixture", reconfirmed=True)
            docs.append(document_block(ref, evs[ref], settings.tz))
        claim = case["claim"]
        prompt = check_prompt(docs, [f"[C1] {claim} (cites {', '.join(evs)})"], case["today"])
        try:
            out = llm.call("check", SYSTEM, prompt, CheckOut, expected_output=900, cache_system=True, label=case["name"])
        except StageError as e:
            print(f"FAIL  {case['name']}\n      call failed: {e}")
            failed += 1
            continue
        v = match_verdicts(out.verdicts, [Claim(claim, list(evs), "event", None)]).get(1)
        problems: list[str] = []
        final: str | None = None
        if v is None:
            problems.append("checker returned no verdict for the claim")
        else:
            if v.verdict not in case["expect"]:
                problems.append(f"verdict {v.verdict!r}, expected one of {case['expect']}")
            if v.verdict != "unsupported":
                good = [q for q in v.quotes if q.doc in evs and quote_in(q.text, evs[q.doc].text)]
                if not good:
                    problems.append("no verbatim quote (code would drop the claim)")
                final = claim_text(v, claim)
                names = unsupported_entities(final, support_texts(list(evs.values())))
                if names:
                    problems.append(f"names not in the sources: {sorted(names)} (code would drop the claim)")
                    final = None
            if final:
                if case.get("must_match") and not re.search(case["must_match"], final, re.I):
                    problems.append(f"final wording lacks /{case['must_match']}/")
                if case.get("must_not_match") and re.search(case["must_not_match"], final, re.I):
                    problems.append(f"final wording still matches /{case['must_not_match']}/")
            elif v.verdict != "unsupported" and "unsupported" not in case["expect"] and final is None:
                pass  # already reported above
        status = "ok  " if not problems else "FAIL"
        failed += bool(problems)
        print(f"{status}  {case['name']}")
        if v is not None:
            print(f"      verdict: {v.verdict}; final: {final or '(dropped)'}")
            print(f"      note: {v.note}")
        for p in problems:
            print(f"      - {p}")
    print(f"\n{len(cases) - failed} of {len(cases)} cases pass. Cost ${budget.spent:.3f}.")
    return 1 if failed else 0
