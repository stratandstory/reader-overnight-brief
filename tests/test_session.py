"""The previous trading day's highlights: what no overnight window covers, through every stage, in its own section."""

import json
import re
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from reader import pipeline, session
from reader.config import load_settings
from reader.render import session_heading
from reader.stages.common import Session, Window
from reader.stages.find import FoundClaim, FoundStory
from reader.store import Store, iso
from tests.test_pipeline import ITEMS, NOW, FakeLLM, fake_gather, seed

NY = ZoneInfo("America/New_York")
MONDAY = datetime(2026, 9, 28, tzinfo=NY)

# (source, url, title, summary, Monday hour, minute)
SESSION_ITEMS = [
    ("bbc_business", "https://bbc.example/pentagon", "Pentagon stops using Anthropic AI tools after blacklisting company",
     "It labelled Anthropic a supply chain risk in February.", 12, 13),
    ("the_information", "https://theinformation.example/claude", "Microsoft Slashes Internal Claude Spending by a Third",
     "Meta Platforms and Microsoft are working to cut their employees' use of Claude.", 14, 14),
    ("bbc_business", "https://bbc.example/supermarket", "Community supermarket opens in shopping centre", "", 13, 0),
    ("wsj_markets", "https://wsj.example/waller-evening", "Fed's Waller to speak in New York on Monday evening", "", 11, 0),
    ("cnbc_top", "https://cnbc.example/early", "Stocks set for a quiet open as traders await data", "", 8, 0),  # before Monday's brief
]


def seed_session(store: Store, settings, brief_end: datetime | None = datetime(2026, 9, 28, 9, 39, tzinfo=NY)) -> None:
    for source_id, url, title, summary, hour, minute in SESSION_ITEMS:
        src = settings.source(source_id)
        store.upsert_item({"id": "s" + str(abs(hash(url)))[:10], "source_id": src.id, "publisher": src.publisher,
                           "section": src.section, "kind": src.kind, "tier": src.tier, "owner": src.owner, "title": title,
                           "summary": summary, "url": url, "published_utc": iso(MONDAY.replace(hour=hour, minute=minute)),
                           "model_ok": True, "extra": {}})
    if brief_end:  # Monday's brief, written at 9:39 AM
        store.start_run("20260928-093900", MONDAY.replace(hour=16) - timedelta(days=3), brief_end)
        store.finish_run("20260928-093900", "ok", 2.0, "briefs/x.md", "summary", {})


class SessionLLM(FakeLLM):
    """The analyst adds the session's stories and joins one session item to an overnight story; the editor files
    one session story under top, one under session, and an overnight story under session."""

    def find(self, user):
        self.find_user = user
        out = super().find(user)
        pairs = {m.group(2).strip(): m.group(1) for m in re.finditer(r"^\[(A\d+)\].*\n(.+)$", user, re.M)}
        ref = lambda start: next(r for t, r in pairs.items() if t.startswith(start))
        out.stories[0].claims[0].refs.append(ref("Fed's Waller to speak"))
        claim = lambda text, start: [FoundClaim(text=text, refs=[ref(start)], kind="event", event_date=None)]
        out.stories += [
            FoundStory(title="Pentagon drops Anthropic", continues=None, category="corporate", region="us",
                       audiences=["banking"], materiality=4, why_it_matters="IPO.",
                       claims=claim("Pentagon stops using Anthropic AI tools after blacklisting company", "Pentagon stops")),
            FoundStory(title="Microsoft trims Claude", continues=None, category="corporate", region="us",
                       audiences=["banking"], materiality=3, why_it_matters="Revenue.",
                       claims=claim("Microsoft Slashes Internal Claude Spending by a Third", "Microsoft Slashes")),
            FoundStory(title="Supermarket opens", continues=None, category="other", region="europe_uk",
                       audiences=["wealth"], materiality=1, why_it_matters="None.",
                       claims=claim("Community supermarket opens in shopping centre", "Community supermarket")),
        ]
        return out

    def write(self, user):
        self.write_user = user
        out = super().write(user)
        marked = {m.group(1) for m in re.finditer(r"^\[(T\d+)\] .*previous session$", user, re.M)}
        microsoft = next(i for i in out.top if i.headline == "Microsoft trims Claude")
        pboc = next(i for i in out.top if i.headline == "PBOC weighs RRR cut")
        out.top = [i for i in out.top if i not in (microsoft, pboc)]  # Pentagon stays filed under top
        out.session = [microsoft, pboc]
        self.marked = marked
        return out


