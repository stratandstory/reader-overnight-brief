import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

from reader.guards import excerpt, quote_in, unsupported_numbers
from reader.stages.check import status_for
from reader.evidence import Evidence
from reader.timewindow import NYSE_HOLIDAYS, next_trading_days, overnight_window

NY = ZoneInfo("America/New_York")


def ev(tier: int, owner: str) -> Evidence:
    return Evidence("i1", owner, "s", tier, owner, "news", "https://x", "2026-09-26T00:00:00+00:00", "t", "t", "", True)


class QuoteTests(unittest.TestCase):
    def test_verbatim_quote_passes_despite_typography(self):
        doc = "The Fed’s board approved the application — effective immediately."
        self.assertTrue(quote_in("The Fed's board approved the application - effective immediately", doc))

    def test_paraphrase_fails(self):
        self.assertFalse(quote_in("The board said yes to the application", "The Fed's board approved the application."))

    def test_short_fragment_fails(self):
        self.assertFalse(quote_in("approved", "The Fed's board approved the application."))


class NumberGuardTests(unittest.TestCase):
    def test_numbers_must_come_from_claims(self):
        support = ["Oil fell 2.5% to $81.20 a barrel on Friday."]
        self.assertEqual(unsupported_numbers("Oil fell 2.5% to $81.20.", support), set())
        self.assertEqual(unsupported_numbers("Oil fell 3% after the report.", support), {"3"})

    def test_thousands_separators(self):
        self.assertEqual(unsupported_numbers("A $1,200 fine", ["a fine of $1200"]), set())


class ExcerptTests(unittest.TestCase):
    def test_keeps_opening_and_relevant_paragraphs(self):
        paras = ["Opening paragraph about the announcement today." * 2,
                 "Second paragraph with context and more detail here." * 2]
        paras += [f"Filler paragraph number {i} about unrelated administrative matters." * 3 for i in range(60)]
        paras.append("The committee voted to lower the target range for the federal funds rate.")
        text = "\n".join(paras)
        out = excerpt(text, ["Committee lowers target range for federal funds rate"], max_chars=1200)
        self.assertIn("Opening paragraph", out)
        self.assertIn("lower the target range", out)
        self.assertLessEqual(len(out), 1400)


class StatusTests(unittest.TestCase):
    def test_primary_source_confirms(self):
        self.assertEqual(status_for("primary", [ev(0, "Federal Reserve")]), "confirmed")

    def test_two_independent_outlets_confirm(self):
        self.assertEqual(status_for("reported", [ev(1, "Bloomberg"), ev(2, "NBCUniversal")]), "confirmed")

    def test_same_owner_is_not_independent(self):
        self.assertEqual(status_for("reported", [ev(1, "Dow Jones"), ev(2, "Dow Jones")]), "reported")

    def test_unconfirmed_report_placement_follows_tier(self):
        self.assertEqual(status_for("attributed", [ev(1, "Bloomberg")]), "attributed")
        self.assertEqual(status_for("attributed", [ev(2, "NBCUniversal")]), "developing")

    def test_outlets_supporting_different_parts_do_not_corroborate(self):
        bbg, cnbc = ev(1, "Bloomberg"), ev(2, "NBCUniversal")
        self.assertEqual(status_for("reported", [bbg, cnbc], whole=[bbg]), "reported")
        self.assertEqual(status_for("reported", [bbg, cnbc], whole=[bbg, cnbc]), "confirmed")

    def test_primary_basis_without_primary_document_is_downgraded(self):
        self.assertEqual(status_for("primary", [ev(1, "Bloomberg")]), "reported")


