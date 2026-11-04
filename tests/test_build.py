"""Tests for the data scripts. They use invented sample topics in
tests/fixtures (titles start with EXAMPLE) and never touch the network.

Run:  python -m unittest discover -s tests -v
"""

import json
import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_calls  # noqa: E402
import fetch  # noqa: E402

TODAY = date(2026, 11, 4)
FIXTURE = ROOT / "tests" / "fixtures" / "raw_topics_sample.json"


class BuildTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        shutil.copy(FIXTURE, self.tmp / "raw_topics.json")
        shutil.copy(ROOT / "data" / "programmes.json", self.tmp / "programmes.json")
        (self.tmp / "manual_calls.json").write_text("[]")
        (self.tmp / "tags.csv").write_text(
            "identifier,tag_status,ssh_flag,erc_domains,erc_panels,scheme,reviewed_by,note\n"
        )

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def build(self, **kw):
        return build_calls.build(TODAY, kw.get("allow_drop", False), data_dir=self.tmp)

    def by_id(self, data):
        return {c["identifier"]: c for c in data["calls"]}


class TestSelection(BuildTestCase):
    def test_keeps_only_applicable_2027_calls(self):
        calls = self.by_id(self.build())
        self.assertEqual(sorted(calls), sorted([
            "HORIZON-CL2-2027-01-TEST-01",
            "ERC-2027-STG",
            "HORIZON-CL4-2027-03-TEST-03",
            "HORIZON-CL6-2027-TEST-CSA",
            "HORIZON-MSCA-2027-PF-01-01",
        ]))

    def test_two_stage_with_first_stage_in_2026_is_dropped(self):
        self.assertNotIn("HORIZON-CL5-2027-02-TEST-02", self.by_id(self.build()))

    def test_closed_label_ignored_when_deadline_is_2027(self):
        call = self.by_id(self.build())["HORIZON-CL6-2027-TEST-CSA"]
        self.assertEqual(call["status"], "open")


class TestFields(BuildTestCase):
    def test_rich_topic(self):
        c = self.by_id(self.build())["HORIZON-CL2-2027-01-TEST-01"]
        self.assertEqual(c["programme"], "Horizon Europe")
        self.assertEqual(c["pillar_or_cluster"], "Cluster 2: Culture, Creativity and Inclusive Society")
        self.assertEqual(c["deadlines"], ["2027-02-10"])
        self.assertEqual(c["opening_date"], "2026-10-01")
        self.assertEqual(c["budget_per_project_eur"], {"min": 3000000, "max": 3000000})
        self.assertEqual(c["scheme"], "consortium")
        self.assertEqual(c["stages"], 1)
        self.assertIs(c["ssh_flag"], True)
        self.assertEqual(c["tag_status"], "suggested")
        self.assertEqual(
            c["portal_url"],
            "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/"
            "opportunities/topic-details/horizon-cl2-2027-01-test-01",
        )
        self.assertEqual(c["last_checked"], "2026-11-04")

    def test_missing_values_stay_empty(self):
        c = self.by_id(self.build())["HORIZON-CL6-2027-TEST-CSA"]
        self.assertIsNone(c["budget_per_project_eur"])
        self.assertIsNone(c["opening_date"])

    def test_two_stage_deadlines_sorted(self):
        c = self.by_id(self.build())["HORIZON-CL4-2027-03-TEST-03"]
        self.assertEqual(c["stages"], 2)
        self.assertEqual(c["deadlines"], ["2027-01-20", "2027-09-10"])
        self.assertEqual(c["scheme"], "consortium")
        self.assertEqual(c["budget_per_project_eur"], {"min": 4000000, "max": 6000000})
        self.assertEqual(c["ssh_flag"], "unknown")
        self.assertEqual(c["tag_status"], "untagged")

    def test_scheme_rules(self):
        calls = self.by_id(self.build())
        self.assertEqual(calls["ERC-2027-STG"]["scheme"], "individual")
        self.assertEqual(calls["HORIZON-MSCA-2027-PF-01-01"]["scheme"], "individual")
        self.assertEqual(calls["HORIZON-CL6-2027-TEST-CSA"]["scheme"], "either")

    def test_forthcoming_from_opening_date(self):
        self.assertEqual(self.by_id(self.build())["ERC-2027-STG"]["status"], "forthcoming")

    def test_cross_cutting_ssh_suggestion(self):
        c = self.by_id(self.build())["HORIZON-CL6-2027-TEST-CSA"]
        self.assertIs(c["ssh_flag"], True)
        self.assertEqual(c["tag_status"], "suggested")

    def test_programmes_listed_from_data(self):
        self.assertEqual(self.build()["programmes"], ["Horizon Europe"])


