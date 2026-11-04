"""Tests for department matching (scripts/match.py) and the description
cache in scripts/fetch.py. No network access; sample data is invented.

Run:  python -m unittest discover -s tests -v
"""

import json
import shutil
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_calls  # noqa: E402
import fetch  # noqa: E402
import match  # noqa: E402


class TestTermPattern(unittest.TestCase):
    def hits(self, term, text):
        return bool(match.term_pattern(term).search(text))

    def test_hyphen_space_and_joined(self):
        for text in ("start-ups", "start ups", "startups", "a start-up"):
            self.assertTrue(self.hits("start-ups", text), text)

    def test_spelling_variants(self):
        self.assertTrue(self.hits("organisations", "research organizations"))
        self.assertTrue(self.hits("consumer behaviour", "consumer behavior"))
        self.assertTrue(self.hits("labour market", "the labor market"))

    def test_singular_and_plural(self):
        self.assertTrue(self.hits("SMEs", "every SME"))
        self.assertTrue(self.hits("museums", "a museum"))
        self.assertTrue(self.hits("ESG", "ESG reporting"))

    def test_whole_words_only(self):
        self.assertFalse(self.hits("ports", "supports"))
        self.assertFalse(self.hits("ports", "sports"))
        self.assertFalse(self.hits("trust", "trustworthy"))

    def test_case_insensitive(self):
        self.assertTrue(self.hits("New European Bauhaus", "the new european bauhaus"))


PROFILE = {"id": "x", "name": "X", "erc_panels": ["SH8", "SH1"],
           "search_terms": ["cultural heritage", "museums", "audiences", "family business"]}


class TestScore(unittest.TestCase):
    def test_title_tag_description_weights(self):
        call = {"title": "EXAMPLE Cultural heritage and society", "erc_panels": []}
        desc = {"tags": ["Museums"], "keywords": [], "text": "Reach new audiences. Cultural heritage again."}
        result = match.score_call(call, PROFILE, desc)
        self.assertEqual(result["terms"], ["cultural heritage", "museums", "audiences"])
        self.assertEqual(result["score"], match.TITLE_POINTS + match.TAG_POINTS + match.DESCRIPTION_POINTS)

    def test_panels_score_main_higher(self):
        call = {"title": "EXAMPLE", "erc_panels": ["SH1", "SH8"]}
        result = match.score_call(call, PROFILE, None)
        self.assertEqual(result["panels"], ["SH8", "SH1"])
        self.assertEqual(result["score"], match.MAIN_PANEL_POINTS + match.OTHER_PANEL_POINTS)
        only_other = match.score_call({"title": "EXAMPLE", "erc_panels": ["SH1"]}, PROFILE, None)
        self.assertEqual(only_other["score"], match.OTHER_PANEL_POINTS)

    def test_no_match(self):
        self.assertIsNone(match.score_call({"title": "EXAMPLE batteries", "erc_panels": []}, PROFILE,
                                           {"tags": [], "keywords": [], "text": "battery recycling"}))

    def test_title_only_without_description(self):
        result = match.score_call({"title": "EXAMPLE museums", "erc_panels": []}, PROFILE, None)
        self.assertEqual(result["terms"], ["museums"])


class TestOpenToAll(unittest.TestCase):
    def setUp(self):
        self.rules = match.load_profiles()["open_rules"]

    def label(self, identifier):
        return match.open_to_all_label(identifier, self.rules)

    def test_open_schemes(self):
        self.assertEqual(self.label("ERC-2027-COG"), "ERC")
        self.assertEqual(self.label("ERC-2027-AdG"), "ERC")
        self.assertEqual(self.label("HORIZON-MSCA-2027-PF-01-01"), "MSCA")
        self.assertEqual(self.label("HORIZON-MSCA-2027-DN-01-01"), "MSCA")
        self.assertEqual(self.label("HORIZON-EIC-2027-PATHFINDEROPEN-01"), "EIC Pathfinder Open")

    def test_not_open(self):
        self.assertIsNone(self.label("ERC-2027-POC"))           # only for ERC grantees
        self.assertIsNone(self.label("HORIZON-MSCA-2027-CITIZENS-01-01"))
        self.assertIsNone(self.label("HORIZON-CL2-2027-01-HERITAGE-04"))


class TestDepartmentsFile(unittest.TestCase):
    def test_structure(self):
        cfg = match.load_profiles()
        depts = [p for p in cfg["profiles"].values() if p["kind"] == "department"]
        topics = [p for p in cfg["profiles"].values() if p["kind"] == "topic"]
        self.assertEqual(len(depts), 9)
        self.assertEqual(len(topics), 10)
        for p in cfg["profiles"].values():
            self.assertRegex(p["id"], r"^[a-z0-9]+(-[a-z0-9]+)*$")
            self.assertTrue(p["search_terms"])
            self.assertTrue(p["description"].endswith("."))
            for panel in p["erc_panels"]:
                self.assertRegex(panel, build_calls.ERC_PANEL_RE)