class WindowTests(unittest.TestCase):
    def test_holidays_are_weekdays(self):
        for d in NYSE_HOLIDAYS:
            self.assertLess(d.weekday(), 5, d)

    def test_monday_morning_reaches_back_to_friday_close(self):
        monday = datetime(2026, 9, 28, 6, 30, tzinfo=NY)
        start, _ = overnight_window(monday, "America/New_York", 16, 100)
        self.assertEqual(start.astimezone(NY), datetime(2026, 9, 25, 16, 0, tzinfo=NY))

    def test_after_close_uses_same_day_close(self):
        evening = datetime(2026, 9, 29, 21, 0, tzinfo=NY)
        start, _ = overnight_window(evening, "America/New_York", 16, 100)
        self.assertEqual(start.astimezone(NY), datetime(2026, 9, 29, 16, 0, tzinfo=NY))

    def test_holiday_is_skipped(self):
        tuesday_after_labor_day = datetime(2026, 9, 8, 6, 30, tzinfo=NY)
        start, _ = overnight_window(tuesday_after_labor_day, "America/New_York", 16, 100)
        self.assertEqual(start.astimezone(NY).date(), date(2026, 9, 4))

    def test_next_trading_days_skip_weekends_and_holidays(self):
        self.assertEqual(next_trading_days(date(2026, 9, 3), 3), [date(2026, 9, 4), date(2026, 9, 8), date(2026, 9, 9)])


if __name__ == "__main__":
    unittest.main()


class VerdictMatchingTests(unittest.TestCase):
    def test_ids_text_and_rewording_match_but_nothing_is_guessed(self):
        from reader.stages.check import Verdict, match_verdicts
        from reader.stages.find import Claim

        claims = [Claim("Stocks rose on Friday.", ["i1"], "market_move", None),
                  Claim("The Fed approved the Peoples Bancorp merger.", ["i2"], "event", None),
                  Claim("Oil futures ended a volatile week with mixed results.", ["i3"], "market_move", None),
                  Claim("Nike will report results on September 30.", ["i4"], "scheduled", None)]

        def v(label):
            return Verdict(claim_id=label, verdict="supported", revised=None, quotes=[], basis="reported",
                           full_support=[], event_date=None, note="")

        got = match_verdicts([v("[C1]"), v("The Fed approved the Peoples Bancorp merger."),
                              v("Oil futures ended a volatile week, with mixed results"), v("something else entirely")],
                             claims)
        self.assertEqual(sorted(got), [1, 2, 3])  # the fourth verdict is not assigned to anything


class StoryMemoryTests(unittest.TestCase):
    def test_same_day_rerun_replaces_earlier_run_but_keeps_prior_days(self):
        import tempfile
        from datetime import timedelta
        from pathlib import Path
        from unittest import mock
        from reader import store as store_mod
        from reader.store import Store

        with tempfile.TemporaryDirectory() as tmp:
            st = Store(Path(tmp) / "m.db")
            friday = datetime(2026, 9, 25, 7, 0, tzinfo=NY)
            saturday_early = datetime(2026, 9, 26, 9, 0, tzinfo=NY)
            saturday_late = datetime(2026, 9, 26, 11, 0, tzinfo=NY)
            day_start = datetime(2026, 9, 26, 0, 0, tzinfo=NY)
            with mock.patch.object(store_mod, "utcnow", lambda: friday):
                st.record_story("fed", "Fed", "rates", "Friday state", "run-fri", [])
            with mock.patch.object(store_mod, "utcnow", lambda: saturday_early):
                st.forget_same_day(day_start, "run-sat1")
                st.record_story("fed", "Fed", "rates", "Saturday first draft", "run-sat1", [])
                st.record_story("oil", "Oil", "energy", "Saturday first draft", "run-sat1", [])
            # a rerun later the same day sees Friday's state as prior coverage, not the morning draft
            prior = st.tracked_before(day_start, day_start - timedelta(days=14))
            self.assertEqual([(r["id"], r["last_state"]) for r in prior], [("fed", "Friday state")])
            with mock.patch.object(store_mod, "utcnow", lambda: saturday_late):
                st.forget_same_day(day_start, "run-sat2")
                st.record_story("fed", "Fed", "rates", "Saturday final", "run-sat2", [])
            self.assertIsNone(st.story("oil"))  # the superseded draft's new story is gone
            self.assertEqual(st.story("fed")["last_state"], "Saturday final")
            self.assertEqual(st.story("fed")["times_reported"], 2)