class TestLiveDataQuirks(BuildTestCase):
    """Cases found in the live API data on 2026-11-04."""

    def add_topic(self, ident, budget_entries=None, toa="HORIZON Research and Innovation Actions"):
        raw = json.loads((self.tmp / "raw_topics.json").read_text())
        meta = {
            "identifier": [ident], "title": [f"EXAMPLE {ident}"], "type": ["1"],
            "status": ["31094501"], "deadlineDate": ["2027-03-03T00:00:00.000+0000"],
            "deadlineModel": ["single-stage"], "startDate": ["2026-12-01T00:00:00.000+0000"],
            "typesOfAction": [toa],
        }
        if budget_entries is not None:
            meta["budgetOverview"] = [json.dumps({"budgetTopicActionMap": {"1": budget_entries}})]
        raw["topics"].append({"url": None, "reference": ident, "metadata": meta})
        (self.tmp / "raw_topics.json").write_text(json.dumps(raw))

    def test_zero_budget_is_missing(self):
        self.add_topic("HORIZON-MSCA-2027-DN-01-01", [
            {"action": "HORIZON-MSCA-2027-DN-01-01 - HORIZON-TMA-MSCA-DN", "minContribution": 0, "maxContribution": 0}])
        self.assertIsNone(self.by_id(self.build())["HORIZON-MSCA-2027-DN-01-01"]["budget_per_project_eur"])

    def test_budget_matches_whole_identifier(self):
        self.add_topic("HORIZON-CL5-2027-09-X-01", [
            {"action": "HORIZON-CL5-2027-09-X-01-two-stage - HORIZON-RIA", "minContribution": 9000000, "maxContribution": 9000000},
            {"action": "HORIZON-CL5-2027-09-X-01 - HORIZON-RIA", "minContribution": 2000000, "maxContribution": 2500000}])
        c = self.by_id(self.build())["HORIZON-CL5-2027-09-X-01"]
        self.assertEqual(c["budget_per_project_eur"], {"min": 2000000, "max": 2500000})

    def test_cancelled_topic_dropped(self):
        self.add_topic("HORIZON-NEB-2027-01-REGEN-03-CANCELLED")
        self.assertNotIn("HORIZON-NEB-2027-01-REGEN-03-CANCELLED", self.by_id(self.build()))

    def test_euratom_prefix(self):
        self.add_topic("HORIZON-EURATOM-2027-01-01")
        c = self.by_id(self.build())["HORIZON-EURATOM-2027-01-01"]
        self.assertEqual(c["programme"], "Euratom Research and Training Programme")

    def test_era_fellowship_is_individual(self):
        self.add_topic("HORIZON-WIDERA-2027-03-WIDENING-01",
                       toa="HORIZON TMA MSCA Postdoctoral Fellowships - European Fellowships")
        self.assertEqual(self.by_id(self.build())["HORIZON-WIDERA-2027-03-WIDENING-01"]["scheme"], "individual")

    def test_double_space_in_action_name(self):
        self.add_topic("HORIZON-CL3-2027-01-X-01", toa="HORIZON  Research and Innovation Actions")
        self.assertEqual(self.by_id(self.build())["HORIZON-CL3-2027-01-X-01"]["scheme"], "consortium")