def run(settings, store, tmp, llm_cls=SessionLLM):
    made = []

    def make(*a, **kw):
        made.append(llm_cls(*a, **kw))
        return made[-1]
    with mock.patch.object(pipeline, "LLM", make), \
         mock.patch.object(pipeline, "utcnow", lambda: NOW), \
         mock.patch.object(pipeline, "DATA_DIR", tmp / "data"), \
         mock.patch.object(pipeline, "BRIEFS_DIR", tmp / "briefs"), \
         mock.patch("reader.stages.check.gather", fake_gather):
        code = pipeline.run_brief(settings, store, collect_first=False)
    return code, made[0]


def section(brief: str, heading: str) -> str:
    start = brief.index(heading)
    end = brief.find("\n## ", start + 1)
    return brief[start:end if end > 0 else None]


class SessionBriefTest(unittest.TestCase):
    def test_session_section_end_to_end(self):
        settings = load_settings()
        settings.raw["brief"]["workbench"] = ""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            store = Store(tmp / "t.db")
            seed(store, settings)
            seed_session(store, settings)
            code, llm = run(settings, store, tmp)
            self.assertEqual(code, 0)
            brief = next((tmp / "briefs").glob("*.md")).read_text()
            report = next((tmp / "data" / "runs").glob("*/report.md")).read_text()

            # the analyst saw the session's items in their own block, and not the item Monday's brief already had
            self.assertIn("Previous session: the items below were published Monday, September 28, from 9:39 AM to "
                          "the 4:00 PM close", llm.find_user)
            self.assertLess(llm.find_user.index("Previous session:"), llm.find_user.index("Pentagon stops using"))
            self.assertNotIn("Stocks set for a quiet open", llm.find_user)
            # the editor was told which stories are the session's own: the two all-session stories that were checked
            self.assertEqual(len(llm.marked), 2)
            self.assertIn("were reported Monday, September 28, from 9:39 AM to the 4:00 PM close", llm.write_user)

            self.assertIn("· news since Mon 4:00 PM, plus highlights from Monday 9:39 AM to 4:00 PM", brief)
            self.assertIn("## Highlights from Monday's trading day", brief)
            self.assertIn("_Reported Monday after Monday's brief (9:39 AM) and before the 4:00 PM close, so no brief has "
                          "carried them. The few that matter most for today; everything else in this brief is overnight "
                          "news._", brief)
            # after Top stories, before the rest
            self.assertLess(brief.index("## Top stories"), brief.index("## Highlights from Monday"))
            self.assertLess(brief.index("## Highlights from Monday"), brief.index("## Developing"))
            highlights = section(brief, "## Highlights from Monday")
            # filed under top by the editor, moved here by code; filed here by the editor and kept
            self.assertIn("Pentagon drops Anthropic", highlights)
            self.assertIn("[BBC, Mon 12:13 PM](https://bbc.example/pentagon)", highlights)
            self.assertIn("Microsoft trims Claude", highlights)
            self.assertIn("Moved 'Pentagon drops Anthropic' to the previous session's highlights", report)
            # an overnight story the editor filed here goes back to the overnight sections
            self.assertNotIn("China's central bank", highlights)
            self.assertIn("Moved 'PBOC weighs RRR cut' out of the previous session's highlights", report)
            # a story with any overnight source is overnight news, its session source shown with its time
            top = section(brief, "## Top stories")
            self.assertIn("Fed's Waller says further rate cuts", top)
            self.assertIn("[WSJ, Mon 11:00 AM](https://wsj.example/waller-evening)", top)
            # below the bar: never checked, never printed, and the report says so
            self.assertNotIn("supermarket", brief.lower())
            self.assertIn("Previous-session story not checked, below its bar of 3: Supermarket opens (materiality 1)", report)

            self.assertIn(f"_How this brief was checked: {len(ITEMS)} overnight items and 4 from Monday's session, "
                          f"from ", brief)
            self.assertIn("Previous session: Mon 9:39 AM to Mon 4:00 PM (from that day's brief to the close)", report)
            self.assertIn("| Previous session: items | 4 |", report)
            self.assertIn("| Previous session: items published | 2 |", report)
            self.assertIn("(materiality 4, previous session)", report)
            screened = json.loads(next((tmp / "data" / "runs").glob("*/1-screen.json")).read_text())
            self.assertEqual(sum(1 for r in screened if r.get("session")), 4)
            # remembered like any other story, so tomorrow's analyst knows it was reported
            titles = {r["title"] for r in store.open_stories(NOW.replace(year=2025))}
            self.assertIn("Pentagon drops Anthropic", titles)

    def test_switched_off_brief_is_unchanged(self):
        settings = load_settings()
        settings.raw["brief"]["workbench"] = ""
        settings.raw["session"]["enabled"] = False
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            store = Store(tmp / "t.db")
            seed(store, settings)
            seed_session(store, settings)
            code, llm = run(settings, store, tmp, FakeLLM)
            self.assertEqual(code, 0)
            brief = next((tmp / "briefs").glob("*.md")).read_text()
            self.assertNotIn("Highlights from", brief)
            self.assertNotIn("Pentagon", brief)
            self.assertIn("· news since Mon 4:00 PM\n", brief)