class EntityGuardTests(unittest.TestCase):
    def test_name_the_source_does_not_use_is_caught(self):
        from reader.guards import unsupported_entities
        support = ["Saudi Arabia’s capital again came under attack from Yemen’s Houthis over the weekend",
                   "as Saudi coalition intercepts projectiles"]
        claim = "Saudi Arabia's capital came under renewed attack from Yemen's Houthis, with Saudi-backed forces intercepting projectiles"
        self.assertEqual(unsupported_entities(claim, support), {"Saudi-backed"})

    def test_abbreviations_titles_and_sentence_starts_are_not_flagged(self):
        from reader.guards import unsupported_entities
        self.assertEqual(unsupported_entities("Fed's Waller says further rate cuts are likely",
                                              ["Federal Reserve Governor Christopher Waller said further cuts are likely."]), set())
        self.assertEqual(unsupported_entities("Senator Ted Cruz said the White House gave assurances",
                                              ["Sen. Ted Cruz told refiners the White House offered assurances"]), set())
        self.assertEqual(unsupported_entities("Overseas purchases of US equities topped $940 billion",
                                              ["Foreign buying of U.S. stocks tops $940bn"]), set())
        self.assertEqual(unsupported_entities("Cattle groups and two GOP senators said ICE raids hurt operations",
                                              ["Cattle groups and two Republican senators say immigration raids hurt operations"]), set())
        # Mon Sep 28 and Tue Sep 29: rejected against sources that name the same body or country another way
        self.assertEqual(unsupported_entities("The RBA cited continued pressure on energy prices",
                                              ["The Reserve Bank of Australia voted to raise rates, citing continued pressure on energy prices"]), set())
        self.assertEqual(unsupported_entities("Crop futures fell as traders awaited signs of Chinese purchases",
                                              ["Grains Fall as Traders Seek China Buying Signs After Tariff Cuts"]), set())
        # common nouns, not names (Wed Sep 30 and Mon Oct 5: "IPO" rejected against "listings")
        self.assertEqual(unsupported_entities("IPO pipeline cools as CEOs wait", ["Several listings have been paused"]), set())

    def test_resolved_dates_are_not_names(self):
        from reader.guards import unsupported_entities
        self.assertEqual(unsupported_entities("The attack came on Saturday, Sept. 26, 2026, at 10 AM ET",
                                              ["Saudi Arabia's capital came under attack over the weekend"]), set())

    def test_publisher_attribution_counts_as_supported(self):
        from reader.evidence import Evidence
        from reader.stages.check import support_texts
        from reader.guards import unsupported_entities
        ft = Evidence("i1", "Financial Times", "Markets", 1, "Nikkei", "news", "https://x", "2026-09-25T20:24:00+00:00",
                      "t", "US bond sell-off pushes long-term yields to highest since 2004", "", True)
        self.assertEqual(unsupported_entities("Long-term yields hit their highest since 2004, the Financial Times reported (FT)",
                                              support_texts([ft])), set())

    def test_ordinary_word_starting_a_sentence_before_a_name_is_not_a_name(self):
        # Fri Oct 2: "Deteriorating" and "Major" were rejected as names the source does not use. Both are
        # words the news prints in lower case; "Chinese" is not, and stays held to the source.
        from reader import guards
        from reader.guards import unsupported_entities
        support = ["French bonds further deteriorate, hitting European bank stocks"]
        claim = "Deteriorating French bonds hit European bank stocks, MarketWatch reported."
        self.assertEqual(unsupported_entities(claim, support + ["MarketWatch"]), {"Deteriorating"})
        guards.set_ordinary_words({"deteriorating", "major"})
        try:
            self.assertEqual(unsupported_entities(claim, support + ["MarketWatch"]), set())
            # "Major" is ordinary; "U.S" is still a name the source ("Dow, S&P 500 and Nasdaq") never uses
            self.assertEqual(unsupported_entities("Major U.S. stock indexes ended higher",
                                                  ["Dow, S&P 500 and Nasdaq end higher as chip stocks rally"]), {"U.S"})
            self.assertEqual(unsupported_entities("Chinese EV makers cut prices", ["EV makers cut prices"]), {"Chinese"})
        finally:
            guards.set_ordinary_words(())

    def test_ordinary_words_are_those_the_news_prints_in_lower_case(self):
        import tempfile
        from pathlib import Path
        from reader.store import Store
        with tempfile.TemporaryDirectory() as tmp:
            st = Store(Path(tmp) / "t.db")
            for n, (title, summary) in enumerate([("Major banks rally as Chinese stocks slide", "a major move"),
                                                  ("Bond selloff is a major test", "Chinese regulators act"),
                                                  ("Yields deteriorating", "")]):
                st.upsert_item({"id": f"i{n}", "source_id": "s", "publisher": "P", "section": "", "kind": "news",
                                "tier": 1, "owner": "O", "title": title, "summary": summary, "url": f"https://x/{n}",
                                "published_utc": "2026-10-01T10:00:00+00:00"})
            words = st.ordinary_words()
        self.assertIn("major", words)
        self.assertNotIn("chinese", words)       # only ever capitalised
        self.assertNotIn("deteriorating", words)  # in one item only

    def test_hyphenated_pair_of_names_checks_each_side(self):
        from reader.guards import unsupported_entities
        self.assertEqual(unsupported_entities("The US-China summit ended", ["Trump and Xi wrap up the U.S.–China summit"]), set())
        self.assertEqual(unsupported_entities("Trump-Xi summit trims tariffs", ["Xi's state visit ends with tariff cuts"]), {"Trump"})

    def test_same_name_spelled_with_or_without_periods_and_hyphens(self):
        # Wed Sep 30 and Mon Oct 5: six claims rejected on "U.S" against "US", "C.H" against "CH Robinson",
        # "AI-focused" against "A.I.-focused" and "AI-spending" against "AI spending".
        from reader.guards import unsupported_entities
        self.assertEqual(unsupported_entities("Copper edged higher after the latest U.S. employment report",
                                              ["Copper edged higher as traders dialed back bets after the latest US employment report"]), set())
        self.assertEqual(unsupported_entities("C.H. Robinson agreed to buy RXO",
                                              ["CH Robinson Worldwide Inc. agreed to buy trucking brokerage firm RXO Inc."]), set())
        self.assertEqual(unsupported_entities("AI-focused firm Situational Awareness is in trouble",
                                              ["Meltdown at A.I.-focused investment firm Situational Awareness"]), set())
        self.assertEqual(unsupported_entities("The AI-spending boom slows", ["The AI spending boom slows"]), set())
        self.assertEqual(unsupported_entities("The G7 agreed to release 100 million barrels",
                                              ["Plus, the G-7 agreed to release 100 million barrels of diesel and crude oil"]), set())
        # the letters must still be there as a word: "CH" is not found inside "which"
        self.assertEqual(unsupported_entities("C.H. Robinson agreed to buy RXO", ["Robinson, which agreed to buy RXO"]), {"C.H"})
        # a hyphenated modifier is still held to the source as a whole: Bloomberg's "artificial intelligence is
        # causing a surge in demand" does not say "AI-driven"
        self.assertEqual(unsupported_entities("Uchida said AI-driven demand is fueling inflation",
                                              ["Artificial intelligence is causing a surge in demand that is fueling inflationary "
                                               "pressure, according to Bank of Japan Deputy Governor Shinichi Uchida."]), {"AI-driven"})


    def test_a_place_and_its_adjective_are_one_name(self):
        # Mon Oct 5, second brief: rejected "Yemeni", "Indian", "Spain's", "European", and the audit's "French"
        from reader.guards import unsupported_entities
        self.assertEqual(unsupported_entities("Saudi-backed Yemeni forces launched a campaign",
                                              ["Saudi-Backed Yemen Forces Begin Bid to Retake Houthi Areas", "Saudi-backed forces"]), set())
        self.assertEqual(unsupported_entities("Indian officials signaled an impasse", ["US, India Officials Signal Trade Deal Talks at an Impasse"]), set())
        self.assertEqual(unsupported_entities("Spain's Sánchez called a snap election", ["Spanish Prime Minister Pedro Sánchez called an early election"]), set())
        self.assertEqual(unsupported_entities("Euro hits low as French fiscal crisis weighs", ["The euro fell amid France's fiscal crisis"]), set())
        # another name for a token must appear as a whole word: "Omani" is not found through "Oman" in "woman"
        self.assertEqual(unsupported_entities("Exports of Omani crude rose", ["A woman said exports of crude rose"]), {"Omani"})
        # an adjective the source never ties to the place is still caught
        self.assertEqual(unsupported_entities("Chinese EV makers cut prices", ["EV makers cut prices"]), {"Chinese"})

    def test_market_abbreviations_the_source_spells_out(self):
        from reader.guards import unsupported_entities
        self.assertEqual(unsupported_entities("Bini Smaghi urges a QT halt",
                                              ["Lorenzo Bini Smaghi wrote that the ECB should halt quantitative tightening"]), set())
        self.assertEqual(unsupported_entities("BOJ set to declare 2% inflation as JGB yields hit high",
                                              ["The BOJ will declare underlying inflation has reached 2%", "Japan's long-term bond yields reached a fresh high"]), set())
        # Tue Oct 6: the WSJ's headline said SCOTUS, and the climate-lawsuits story was lost on "Supreme Court"
        self.assertEqual(unsupported_entities("The oil industry's bid to kill climate change lawsuits faced skepticism at the Supreme Court",
                                              ["Oil Industry’s Bid to Kill Climate Change Lawsuits Faces SCOTUS Skepticism"]), set())
        self.assertEqual(unsupported_entities("SCOTUS hears the case", ["The Supreme Court hears the case"]), set())


