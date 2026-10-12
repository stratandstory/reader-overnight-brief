"""End-to-end run with a stand-in for the API: exercises every stage's plumbing and every guard."""

import os
import re
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from reader import pipeline
from reader.config import load_settings
from reader.evidence import Evidence
from reader.stages.audit import AuditOut, LineCheck
from reader.stages.check import CheckOut, Quote, Verdict
from reader.stages.find import FindOut, FoundClaim, FoundStory
from reader.stages.screen import ScreenOut, Score
from reader.stages.write import Item, Sentence, WriteOut
from reader.store import Store, iso

NY = ZoneInfo("America/New_York")
NOW = datetime(2026, 9, 29, 6, 30, tzinfo=NY)

ITEMS = [
    ("wsj_markets", "https://wsj.example/waller", "Fed's Waller says further rate cuts are likely this year",
     "Federal Reserve Governor Christopher Waller said further cuts are likely.", 5),
    ("cnbc_top", "https://cnbc.example/waller", "Fed's Waller says further rate cuts are likely this year",
     "Waller spoke in New York.", 4),
    ("bloomberg_markets", "https://bbg.example/acme", "Acme is in talks to buy Widget, people familiar with the matter say",
     "The deal could be announced within weeks.", 3),
    ("prn_all", "https://prn.example/acme-q3", "Acme to report third-quarter results on October 6, 2026",
     "Acme will host a conference call.", 2),
    ("scmp_business", "https://scmp.example/pboc", "China's central bank is said to weigh a cut to reserve requirements, people familiar say",
     "", 1),
]


def seed(store: Store, settings) -> dict[str, str]:
    ids = {}
    for source_id, url, title, summary, hours_ago in ITEMS:
        src = settings.source(source_id)
        published = NOW.replace(hour=6 - hours_ago)
        item = {"id": "i" + str(abs(hash(url)))[:10], "source_id": src.id, "publisher": src.publisher,
                "section": src.section, "kind": src.kind, "tier": src.tier, "owner": src.owner, "title": title,
                "summary": summary, "url": url, "published_utc": iso(published), "model_ok": True, "extra": {}}
        store.upsert_item(item)
        ids[url] = item["id"]
    return ids


