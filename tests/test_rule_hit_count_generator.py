"""Tests for the Rule Hit Count report generator (and the shared rule baseline)."""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import MagicMock

from src.report.policy_usage_generator import build_rule_baseline
from src.report.rule_hit_count_generator import (
    CLEANUP_DAYS_THRESHOLD,
    RuleHitCountGenerator,
    RuleHitCountResult,
    _norm_header,
)


def _write_native_csv(dirpath: str) -> str:
    """Write a CSV shaped like the PCE-native Rule Hit Count export."""
    path = os.path.join(dirpath, "rule-hit-count.csv")
    with open(path, "w", encoding="utf-8-sig") as fh:
        fh.write(
            "Rule HREF,Rule Name,Rule Set HREF,Rule Set Name,Rule Hit Count,"
            "Days Since Last Hit,Start Date,End Date\n"
            "/orgs/1/sec_policy/active/rule_sets/10/sec_rules/100,allow web,"
            "/orgs/1/sec_policy/active/rule_sets/10,RS-A,42,3,2026-06-01,2026-07-01\n"
            "/orgs/1/sec_policy/active/rule_sets/10/sec_rules/101,stale allow,"
            "/orgs/1/sec_policy/active/rule_sets/10,RS-A,5,120,2026-06-01,2026-07-01\n"
            "/orgs/1/sec_policy/active/rule_sets/11/deny_rules/200,deny legacy,"
            "/orgs/1/sec_policy/active/rule_sets/11,RS-Legacy,0,,2026-06-01,2026-07-01\n"
        )
    return path


def _sample_rulesets():
    return [{
        "href": "/orgs/1/sec_policy/draft/rule_sets/10",
        "name": "RS-A",
        "scopes": [[{"label": {"href": "/orgs/1/labels/1"}}]],
        "rules": [
            {"href": "/orgs/1/sec_policy/draft/rule_sets/10/sec_rules/100",
             "enabled": True, "description": "allow web",
             "consumers": [{"actors": "ams"}],
             "providers": [{"label": {"href": "/orgs/1/labels/2"}}],
             "ingress_services": [{"port": 443, "proto": 6}]},
        ],
        "deny_rules": [
            {"href": "/orgs/1/sec_policy/draft/rule_sets/10/deny_rules/200",
             "enabled": True, "override": True},
        ],
    }]


class TestBuildRuleBaseline(unittest.TestCase):
    def test_flattens_and_annotates(self):
        flat_rules, ruleset_map = build_rule_baseline(_sample_rulesets())
        self.assertEqual(len(flat_rules), 2)
        self.assertEqual(ruleset_map["/orgs/1/sec_policy/draft/rule_sets/10"], "RS-A")
        allow, deny = flat_rules
        self.assertEqual(allow["_rule_type"], "Allow")
        self.assertEqual(allow["_ruleset_name"], "RS-A")
        self.assertEqual(allow["_rule_no"], 1)
        self.assertEqual(allow["_rule_id"], "100")
        self.assertEqual(deny["_rule_type"], "Override Deny")
        self.assertEqual(deny["_rule_no"], 2)


class TestNormHeader(unittest.TestCase):
    def test_native_headers_normalize(self):
        self.assertEqual(_norm_header("Rule HREF"), "rule_href")
        self.assertEqual(_norm_header("Rule Hit Count"), "rule_hit_count")
        self.assertEqual(_norm_header("  Days Since Last Hit "), "days_since_last_hit")


class TestGenerateFromCsv(unittest.TestCase):
    def test_parses_native_csv_without_api(self):
        gen = RuleHitCountGenerator(MagicMock(), api_client=None)
        with tempfile.TemporaryDirectory() as td:
            result = gen.generate_from_csv(_write_native_csv(td), lang="en")
        self.assertIsInstance(result, RuleHitCountResult)
        self.assertEqual(result.record_count, 3)
        self.assertEqual(result.source, "csv")
        self.assertEqual(result.date_range, ("2026-06-01", "2026-07-01"))
        kpis = result.module_results["kpis"]
        self.assertEqual(kpis["total_rules"], 3)
        self.assertEqual(kpis["hit_rules"], 2)
        self.assertEqual(kpis["unused_rules"], 1)
        self.assertEqual(kpis["total_hits"], 47)
        hit_df = result.module_results["hit_df"]
        self.assertEqual(list(hit_df["hit_count"]), [42, 5])   # desc by hits

    def test_missing_required_columns_raises(self):
        gen = RuleHitCountGenerator(MagicMock(), api_client=None)
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "bad.csv")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("foo,bar\n1,2\n")
            with self.assertRaises(ValueError):
                gen.generate_from_csv(path)


class TestCleanupCandidates(unittest.TestCase):
    def test_cleanup_includes_unused_and_stale_enabled_rules(self):
        # Without enrichment 'enabled' is '', so cleanup only applies when
        # enrichment sets enabled=True. Enrich rows 100/101 via mocked api.
        api = MagicMock()
        api.get_all_rulesets.return_value = [{
            "href": "/orgs/1/sec_policy/active/rule_sets/10",
            "name": "RS-A",
            "scopes": [],
            "rules": [
                {"href": "/orgs/1/sec_policy/active/rule_sets/10/sec_rules/100", "enabled": True},
                {"href": "/orgs/1/sec_policy/active/rule_sets/10/sec_rules/101", "enabled": True},
            ],
        }]
        api.resolve_actor_str.return_value = "Any"
        api.resolve_service_str.return_value = "All Services"
        gen = RuleHitCountGenerator(MagicMock(), api_client=api)
        with tempfile.TemporaryDirectory() as td:
            result = gen.generate_from_csv(_write_native_csv(td))
        cleanup = result.module_results["cleanup_df"]
        # rule 101: enabled, 120 days since last hit >= 90 → cleanup candidate
        self.assertIn("101", list(cleanup["rule_id"]))
        # rule 100: 3 days since last hit, has hits → NOT a candidate
        self.assertNotIn("100", list(cleanup["rule_id"]))
        self.assertEqual(CLEANUP_DAYS_THRESHOLD, 90)


class TestCsvEnrichment(unittest.TestCase):
    def test_enriches_matching_hrefs(self):
        api = MagicMock()
        api.get_all_rulesets.return_value = _sample_rulesets()
        api.resolve_actor_str.return_value = "All Workloads"
        api.resolve_service_str.return_value = "443/tcp"
        gen = RuleHitCountGenerator(MagicMock(), api_client=api)
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "rhc.csv")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(
                    "Rule HREF,Rule Hit Count\n"
                    "/orgs/1/sec_policy/draft/rule_sets/10/sec_rules/100,7\n"
                )
            result = gen.generate_from_csv(path)
        row = result.dataframe[result.dataframe["rule_id"] == "100"].iloc[0]
        self.assertEqual(row["consumers"], "All Workloads")
        self.assertEqual(row["services"], "443/tcp")
        self.assertEqual(row["ruleset"], "RS-A")
        self.assertEqual(row["rule_type"], "Allow")
        self.assertEqual(row["enabled"], True)

    def test_enrichment_failure_is_non_fatal_and_flagged(self):
        api = MagicMock()
        api.get_all_rulesets.side_effect = ConnectionError("PCE down")
        gen = RuleHitCountGenerator(MagicMock(), api_client=api)
        with tempfile.TemporaryDirectory() as td:
            result = gen.generate_from_csv(_write_native_csv(td))
        self.assertEqual(result.record_count, 3)
        self.assertTrue(result.module_results.get("enrich_failed"))


if __name__ == "__main__":
    unittest.main()
