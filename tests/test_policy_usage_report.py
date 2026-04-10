import unittest
import tempfile
import zipfile
import os
import json
from unittest.mock import MagicMock

from src.report.analysis.policy_usage.pu_mod00_executive import pu_executive_summary
from src.report.policy_usage_generator import PolicyUsageGenerator, PolicyUsageResult


class TestPolicyUsageExecutiveSummary(unittest.TestCase):
    def test_execution_stats_are_exposed(self):
        results = {
            "mod01": {
                "total_rules": 12,
                "hit_count": 5,
                "unused_count": 7,
                "hit_rate_pct": 41.7,
            },
            "mod03": {"unused_df": None},
            "meta": {
                "execution_stats": {
                    "cached_rules": 4,
                    "submitted_rules": 8,
                    "pending_jobs": 1,
                    "failed_jobs": 2,
                    "top_hit_ports": [{"port_proto": "443/tcp", "flow_count": 12}],
                }
            },
        }

        summary = pu_executive_summary(results, lookback_days=30)

        self.assertEqual(summary["execution_stats"]["cached_rules"], 4)
        labels = {item["label"]: item["value"] for item in summary["kpis"]}
        self.assertEqual(labels["Cached Reuse"], "4")
        self.assertEqual(labels["New Queries"], "8")
        self.assertEqual(labels["Top Hit Port"], "443/tcp")
        self.assertTrue(any("pending" in note.lower() for note in summary["execution_notes"]))
        self.assertTrue(any("failed" in note.lower() for note in summary["execution_notes"]))
        self.assertTrue(any("top observed hit ports" in note.lower() for note in summary["execution_notes"]))

    def test_report_metadata_contains_execution_summary(self):
        gen = PolicyUsageGenerator(MagicMock(), api_client=None)
        result = PolicyUsageResult(
            record_count=12,
            date_range=("2026-04-01", "2026-04-02"),
            module_results={
                "mod00": {
                    "kpis": [{"label": "Hit Rules", "value": "5"}],
                    "execution_notes": ["Reused 4 completed async summaries."],
                }
            },
            execution_stats={
                "cached_rules": 4,
                "submitted_rules": 8,
                "pending_jobs": 1,
                "failed_jobs": 2,
                "top_hit_ports": [{"port_proto": "443/tcp", "flow_count": 12}],
                "reused_rule_details": [{"rule_href": "/rules/1", "status": "reused"}],
                "pending_rule_details": [{"rule_href": "/rules/2", "status": "pending"}],
                "failed_rule_details": [{"rule_href": "/rules/3", "status": "failed"}],
            },
        )

        metadata = gen._build_report_metadata(result, file_format="html")

        self.assertEqual(metadata["report_type"], "policy_usage")
        self.assertEqual(metadata["file_format"], "html")
        self.assertIn("cache 4", metadata["summary"])
        self.assertIn("new 8", metadata["summary"])
        self.assertEqual(metadata["execution_stats"]["pending_jobs"], 1)
        self.assertEqual(metadata["top_hit_ports"][0]["port_proto"], "443/tcp")
        self.assertEqual(metadata["reused_rule_details"][0]["status"], "reused")
        self.assertEqual(metadata["pending_rule_details"][0]["status"], "pending")
        self.assertEqual(metadata["failed_rule_details"][0]["status"], "failed")
        self.assertIn("attack_summary", metadata)
        self.assertIn("boundary_breaches", metadata["attack_summary"])

    def test_export_writes_dashboard_summary_and_attack_metadata(self):
        gen = PolicyUsageGenerator(MagicMock(), api_client=None)
        result = PolicyUsageResult(
            module_results={
                "mod00": {
                    "kpis": [],
                    "execution_notes": [],
                    "boundary_breaches": [{"finding": "Unused high-risk rule", "action": "Review and tighten scope"}],
                    "suspicious_pivot_behavior": [],
                    "blast_radius": [],
                    "blind_spots": [],
                    "action_matrix": [{"action": "Disable stale rules", "priority": 70}],
                },
                "mod02": {"hit_df": None},
                "mod03": {"unused_df": None},
            },
            execution_stats={
                "reused_rule_details": [{"rule_href": "/rules/1", "status": "reused"}],
            },
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            paths = gen.export(result, fmt="csv", output_dir=tmpdir)
            self.assertEqual(len(paths), 1)

            metadata_path = paths[0] + ".metadata.json"
            self.assertTrue(os.path.exists(metadata_path))
            with open(metadata_path, "r", encoding="utf-8") as fh:
                metadata = json.load(fh)
            self.assertEqual(metadata["report_type"], "policy_usage")
            self.assertEqual(metadata["attack_summary_counts"]["boundary_breaches"], 1)

            summary_path = os.path.join(tmpdir, "latest_policy_usage_summary.json")
            self.assertTrue(os.path.exists(summary_path))

    def test_csv_export_includes_execution_detail_files(self):
        gen = PolicyUsageGenerator(MagicMock(), api_client=None)
        result = PolicyUsageResult(
            module_results={
                "mod00": {"kpis": [], "execution_notes": []},
                "mod02": {"hit_df": None},
                "mod03": {"unused_df": None},
            },
            execution_stats={
                "top_hit_ports": [{"port_proto": "443/tcp", "flow_count": 12}],
                "hit_rule_port_details": [{"rule_href": "/rules/1", "top_hit_ports": "443/tcp (12)"}],
                "reused_rule_details": [{"rule_href": "/rules/1", "status": "reused"}],
                "pending_rule_details": [{"rule_href": "/rules/2", "status": "pending"}],
                "failed_rule_details": [{"rule_href": "/rules/3", "status": "failed"}],
            },
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            paths = gen.export(result, fmt="csv", output_dir=tmpdir)

            self.assertEqual(len(paths), 1)
            with zipfile.ZipFile(paths[0], "r") as zf:
                names = set(zf.namelist())

        self.assertIn("execution_reused_rules.csv", names)
        self.assertIn("execution_pending_rules.csv", names)
        self.assertIn("execution_failed_rules.csv", names)
        self.assertIn("hit_rule_port_details.csv", names)

    def test_generate_from_csv_surfaces_top_hit_ports(self):
        gen = PolicyUsageGenerator(MagicMock(), api_client=None)
        csv_text = "\n".join([
            "ruleset_name,ruleset_href,rule_href,rule_description,rule_enabled,flows,flows_by_port,src_labels,dst_labels,services",
            'RS-1,/orgs/1/sec_policy/draft/rule_sets/1,/orgs/1/sec_policy/draft/rule_sets/1/sec_rules/1,Rule A,true,12,"443 TCP (10); 8443 TCP (2)",src:app,dst:db,HTTPS',
            'RS-1,/orgs/1/sec_policy/draft/rule_sets/1,/orgs/1/sec_policy/draft/rule_sets/1/sec_rules/2,Rule B,true,0,"",src:app,dst:db,SSH',
        ])

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "rule_usage.csv")
            with open(csv_path, "w", encoding="utf-8") as fh:
                fh.write(csv_text)
            result = gen.generate_from_csv(csv_path)

        mod02 = result.module_results["mod02"]
        mod03 = result.module_results["mod03"]
        self.assertIn("Top Hit Ports", mod02["hit_df"].columns)
        self.assertEqual(mod02["hit_df"].iloc[0]["Top Hit Ports"], "443/tcp (10); 8443/tcp (2)")
        self.assertEqual(mod02["top_ports_df"].iloc[0]["Port / Proto"], "443/tcp")
        self.assertEqual(mod02["top_ports_df"].iloc[0]["Flow Count"], 10)
        self.assertIn("Observed Hit Ports", mod03["unused_df"].columns)
        self.assertEqual(mod03["unused_df"].iloc[0]["Observed Hit Ports"], "None in lookback")


if __name__ == "__main__":
    unittest.main()