class HedgeGuardTests(unittest.TestCase):
    def test_line_that_states_a_hedged_claim_as_done_is_caught(self):
        from reader.guards import dropped_hedges
        claim = "A US bond sell-off pushed long-term yields to their highest since 2004, with the market heading for its worst week since 2024"
        self.assertEqual(dropped_hedges("Long-term yields hit their highest since 2004 in the worst bond week since 2024", [claim]),
                         {"heading for"})
        self.assertEqual(dropped_hedges("Long-term yields are heading for their worst week since 2024", [claim]), set())
        self.assertEqual(dropped_hedges("Trump will meet Xi in November.", ["Trump said he would meet again with Xi in November"]), {"would"})

    def test_unhedged_claims_pass(self):
        from reader.guards import dropped_hedges
        self.assertEqual(dropped_hedges("Apple plans to appeal.", ["Apple plans to appeal the verdict"]), set())
        self.assertEqual(dropped_hedges("A jury awarded Taction $5.7 billion.", ["A federal jury awarded Taction Technology more than $5.7 billion"]), set())

    def test_hedges_are_whole_words(self):
        # Mon Oct 5: "expect" matched "expectations" and the gold headline fell back to a truncated claim
        from reader.guards import dropped_hedges, hedges_in
        self.assertEqual(dropped_hedges("Gold rallies as soft U.S. data erodes Fed hike bets",
                                        ["Gold prices rose after soft U.S. economic data sharply lowered expectations of a Fed rate hike in October"]), set())
        self.assertEqual(dropped_hedges("Hon Hai beats sales estimates", ["Hon Hai reported better-than-expected quarterly revenue"]), set())
        self.assertEqual(hedges_in("The claim was verified"), set())
        self.assertEqual(hedges_in("Oil weighed on stocks"), set())
        self.assertEqual(hedges_in("Exxon weighs a bid"), {"weigh"})
        self.assertEqual(hedges_in("Profits are expected to rise"), {"expect"})
        self.assertEqual(hedges_in("yields cross 6%, possibly within October"), {"possible"})

    def test_hedge_counts_only_for_the_fact_it_qualifies(self):
        # Mon Oct 5: the euro and Aramco headlines restated other claims of their items and were replaced with
        # truncated claim text because a hedge elsewhere in the item ("would", "could") was missing from them.
        from reader.guards import dropped_hedges
        aramco = ["Saudi Aramco CEO Amin Nasser said global oil inventories could take up to two years to rebuild.",
                  "Nasser said the global supply cushion is 'scarily thin', with estimates that less than 6 billion barrels "
                  "of commercial inventories remain, most of it not practically available."]
        self.assertEqual(dropped_hedges("Aramco CEO: global oil stockpiles 'scarily thin'", aramco), set())
        self.assertEqual(dropped_hedges("Aramco CEO: oil inventories will take two years to rebuild", aramco), {"could"})
        euro = ["The euro fell to its weakest level since May 2025, a 17-month low against the dollar, as France's fiscal "
                "crisis and political upheaval in the region rattled European markets.",
                "Spanish Prime Minister Pedro Sánchez called an early election for Nov. 29 after parliament rejected a housing "
                "plan his government had hoped would quell mounting social protests."]
        self.assertEqual(dropped_hedges("Euro slumps to 17-month low as France, Spain turmoil mount", euro), set())
        self.assertEqual(dropped_hedges("Sánchez's housing plan quelled social protests", euro), {"would", "hope"})
        self.assertEqual(dropped_hedges("A housing plan meant to quell social protests failed", euro), set())
        # the hedged subject counts too: "set to surge" restated as "jump" is still an upgrade
        self.assertEqual(dropped_hedges("Brazil assets jump", ["Brazilian assets are set to surge as investors price in a new government"]),
                         {"set to"})