class FakeLLM:
    """Answers each stage the way a careful model would, including one deliberate slip for the audit to catch."""

    def __init__(self, settings, budget, dry_run=False):
        self.settings, self.budget, self.dry_run, self.calls = settings, budget, dry_run, []

    def call(self, stage, system, user, schema, **kw):
        self.calls.append({"stage": stage, "label": kw.get("label", ""), "model": "fake", "stop_reason": "end_turn",
                           "input": len(user) // 4, "output": 100, "cost": 0.0})
        return getattr(self, stage)(user)

    def screen(self, user):
        return ScreenOut(scores=[Score(ref=r, score=3) for r in re.findall(r"^\[(A\d+)\]", user, re.M)])

    def find(self, user):
        pairs = [(m.group(1), m.group(2).strip()) for m in re.finditer(r"^\[(A\d+)\].*\n(.+)$", user, re.M)]
        waller = [r for r, t in pairs if t.startswith("Fed's Waller")]
        acme_talks = next(r for r, t in pairs if t.startswith("Acme is in talks"))
        acme_q3 = next(r for r, t in pairs if t.startswith("Acme to report"))
        pboc = next(r for r, t in pairs if t.startswith("China's central bank"))
        return FindOut(stories=[
            FoundStory(title="Waller backs more cuts", continues=None, category="central_banks_rates", region="us",
                       audiences=["trading", "wealth"], materiality=5, why_it_matters="Rates path.",
                       claims=[FoundClaim(text="Fed's Waller says further rate cuts are likely this year", refs=waller,
                                          kind="event", event_date=None)]),
            FoundStory(title="Acme deal talks", continues=None, category="deals_capital_markets", region="us",
                       audiences=["banking"], materiality=4, why_it_matters="M&A.",
                       claims=[FoundClaim(text="Acme is in talks to buy Widget, people familiar with the matter say",
                                          refs=[acme_talks], kind="report", event_date=None),
                               FoundClaim(text="Acme will report third-quarter results on October 6, 2026",
                                          refs=[acme_q3], kind="scheduled", event_date="2026-10-06"),
                               FoundClaim(text="Acme has agreed to pay $4 billion", refs=[acme_talks], kind="event",
                                          event_date=None)]),
            FoundStory(title="PBOC weighs RRR cut", continues=None, category="central_banks_rates", region="asia",
                       audiences=["trading"], materiality=3, why_it_matters="China easing.",
                       claims=[FoundClaim(text="China's central bank is said to weigh a cut to reserve requirements",
                                          refs=[pboc, "A99"], kind="report", event_date=None)]),
        ])

    def check(self, user):
        docs = dict(re.findall(r'<document id="(E\d+)"[^>]*>\n(.*?)\n</document>', user, re.S))
        verdicts = []
        for ref, text in re.findall(r"^\[(C\d+)\] (.+?) \(cites", user, re.M):
            if "$4 billion" in text:
                verdicts.append(Verdict(claim_id=ref, verdict="unsupported", revised=None, quotes=[], basis="reported",
                                        full_support=[], event_date=None, note="No price in the documents."))
                continue
            doc_id, doc_text = next(iter(docs.items()))
            first_line = doc_text.split("\n")[0]
            if "third-quarter" in text:
                doc_id, first_line = next((d, t.split("\n")[0]) for d, t in docs.items() if "third-quarter" in t)
            basis = "attributed" if ("familiar" in text or "said to" in text) else ("primary" if "report third" in text else "reported")
            # Like the real model on its first live run: some verdicts are labelled with the claim's text, not its id.
            label = text if "Waller" in text else f"[{ref}]"
            quotes = ([Quote(doc=d, text=t.split("\n")[0]) for d, t in docs.items()] if basis == "reported"
                      else [Quote(doc=doc_id, text=first_line)])
            verdicts.append(Verdict(claim_id=label, verdict="supported", revised=None, quotes=quotes, basis=basis,
                                    full_support=[q.doc for q in quotes],
                                    event_date="2026-10-06" if "October 6" in text else None, note="ok"))
        return CheckOut(verdicts=verdicts)

    def write(self, user):
        by_story, current, titles = {}, None, {}
        for line in user.splitlines():
            m = re.match(r"^\[(T\d+)\] (.+?) —", line)
            if m:
                current = m.group(1)
                titles[current] = m.group(2)
            m = re.match(r"^  \[(V\d+)\]", line)
            if m and current:
                by_story.setdefault(current, []).append(m.group(1))
        items = [Item(story=key, headline=title, headline_claims=by_story[key][:1],
                      what_changed=[Sentence(text=f"{title}.", claims=by_story[key])],
                      why_it_matters="A 7% move is possible." if key == "T1" else "Worth watching.",
                      audiences=["trading"]) for key, title in titles.items()]
        return WriteOut(summary="Waller backs more cuts.", summary_claims=["V1"], top=items, second=[], developing=[],
                        session=[], calendar=re.findall(r"^\[(K\d+)\]", user, re.M))

    def audit(self, user):
        return AuditOut(lines=[
            LineCheck(line="B1.h", verdict="fix", fixed="Waller says 9 more cuts are coming", reason="overstated"),
            LineCheck(line="[B2.w]", verdict="fix", fixed="Deal talks matter for bankers.", reason="tightened"),
        ])


def fake_gather(items, settings, fetcher, queries):
    return {i["id"]: Evidence(i["id"], i["publisher"], i["section"], i["tier"], i["owner"], i["kind"], i["url"],
                              i["published_utc"], i["title"], i["title"] + ("\n" + i["summary"] if i["summary"] else ""),
                              "test copy", True) for i in items}


class PipelineTest(unittest.TestCase):
    def test_full_run_with_guards(self):
        settings = load_settings()
        settings.raw["brief"]["analysis"] = "labelled"  # exercise the why-it-matters audit and its rendering
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "workbench").mkdir()
            settings.raw["brief"]["workbench"] = str(tmp / "workbench")
            settings.raw["brief"]["owner"] = "Pat Example"
            store = Store(tmp / "t.db")
            seed(store, settings)
            with mock.patch.object(pipeline, "LLM", FakeLLM), \
                 mock.patch.object(pipeline, "utcnow", lambda: NOW), \
                 mock.patch.object(pipeline, "DATA_DIR", tmp / "data"), \
                 mock.patch.object(pipeline, "BRIEFS_DIR", tmp / "briefs"), \
                 mock.patch("reader.stages.check.gather", fake_gather):
                code = pipeline.run_brief(settings, store, collect_first=False)
            self.assertEqual(code, 0)
            brief = next((tmp / "briefs").glob("*.md")).read_text()
            report = next((tmp / "data" / "runs").glob("*/report.md")).read_text()
            if os.environ.get("READER_SHOW_BRIEF"):
                print(brief, "\n=====\n", report)

            self.assertIn("Tue, Sep 29, 6.30 AM", next((tmp / "briefs").glob("*.md")).name)
            self.assertIn("## Top stories", brief)
            # corroborated by two independent outlets: both links present
            self.assertIn("https://wsj.example/waller", brief)
            self.assertIn("https://cnbc.example/waller", brief)
            # a sentence resting on an unconfirmed tier-1 report names the outlet; this one also cites Acme's own
            # release, so the outlet's name goes on Bloomberg's claim alone, never over the whole sentence
            self.assertIn("Bloomberg reports: Acme is in talks to buy Widget, people familiar with the matter say. "
                          "Acme will report third-quarter results on October 6, 2026.", brief)
            self.assertNotIn("Bloomberg reports: Acme deal talks.", brief)
            # an item resting only on unconfirmed reports carries the caveat
            self.assertIn("Based on unconfirmed reports (SCMP)", brief)
            # a tier-2 unconfirmed report is moved to Developing
            self.assertIn("## Developing", brief)
            # the editor's headline used a name ("PBOC") that its claim does not; the headline fell back to the claim
            self.assertNotIn("PBOC weighs RRR cut", brief)
            self.assertLess(brief.index("## Developing"), brief.index("China's central bank is said to weigh"))
            self.assertIn("names ['PBOC', 'RRR'] are not in its claims", report)
            # the checker's rejection and the analyst's bad citation are both recorded, and never published
            self.assertNotIn("$4 billion", brief)
            self.assertIn("DROP Acme has agreed to pay $4 billion", report)
            self.assertIn("unknown items ['A99']", report)
            # the invented figure in why-it-matters was removed mechanically; the audit's fix was applied
            self.assertNotIn("7%", brief)
            self.assertIn("*Why it matters: Deal talks matter for bankers.*", brief)
            # a sentence that dropped its claim's hedge ("likely") falls back to the claim's wording
            self.assertNotIn("Waller backs more cuts.  ", brief)
            # no item here rests on a single outlet without a caveat, so no "single source" tag appears in item metadata
            self.assertNotIn("single source* —", brief)
            # the hand-entered calendar supplied the jobs report for the coming week
            self.assertIn("Employment Situation", brief)
            self.assertIn("narrowed to what the source says", brief)
            # an audit "fix" that invents a figure is refused; the headline falls back to the claim's wording
            self.assertNotIn("9 more cuts", brief)
            self.assertIn("**1. Fed's Waller says further rate cuts are likely this year**", brief)
            # the scheduled event made it to the calendar with its source
            self.assertIn("Tue, Oct 6", brief)
            self.assertIn("https://prn.example/acme-q3", brief)
            # memory: stories recorded for tomorrow's run
            self.assertEqual(len(store.open_stories(NOW.replace(year=2025))), 3)
            # a rerun the same morning replaces that memory rather than adding a second copy
            with mock.patch.object(pipeline, "LLM", FakeLLM), \
                 mock.patch.object(pipeline, "utcnow", lambda: NOW.replace(minute=45)), \
                 mock.patch("reader.store.utcnow", lambda: NOW.replace(minute=45)), \
                 mock.patch.object(pipeline, "DATA_DIR", tmp / "data"), \
                 mock.patch.object(pipeline, "BRIEFS_DIR", tmp / "briefs"), \
                 mock.patch("reader.stages.check.gather", fake_gather):
                self.assertEqual(pipeline.run_brief(settings, store, collect_first=False), 0)
            self.assertEqual(len(store.open_stories(NOW.replace(year=2025))), 3)
            # the workbench got a copy of each brief, flat, dated, never overwritten, with the provenance block
            copies = sorted(p.name for p in (tmp / "workbench").glob("*.md"))
            self.assertEqual(copies, ["2026-09-29-reader-overnight-markets-brief-v2.md",
                                      "2026-09-29-reader-overnight-markets-brief.md"])
            first = (tmp / "workbench" / copies[1]).read_text()
            # the provenance block names Reader and no person, whatever the settings hold
            self.assertTrue(first.startswith("**Produced by:** Reader\n**Date:** 2026-09-29\n"))
            self.assertNotIn("Pat Example", first)
            self.assertNotIn("**For:**", first)
            self.assertNotIn("Commissioned", first)
            self.assertIn("**Version:** v1\n", first)
            self.assertIn("Committed copy: `Reader/briefs/Tue, Sep 29, 6.30 AM.md`", first)
            self.assertIn("## Top stories", first)
            self.assertIn("**Version:** v2 — a later run the same morning; supersedes v1", (tmp / "workbench" / copies[0]).read_text())


class MorningPackageTest(unittest.TestCase):
    """A morning nobody ran: the package freezes it at 6:30, and the brief can be written from it a day later."""

    def test_package_then_late_brief(self):
        from datetime import date, timedelta
        from reader.package import load_package, make_package

        settings = load_settings()
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            settings.raw["brief"]["workbench"] = ""
            store = Store(tmp / "t.db")
            seed(store, settings)
            packages = tmp / "data" / "packages"
            day = NOW.date()
            with mock.patch("reader.store.utcnow", lambda: NOW - timedelta(hours=2)):
                store.log_fetch("bloomberg_markets", "ok", 20, 20, 20, gap=True)
            with self.assertRaises(ValueError):  # not 6:30 yet
                make_package(settings, store, day, NOW - timedelta(minutes=5), root=packages)
            folder, made = make_package(settings, store, day, NOW + timedelta(hours=3), root=packages)
            self.assertTrue(made)
            headlines = (folder / "headlines.md").read_text()
            self.assertIn("# Overnight news, Tue, Sep 29", headlines)
            self.assertIn("[Acme is in talks to buy Widget, people familiar with the matter say](https://bbg.example/acme)", headlines)
            self.assertIn("No model has read or written any of this list", headlines)
            self.assertIn("- Bloomberg · Markets, check at ", headlines)
            pkg = load_package(day, root=packages)
            self.assertEqual(len(pkg["items"]), len(ITEMS))
            self.assertEqual(pkg["window_end"], NOW)

            # Later collection neither changes the package nor gets into it
            store.upsert_item({"id": "ilater", "source_id": "wsj_markets", "publisher": "The Wall Street Journal",
                               "section": "Markets", "kind": "news", "tier": 1, "owner": "News Corp",
                               "title": "Stocks open higher Tuesday", "summary": "", "url": "https://wsj.example/open",
                               "published_utc": iso(NOW + timedelta(hours=3))})
            self.assertFalse(make_package(settings, store, day, NOW + timedelta(days=1), root=packages)[1])
            self.assertEqual(len(load_package(day, root=packages)["items"]), len(ITEMS))

            later = NOW + timedelta(days=1, hours=3, minutes=30)  # Wednesday 10:00 AM
            with mock.patch.object(pipeline, "LLM", FakeLLM), \
                 mock.patch.object(pipeline, "utcnow", lambda: later), \
                 mock.patch.object(pipeline, "DATA_DIR", tmp / "data"), \
                 mock.patch.object(pipeline, "BRIEFS_DIR", tmp / "briefs"), \
                 mock.patch("reader.stages.check.gather", fake_gather):
                code = pipeline.run_brief(settings, store, collect_first=False, package_day=day)
            self.assertEqual(code, 0)
            path = tmp / "briefs" / "Tue, Sep 29, 6.30 AM (late).md"
            brief = path.read_text()
            self.assertIn("**Tuesday, September 29, 2026 · 6:30 AM New York**", brief)
            self.assertIn("_Written late, Wed, Sep 30 at 10:00 AM, from the 6:30 AM morning package. "
                          "Sources were re-checked when it was written._", brief)
            self.assertNotIn("Stocks open higher", brief)
            run_dir = next((tmp / "data" / "runs").glob("*-for-20260929"))
            self.assertIn("story memory left as it was", (run_dir / "report.md").read_text())
            self.assertEqual(store.open_stories(NOW.replace(year=2025)), [])
            # a late brief makes no package of its own morning
            self.assertFalse((packages / "2026-09-30").exists())

    def test_footer_counts_only_sources_checked_that_morning(self):
        # Tue Oct 6: three sources switched off weeks earlier printed as "not reachable this morning"
        from reader.package import unavailable
        data = {"window_start": "2026-10-05T20:00:00+00:00", "sources": [
            {"publisher": "GlobeNewswire", "kind": "wire", "status": "robots.txt disallows or is unreachable",
             "fetched_utc": "2026-09-26T14:02:04+00:00"},
            {"publisher": "Bloomberg", "kind": "news", "status": "ok", "fetched_utc": "2026-10-06T10:22:00+00:00"},
            {"publisher": "The White House", "kind": "official", "status": "HTTP 403", "fetched_utc": "2026-10-06T10:22:00+00:00"},
            {"publisher": "TreasuryDirect", "kind": "calendar", "status": "HTTP 403", "fetched_utc": "2026-10-06T10:22:00+00:00"},
        ]}
        self.assertEqual(unavailable(data), ["The White House"])


if __name__ == "__main__":
    unittest.main()


class ResumeLoaderTest(unittest.TestCase):
    def test_checked_stories_round_trip_through_json(self):
        import json
        from dataclasses import asdict
        from reader.evidence import Evidence
        from reader.sinceopen import load_dataclass
        from reader.stages.check import CheckedStory, VerifiedClaim
        from reader.stages.find import Claim, Story
        story = Story(key="T1", title="Jobs miss", continues=None, category="economic_data", region="us", audiences=["trading"],
                      materiality=5, why_it_matters="Rates.", claims=[Claim(text="29,000 jobs", item_ids=["i1"], kind="event", event_date=None)])
        ev = Evidence(item_id="i1", publisher="CNBC", section="Economy", tier=2, owner="Versant", kind="news", url="https://c/1",
                      published_utc="2026-10-02T12:30:00+00:00", title="t", text="x", note="", reconfirmed=True, day_only=True)
        cs = CheckedStory(story=story, verified=[VerifiedClaim(id="V1", story_key="T1", text="29,000 jobs", kind="event", status="confirmed",
                                                                basis="reported", evidence=[ev], quotes=["29,000"], event_date=None, original="29,000 jobs")],
                          rejected=[{"text": "dropped", "reason": "name"}])
        back = load_dataclass(CheckedStory, json.loads(json.dumps(asdict(cs))))
        self.assertEqual(back, cs)
        self.assertIsInstance(back.verified[0].evidence[0], Evidence)