class TestBuildAddsFits(unittest.TestCase):
    def test_build_with_departments(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            shutil.copy(ROOT / "tests" / "fixtures" / "raw_topics_sample.json", tmp / "raw_topics.json")
            for name in ("programmes.json", "departments.json"):
                shutil.copy(ROOT / "data" / name, tmp / name)
            (tmp / "manual_calls.json").write_text("[]")
            (tmp / "descriptions.json").write_text(json.dumps({"topics": {
                "HORIZON-CL2-2027-01-TEST-01": {"text": "Work with museums and their audiences.", "tags": [], "keywords": []}}}))
            data = build_calls.build(date(2026, 11, 4), False, data_dir=tmp)
            calls = {c["identifier"]: c for c in data["calls"]}
            self.assertEqual(calls["ERC-2027-STG"]["open_to_all_fields"], "ERC")
            self.assertIsNone(calls["HORIZON-CL2-2027-01-TEST-01"]["open_to_all_fields"])
            fit = calls["HORIZON-CL2-2027-01-TEST-01"]["fits"]["arts-management"]
            self.assertEqual(fit["terms"], ["audiences", "museums"])
        finally:
            shutil.rmtree(tmp)


def topic(identifier, deadline="2027-03-01T00:00:00.000+0000", extra="a"):
    return {"metadata": {"identifier": [identifier], "deadlineDate": [deadline], "x": [extra]}}


class TestDescriptionCache(unittest.TestCase):
    NOW = datetime(2026, 11, 4, 2, 30, tzinfo=timezone.utc)

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.path = self.tmp / "descriptions.json"
        self.calls = []
        self.sleep = mock.patch.object(fetch.time, "sleep")
        self.sleep.start()

    def tearDown(self):
        self.sleep.stop()
        shutil.rmtree(self.tmp)

    def fetcher(self, identifier):
        self.calls.append(identifier)
        if identifier.startswith("FAIL"):
            raise fetch.FetchError("boom")
        return {"description": f"<p>About <b>{identifier}</b></p>", "tags": ["T"], "keywords": ["K"]}

    def run_update(self, topics, now=None):
        return fetch.update_descriptions(topics, self.path, now or self.NOW, self.fetcher)

    def test_first_run_fetches_2027_topics_only(self):
        result = self.run_update([topic("A"), topic("OLD", "2026-12-01T00:00:00.000+0000")])
        self.assertEqual(self.calls, ["A"])
        self.assertEqual(result["topics"]["A"]["text"], "About A")
        self.assertEqual(result["topics"]["A"]["tags"], ["T"])

    def test_unchanged_topics_not_refetched(self):
        self.run_update([topic("A")])
        self.calls.clear()
        self.run_update([topic("A"), topic("B")], self.NOW + timedelta(days=1))
        self.assertEqual(self.calls, ["B"])

    def test_changed_metadata_refetched(self):
        self.run_update([topic("A")])
        self.calls.clear()
        self.run_update([topic("A", extra="changed")], self.NOW + timedelta(days=1))
        self.assertEqual(self.calls, ["A"])

    def test_weekly_full_refresh(self):
        self.run_update([topic("A")])
        self.calls.clear()
        self.run_update([topic("A")], self.NOW + timedelta(days=7))
        self.assertEqual(self.calls, ["A"])

    def test_failure_keeps_old_text(self):
        self.run_update([topic("FAIL-1")])  # no cached text: nothing stored
        self.assertNotIn("FAIL-1", json.loads(self.path.read_text())["topics"])
        cache = {"last_full_refresh": self.NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "topics": {"FAIL-2": {"text": "old text", "tags": [], "keywords": [], "metadata_hash": "stale"}}}
        self.path.write_text(json.dumps(cache))
        result = self.run_update([topic("FAIL-2")], self.NOW + timedelta(days=1))
        self.assertEqual(result["topics"]["FAIL-2"]["text"], "old text")

    def test_failed_full_refresh_not_recorded(self):
        result = self.run_update([topic("FAIL-1"), topic("FAIL-2"), topic("A")])
        self.assertIsNone(result["last_full_refresh"])

    def test_out_of_scope_topics_dropped(self):
        self.run_update([topic("A"), topic("B")])
        result = self.run_update([topic("A")], self.NOW + timedelta(days=1))
        self.assertEqual(list(result["topics"]), ["A"])

    def test_html_to_text(self):
        text = fetch.html_to_text('<p>Expected&nbsp;Outcome:</p><ul><li>one &amp; <b>two</b></li></ul>')
        self.assertEqual(text, "Expected Outcome:\n- one & two")


if __name__ == "__main__":
    unittest.main()