class TestTagsAndManual(BuildTestCase):
    def test_reviewed_tag_overrides(self):
        with (self.tmp / "tags.csv").open("a") as fh:
            fh.write("HORIZON-CL4-2027-03-TEST-03,reviewed,true,,SH3;SH7,either,MO,Checked\n")
        c = self.by_id(self.build())["HORIZON-CL4-2027-03-TEST-03"]
        self.assertEqual(c["tag_status"], "reviewed")
        self.assertIs(c["ssh_flag"], True)
        self.assertEqual(c["erc_panels"], ["SH3", "SH7"])
        self.assertEqual(c["erc_domains"], ["SH"])
        self.assertEqual(c["scheme"], "either")

    def test_bad_panel_rejected(self):
        with (self.tmp / "tags.csv").open("a") as fh:
            fh.write("ERC-2027-STG,reviewed,,,SH9,,,\n")
        with self.assertRaises(build_calls.BuildError):
            self.build()

    def test_manual_call_added(self):
        (self.tmp / "manual_calls.json").write_text(json.dumps([{
            "identifier": "EXAMPLE-MANUAL-2027",
            "title": "EXAMPLE manual call",
            "programme": "Example Programme",
            "portal_url": "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/example",
            "deadlines": ["2027-06-01"],
            "last_checked": "2026-11-01",
        }]))
        data = self.build()
        c = self.by_id(data)["EXAMPLE-MANUAL-2027"]
        self.assertIsNone(c["budget_per_project_eur"])
        self.assertIsNone(c["scheme"])
        self.assertIn("Example Programme", data["programmes"])

    def test_manual_call_needs_portal_link(self):
        (self.tmp / "manual_calls.json").write_text(json.dumps([{
            "identifier": "X", "title": "X", "programme": "X",
            "portal_url": "https://example.com/x", "deadlines": ["2027-06-01"], "last_checked": "2026-11-01",
        }]))
        with self.assertRaises(build_calls.BuildError):
            self.build()


class TestSafety(BuildTestCase):
    def test_empty_raw_refused(self):
        (self.tmp / "raw_topics.json").write_text(json.dumps({"fetched_at": "2026-11-04T00:00:00Z", "topics": []}))
        with self.assertRaises(build_calls.BuildError):
            self.build()

    def test_no_2027_calls_refused(self):
        with self.assertRaises(build_calls.BuildError):
            build_calls.build(date(2028, 1, 1), False, data_dir=self.tmp)

    def test_sharp_drop_refused(self):
        previous = {"calls": [{"identifier": str(i)} for i in range(20)]}
        (self.tmp / "calls.json").write_text(json.dumps(previous))
        with self.assertRaises(build_calls.BuildError):
            self.build()
        self.assertEqual(len(self.build(allow_drop=True)["calls"]), 5)


class TestFetch(unittest.TestCase):
    def test_multipart_carries_filters(self):
        body, ctype = fetch._multipart({"query": fetch.QUERY, "languages": ["en"]})
        self.assertTrue(ctype.startswith("multipart/form-data; boundary="))
        self.assertIn(b'name="query"', body)
        self.assertIn(b'"31094502"', body)
        self.assertIn(b'name="languages"', body)

    def test_partial_results_refused(self):
        page = {"totalResults": 150, "results": [{"metadata": {"identifier": ["A"]}}] * 100}
        short = {"totalResults": 150, "results": [{"metadata": {"identifier": ["B"]}}] * 10}
        with mock.patch.object(fetch, "fetch_page", side_effect=[page, short]), \
             mock.patch.object(fetch.time, "sleep"):
            with self.assertRaises(fetch.FetchError):
                fetch.fetch_all()

    def test_ignored_filters_detected(self):
        page = {"totalResults": 90000, "results": []}
        with mock.patch.object(fetch, "fetch_page", return_value=page):
            with self.assertRaises(fetch.FetchError):
                fetch.fetch_all()

    def test_failed_fetch_keeps_existing_file(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            out = tmp / "raw_topics.json"
            out.write_text('{"old": true}')
            with mock.patch.object(fetch, "OUT_FILE", out), \
                 mock.patch.object(fetch, "fetch_all", side_effect=fetch.FetchError("boom")):
                self.assertEqual(fetch.main(), 1)
            self.assertEqual(out.read_text(), '{"old": true}')
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