class SessionRenderTest(unittest.TestCase):
    def test_footer_counts_screened_session_items_even_when_none_is_printed(self):
        from reader.render import render_brief
        from reader.stages.write import Brief, Line
        s = Session(MONDAY.replace(hour=9, minute=39), MONDAY.replace(hour=16), "America/New_York", True)
        empty = Brief(summary=Line("Quiet night.", []), top=[], second=[], developing=[], calendar=[])
        text = render_brief(empty, now=NOW, window_start=MONDAY.replace(hour=16), tz="America/New_York", tracked={},
                            institutional=[], stats={"items_in_window": 400, "items_in_session": 200, "sources_ok": 60},
                            unavailable=[], run_id="r", session=s)
        self.assertNotIn("Highlights from", text)
        self.assertIn("· news since Mon 4:00 PM\n", text)
        self.assertIn("400 overnight items and 200 from Monday's session, from 60 sources, were screened", text)


class SessionBoundsTest(unittest.TestCase):
    def setUp(self):
        self.settings = load_settings()
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "t.db")

    def tearDown(self):
        self.tmp.cleanup()

    def window(self, end: datetime) -> Window:
        from reader.timewindow import overnight_window
        start, stop = overnight_window(end, "America/New_York", 16, 100)
        return Window(start, stop, "America/New_York")

    def test_from_the_package_time_when_no_brief_ran(self):
        s = session.bounds(self.settings, self.store, self.window(NOW))
        self.assertEqual((s.start, s.end, s.after_brief), (MONDAY.replace(hour=6, minute=30), MONDAY.replace(hour=16), False))
        self.assertEqual(session_heading(s)[1].split(". ")[0],
                         "_Reported Monday between 6:30 AM and the 4:00 PM close, so no brief has carried them")

    def test_from_that_days_brief(self):
        seed_session(self.store, self.settings)
        s = session.bounds(self.settings, self.store, self.window(NOW))
        self.assertEqual((s.start, s.after_brief), (MONDAY.replace(hour=9, minute=39), True))
        # both ends open: the brief had what came before, the overnight window has the close
        titles = {i["title"] for i in session.items(self.store, s)}
        self.assertEqual(len(titles), 4)
        self.assertNotIn("Stocks set for a quiet open as traders await data", titles)

    def test_a_monday_brief_gets_fridays_session(self):
        monday_morning = MONDAY.replace(hour=6, minute=30)
        s = session.bounds(self.settings, self.store, self.window(monday_morning))
        self.assertEqual(s.day(), "Friday")
        self.assertEqual(s.end, MONDAY.replace(hour=16) - timedelta(days=3))
        self.assertEqual(session_heading(s)[0], "## Highlights from Friday's trading day")

    def test_none_when_off_or_after_a_long_closure(self):
        self.settings.raw["session"]["enabled"] = False
        self.assertIsNone(session.bounds(self.settings, self.store, self.window(NOW)))
        self.settings.raw["session"]["enabled"] = True
        # a window the lookback cap shortened: the trading day before it is too far back
        capped = Window(NOW - timedelta(hours=10), NOW, "America/New_York")
        self.assertIsNone(session.bounds(self.settings, self.store, capped))