class NextSessionTests(unittest.TestCase):
    def test_weekend_and_pre_open_runs(self):
        from reader.stages.common import Window
        sat = datetime(2026, 9, 26, 11, 16, tzinfo=NY)
        self.assertEqual(Window(sat, sat, "America/New_York").next_session(), "Monday, Sep 28")
        tue = datetime(2026, 9, 29, 6, 30, tzinfo=NY)
        self.assertEqual(Window(tue, tue, "America/New_York").next_session(), "today")
        fri_evening = datetime(2026, 9, 25, 18, 0, tzinfo=NY)
        self.assertEqual(Window(fri_evening, fri_evening, "America/New_York").next_session(), "Monday, Sep 28")


class StaticCalendarTests(unittest.TestCase):
    def test_config_calendar_is_loaded_with_its_source_page(self):
        import tempfile
        from pathlib import Path
        from reader.schedule import load_static_calendar
        from reader.store import Store

        with tempfile.TemporaryDirectory() as tmp:
            st = Store(Path(tmp) / "c.db")
            self.assertEqual(load_static_calendar(st), [])
            rows = st.calendar_between("2026-09-28", "2026-10-02")
            self.assertTrue(any("Employment Situation" in r["title"] and r["event_date"] == "2026-10-02" for r in rows))
            self.assertTrue(all(r["url"].startswith("https://www.bls.gov") for r in rows if "Bureau of Labor" in r["publisher"]))
            # loading twice does not duplicate
            load_static_calendar(st)
            self.assertEqual(len(st.calendar_between("2026-09-28", "2026-10-02")), len(rows))


