"""Settings: this machine's local.toml over the shared settings, and the sources policy."""

import tempfile
import tomllib
import unittest
from pathlib import Path

from reader.config import CONFIG_DIR, POLICIES, TERMS, load_settings, merge, set_local
from reader.net import tls_context


class LocalSettingsTest(unittest.TestCase):
    def test_local_overrides_key_by_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp) / "local.toml"
            local.write_text('[brief]\nowner = "Pat Example"\n\n[sources]\npolicy = "official"\n')
            settings = load_settings(local=local)
            self.assertEqual(settings.raw["brief"]["owner"], "Pat Example")
            self.assertEqual(settings.raw["brief"]["top_max"], 5)  # untouched keys keep the shared value
            self.assertEqual(settings.source_policy, "official")

    def test_merge_replaces_lists_and_merges_tables(self):
        self.assertEqual(merge({"a": {"x": 1, "y": [1]}, "b": 2}, {"a": {"y": [2]}}), {"a": {"x": 1, "y": [2]}, "b": 2})

    def test_set_local_keeps_comments_and_other_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp) / "local.toml"
            set_local("sources", "policy", "unrestricted", local)
            local.write_text(local.read_text() + '\n[brief]\n# where briefs go\nworkbench = "/tmp/x"\n')
            set_local("sources", "policy", "all", local)
            set_local("brief", "owner", "Pat Example", local)
            text = local.read_text()
            data = tomllib.loads(text)
            self.assertEqual(data["sources"]["policy"], "all")
            self.assertEqual(data["brief"], {"workbench": "/tmp/x", "owner": "Pat Example"})
            self.assertIn("# where briefs go", text)
            self.assertEqual(text.count("policy ="), 1)


class SourcesPolicyTest(unittest.TestCase):
    def setUp(self):
        self.settings = load_settings(local=None)

    def test_every_source_has_known_terms(self):
        self.assertTrue(self.settings.sources)
        for s in self.settings.sources:
            self.assertIn(s.terms, TERMS, s.id)
            if s.kind in ("official", "calendar"):
                self.assertEqual(s.terms, "official", s.id)

    def test_policies_nest(self):
        counts = []
        for policy in ("official", "unrestricted", "all"):
            self.settings.raw["sources"]["policy"] = policy
            active = self.settings.active_sources()
            self.assertTrue(all(s.terms in POLICIES[policy] for s in active))
            counts.append(len(active))
        self.assertLess(counts[0], counts[1])
        self.assertLess(counts[1], counts[2])

    def test_unset_policy_reads_everything_and_off_list_wins(self):
        self.settings.raw["sources"]["policy"] = ""
        everything = self.settings.active_sources()
        self.assertTrue(any(s.terms == "restricts" for s in everything))
        self.settings.raw["sources"]["off"] = [everything[0].id]
        self.assertNotIn(everything[0].id, [s.id for s in self.settings.active_sources()])

    def test_shared_settings_leave_the_choice_to_the_machine(self):
        with open(CONFIG_DIR / "settings.toml", "rb") as f:
            shared = tomllib.load(f)
        self.assertEqual(shared["sources"]["policy"], "")
        self.assertEqual(shared["brief"]["workbench"], "")


class TLSTest(unittest.TestCase):
    def test_certificates_are_loaded(self):
        self.assertGreater(len(tls_context().get_ca_certs()) + tls_context().cert_store_stats()["x509_ca"], 0)


if __name__ == "__main__":
    unittest.main()