class SessionRoutingTest(unittest.TestCase):
    def test_select_and_route(self):
        from reader.evidence import Evidence
        from reader.stages.check import CheckedStory, VerifiedClaim
        from reader.stages.find import Claim, Story
        settings = load_settings()

        def story(key, materiality, is_session):
            return Story(key=key, title=key, continues=None, category="corporate", region="us", audiences=["banking"],
                         materiality=materiality, why_it_matters="", claims=[Claim("x", ["i"], "event", None)],
                         session=is_session)
        stories = [story("T1", 5, False), story("T2", 5, True), story("T3", 4, True), story("T4", 4, True),
                   story("T5", 3, True), story("T6", 2, True), story("T7", 3, False)]
        chosen, notes = session.select(stories, settings, check_limit=1)
        self.assertEqual([s.key for s in chosen], ["T1", "T2", "T3", "T4"])
        self.assertIn("1 lower-materiality stories not checked (limit 1)", notes)
        self.assertIn("Previous-session story not checked, past its ceiling of 3: T5 (materiality 3)", notes)
        self.assertIn("Previous-session story not checked, below its bar of 3: T6 (materiality 2)", notes)

        def checked(key, materiality, item_ids):
            evs = [Evidence(i, "BBC News", "Business", 2, "BBC", "news", f"https://x/{i}", "2026-09-28T16:00:00+00:00",
                            "t", "t", "", True) for i in item_ids]
            return CheckedStory(story=story(key, materiality, False), verified=[
                VerifiedClaim(id="V1", story_key=key, text="x", kind="event", status="reported", basis="reported",
                              evidence=evs, quotes=[], event_date=None, original="x")])
        night = checked("T1", 5, ["n1", "s1"])       # any overnight source: overnight
        own = checked("T2", 4, ["s1", "s2"])         # every source from the session
        stray = checked("T3", 2, ["s2"])             # built as overnight, only its session claim passed, below the bar
        keys, kept, notes = session.route([night, own, stray], {"s1", "s2"}, settings)
        self.assertEqual(keys, {"T2"})
        self.assertEqual([cs.story.key for cs in kept], ["T1", "T2"])
        self.assertIn("below its bar of 3: T3 (materiality 2)", notes[0])


class SessionPackageTest(unittest.TestCase):
    def test_package_freezes_the_session(self):
        from reader.package import load_package, make_package
        settings = load_settings()
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            store = Store(tmp / "t.db")
            seed(store, settings)
            seed_session(store, settings, brief_end=None)
            folder, made = make_package(settings, store, NOW.date(), NOW + timedelta(hours=1), root=tmp / "packages")
            self.assertTrue(made)
            pkg = load_package(NOW.date(), root=tmp / "packages")
            self.assertEqual(pkg["session"]["start"], iso(MONDAY.replace(hour=6, minute=30)))
            self.assertFalse(pkg["session"]["after_brief"])
            self.assertEqual(len(pkg["session_items"]), 5)  # no brief Monday: from 6:30 AM, the 8:00 AM item included
            self.assertIn("Also frozen for the brief's section on the previous trading day: 5 items published from "
                          "Mon 6:30 AM to the 4:00 PM close", (folder / "headlines.md").read_text())


if __name__ == "__main__":
    unittest.main()