class SingleSourceTagTests(unittest.TestCase):
    def test_tag_only_for_unconfirmed_items_without_a_caveat(self):
        from reader.render import _caveat, _single_source
        from reader.stages.check import VerifiedClaim
        from reader.stages.write import BriefItem, Line

        def item(*statuses):
            claims = [VerifiedClaim(f"V{i}", "T1", "t", "event", s, "reported", [ev(1, "Bloomberg")], [], None, "t")
                      for i, s in enumerate(statuses, start=1)]
            return BriefItem("top", "T1", Line("h", claims), [Line("s", claims)], "", ["trading"], None)

        self.assertTrue(_single_source(item("reported")) and not _caveat(item("reported")))
        self.assertFalse(_single_source(item("confirmed", "reported")))
        self.assertTrue(_caveat(item("attributed")))  # caveat, so no tag on top of it


class FallbackHeadlineTests(unittest.TestCase):
    """When the writer's headline and the audit's correction both fail, the headline is built from the claims'
    own wording. Until Mon Oct 5 that was the first claim cut at 14 words, and 7 of 20 headlines read that way."""

    def headline(self, *claims):
        from reader.stages.audit import _headline_from
        from reader.stages.write import Line

        class C:
            def __init__(self, text, status="reported"):
                self.text, self.status = text, status
        return _headline_from(Line("x", [C(c) if isinstance(c, str) else c for c in claims]))

    def test_short_claim_whole_without_its_attribution(self):
        self.assertEqual(self.headline("C.H. Robinson agreed to buy truck broker RXO for around $5 billion in cash and stock, the WSJ reported."),
                         "C.H. Robinson agreed to buy truck broker RXO for around $5 billion in cash and stock")

    def test_long_claim_ends_at_its_first_clause(self):
        self.assertEqual(self.headline("Strikes hit tankers in the Strait of Hormuz and oil infrastructure in Saudi Arabia even as the "
                                       "region's exporters were getting more oil to market, the New York Times reported."),
                         "Strikes hit tankers in the Strait of Hormuz and oil infrastructure in Saudi Arabia")
        self.assertEqual(self.headline("Shares rose as much as 5% after the company raised its forecast and announced a buyback of up to "
                                       "$2 billion over three years, Bloomberg reported."), "Shares rose as much as 5%")

    def test_checker_dates_after_a_weekday_are_left_to_the_sentences(self):
        self.assertEqual(self.headline("The Trump administration is set to return to court on Wednesday, September 30, to defend its power "
                                       "to wage a global trade war, the third time in less than two years, the New York Times reported."),
                         "The Trump administration is set to return to court on Wednesday to defend its power to wage a global trade war")

    def test_unconfirmed_claim_keeps_its_attribution(self):
        text = "The US is reportedly sending a third carrier group to the Middle East, CNBC reported."
        claim = type("C", (), {"text": text, "status": "attributed"})()
        self.assertEqual(self.headline(claim), text.rstrip("."))

    def test_an_aside_is_never_a_headline_and_the_last_resort_does_not_end_on_a_function_word(self):
        self.assertEqual(self.headline("Schneider Electric, the French group, agreed to buy PTC for $22.6 billion in a deal that would "
                                       "create one of the largest industrial software portfolios in the world."),
                         "Schneider Electric, the French group, agreed to buy PTC for $22.6 billion…")


