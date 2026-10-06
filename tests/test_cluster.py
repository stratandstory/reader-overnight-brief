import unittest

from reader.cluster import group, select_groups, tokens


def item(iid, title, summary="", owner="Bloomberg", score=3, tier=1, when="2026-10-02T10:00:00+00:00"):
    return {"id": iid, "title": title, "summary": summary, "owner": owner, "publisher": owner, "tier": tier,
            "published_utc": when, "score": score}


class TokensTest(unittest.TestCase):
    def test_strips_stopwords_possessives_and_punctuation(self):
        self.assertEqual(tokens("The Fed's Waller says cuts are likely, in 2026."), ["fed", "waller", "cuts", "likely", "2026"])


class GroupTest(unittest.TestCase):
    def test_same_development_groups_and_distinct_stays_apart(self):
        a = item("a", "Treasury yields climb to fresh highs as oil rises", "The 30-year yield hit its highest since 2002.")
        b = item("b", "Treasury yields push to fresh highs", "30-year Treasury yield at highest level since 2002 as oil climbs.", owner="Dow Jones")
        c = item("c", "Boeing wins Navy contract for next fighter", "The Pentagon chose Boeing over Lockheed.", owner="NBCUniversal")
        groups = group([a, b, c], 0.45)
        self.assertEqual([[i["id"] for i in g] for g in groups], [["a", "b"], ["c"]])

    def test_membership_is_judged_against_the_leader_not_the_last_member(self):
        a = item("a", "Oil jumps as Iran talks stall")
        b = item("b", "Oil jumps as Iran talks stall, traders say", owner="Dow Jones")
        c = item("c", "Traders say equities fall", owner="Nikkei")  # resembles b a little, not a
        groups = group([a, b, c], 0.45)
        self.assertEqual(len(groups), 2)


class SelectGroupsTest(unittest.TestCase):
    def test_limit_counts_items_and_other_owners_come_first_in_a_group(self):
        items = [item(f"b{i}", "Treasury yields climb to fresh highs as oil rises", owner="Bloomberg",
                      when=f"2026-10-02T1{i}:00:00+00:00") for i in range(4)]
        items.append(item("w", "Treasury yields climb to fresh highs as oil rises", owner="Dow Jones", when="2026-10-02T09:00:00+00:00"))
        items.append(item("x", "Boeing wins Navy contract", owner="NBCUniversal", score=2))
        scores = {it["id"]: it["score"] for it in items}
        groups = select_groups(items, scores, limit=4, threshold=0.45, per_group=3)
        self.assertEqual(sum(len(g) for g in groups), 4)
        self.assertEqual(len(groups), 2)
        first = {it["id"] for it in groups[0]}
        self.assertIn("w", first, "the second owner's copy is kept ahead of the leader's own later copies")
        self.assertEqual(len(first), 3)
        self.assertEqual([it["id"] for it in groups[1]], ["x"])

    def test_groups_are_ranked_by_screen_score_then_tier(self):
        lo = item("lo", "Minor retail news", score=2)
        official = item("off", "FOMC statement", score=3, tier=0, owner="Federal Reserve")
        hi = item("hi", "Oil jumps as Iran talks stall", score=3)
        groups = select_groups([lo, hi, official], {"lo": 2, "hi": 3, "off": 3}, limit=10, threshold=0.45)
        self.assertEqual([g[0]["id"] for g in groups], ["off", "hi", "lo"])

    def test_owner_floor_gives_every_owner_turns_before_tier_decides(self):
        # Mon Oct 5: ranking by tier put every tier-1 item at score 2 ahead of every tier-2 one, so with the
        # cap full no tier-2 owner led a development
        heads = ["Euro slides on French fiscal worry", "Schneider buys PTC", "Aramco cuts Asia prices",
                 "Brazil runoff set for October", "Hon Hai sales beat estimates", "Spain calls snap election",
                 "Samsung chip exports surge", "Korea won weakens past 1,400", "Hyundai recalls sedans"]
        big = [item(f"b{n}", heads[n], owner="Bloomberg", score=2, when=f"2026-10-05T0{n}:00:00+00:00") for n in range(6)]
        small = [item(f"y{n}", heads[6 + n], owner="Yonhap", score=2, tier=2, when=f"2026-10-04T0{n}:00:00+00:00")
                 for n in range(3)]
        scores = {it["id"]: 2 for it in big + small}
        ids = lambda gs: {it["id"] for g in gs for it in g}
        self.assertEqual(ids(select_groups(big + small, scores, limit=4, threshold=0.45)), {"b5", "b4", "b3", "b2"})
        floored = select_groups(big + small, scores, limit=4, threshold=0.45, owner_floor=2)
        self.assertEqual(ids(floored), {"b5", "b4", "y2", "y1"})
        # within the floor, owners take turns: each owner's newest, then each owner's second
        self.assertEqual([g[0]["id"] for g in floored], ["b5", "y2", "b4", "y1"])