class DevelopingPlacementTests(unittest.TestCase):
    def test_reported_news_filed_under_developing_moves_to_further_items(self):
        # Mon Oct 5, second brief: all five Developing items, headed "not yet confirmed", carried reported claims,
        # among them Bolsonaro's first-round lead (Bloomberg, WSJ, FT)
        from reader.config import load_settings
        from reader.stages.check import CheckedStory, VerifiedClaim
        from reader.stages.find import Story
        from reader.stages.write import Item, Sentence, WriteOut, place

        def story(key, status):
            st = Story(key=key, title=key, continues=None, category="markets", region="global", audiences=["trading"],
                       materiality=2, why_it_matters="")
            vc = VerifiedClaim(id=f"V{key[1:]}", story_key=key, text=f"Claim of {key}.", kind="event", status=status,
                               basis="reported", evidence=[], quotes=[], event_date=None, original="")
            return CheckedStory(st, [vc])

        def item(key):
            return Item(story=key, headline=f"Headline {key}", headline_claims=[f"V{key[1:]}"],
                        what_changed=[Sentence(text=f"Claim of {key}.", claims=[f"V{key[1:]}"])], why_it_matters="",
                        audiences=["trading"])

        stories = [story("T1", "reported"), story("T2", "attributed"), story("T3", "confirmed")]
        out = WriteOut(summary="s", summary_claims=["V1"], top=[], second=[], developing=[item("T1"), item("T2"), item("T3")], session=[],
                       calendar=[])
        brief = place(out, stories, [], load_settings())
        self.assertEqual([i.story_key for i in brief.developing], ["T2"])
        self.assertEqual([i.story_key for i in brief.second], ["T1", "T3"])
        self.assertTrue(any("out of Developing" in n for n in brief.notes))



class AttributionTests(unittest.TestCase):
    """A sentence resting on an unconfirmed report must name the outlet, and code adds it when the text doesn't.
    The added name must be true of everything it covers."""

    def claim(self, text, status, *publishers):
        from reader.stages.check import VerifiedClaim
        evidence = [Evidence("i1", p, "s", 1, p, "news", "https://x", "2026-10-06T00:00:00+00:00", "t", "t", "", True)
                    for p in publishers]
        return VerifiedClaim(id="V1", story_key="T1", text=text, kind="report", status=status, basis="reported",
                             evidence=evidence, quotes=[], event_date=None, original=text)

    def attribute(self, text, *claims):
        from reader.stages.audit import _attribute
        from reader.stages.write import Line
        return _attribute(text, Line(text, list(claims)))

    def test_a_prefix_never_covers_a_claim_another_outlet_reported(self):
        # Tue Oct 6, the Saudi item: "Bloomberg reports:" was put over the WSJ's Houthi airport strikes
        strikes = self.claim("Yemen's Houthi rebels struck two airports in Saudi Arabia, the WSJ reported.", "reported",
                             "The Wall Street Journal")
        tankers = self.claim("The U.S. blockade of Iran is keeping dozens of laden tankers bottled up along the nation's coast, "
                             "according to United Against Nuclear Iran.", "attributed", "Bloomberg")
        text, how = self.attribute("Houthi rebels struck two airports in Saudi Arabia, the WSJ reported, while a U.S. blockade is "
                                   "keeping dozens of laden tankers bottled up along Iran's coast, according to United Against "
                                   "Nuclear Iran.", strikes, tankers)
        self.assertEqual(how, "split")
        self.assertEqual(text, "Yemen's Houthi rebels struck two airports in Saudi Arabia, the WSJ reported. Bloomberg reports: "
                               "The U.S. blockade of Iran is keeping dozens of laden tankers bottled up along the nation's coast, "
                               "according to United Against Nuclear Iran.")

    def test_a_prefix_is_kept_when_every_claim_rests_on_the_outlet(self):
        rosengren = self.claim("Former Boston Fed President Eric Rosengren said the Fed is likely to wait until its final meeting "
                               "of the year.", "attributed", "Bloomberg")
        text, how = self.attribute("Rosengren said the Fed is likely to wait until its final meeting of the year.", rosengren)
        self.assertEqual((text, how), ("Bloomberg reports: Rosengren said the Fed is likely to wait until its final meeting "
                                       "of the year.", "prefixed"))
        both = self.claim("Moonshot AI closed its final private round at about $50 billion, people familiar said.",
                          "attributed", "Bloomberg", "Euronews")
        self.assertEqual(self.attribute("Moonshot AI closed its final private round at about $50 billion.", both)[0],
                         "Bloomberg and Euronews report: Moonshot AI closed its final private round at about $50 billion.")

    def test_an_outlet_is_named_only_as_a_whole_word(self):
        # "FT" was found inside "after", so an FT-sourced report went out unattributed
        talks = self.claim("McKesson is nearing a deal for Option Care, people familiar said.", "attributed", "Financial Times")
        self.assertEqual(self.attribute("McKesson is nearing a deal for Option Care after weeks of talks.", talks)[1], "prefixed")
        self.assertEqual(self.attribute("McKesson is nearing a deal for Option Care, the FT reported.", talks), (
            "McKesson is nearing a deal for Option Care, the FT reported.", None))
