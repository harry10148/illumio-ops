import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock

from src.report.report_generator import ReportGenerator, ReportResult


class TestReportGeneratorRawCsvExport(unittest.TestCase):
    def test_export_raw_csv_writes_file_and_metadata(self):
        mock_cm = MagicMock()
        mock_cm.config = {"settings": {}}
        mock_api = MagicMock()
        raw_csv_path = os.path.join(tempfile.gettempdir(), "Illumio_Traffic_Explorer_Raw_test.csv")
        mock_api.export_traffic_query_csv.return_value = {
            "path": raw_csv_path,
            "row_count": 42,
            "job_href": "/orgs/1/traffic_flows/async_queries/77",
            "query_diagnostics": {"native_filters": {"src_label": "role:web"}},
            "policy_decisions": ["blocked"],
            "filters": {"src_label": "role:web"},
            "compute_draft": False,
        }

        gen = ReportGenerator(mock_cm, api_client=mock_api)
        result = ReportResult(
            data_source="api",
            date_range=("2026-04-01", "2026-04-02"),
            query_context={
                "start_date": "2026-04-01T00:00:00Z",
                "end_date": "2026-04-02T23:59:59Z",
                "filters": {"src_label": "role:web"},
                "policy_decisions": ["blocked"],
            },
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            raw_csv_path = os.path.join(tmpdir, "Illumio_Traffic_Explorer_Raw_test.csv")
            mock_api.export_traffic_query_csv.return_value["path"] = raw_csv_path
            with open(raw_csv_path, "w", encoding="utf-8") as fh:
                fh.write("Source IP,Destination IP\n10.0.0.1,10.0.0.2\n")

            paths = gen.export(result, fmt="raw_csv", output_dir=tmpdir)

            self.assertEqual(paths, [raw_csv_path])
            meta_path = raw_csv_path + ".metadata.json"
            self.assertTrue(os.path.exists(meta_path))
            with open(meta_path, "r", encoding="utf-8") as fh:
                metadata = json.load(fh)

        self.assertEqual(metadata["report_type"], "traffic_raw_csv")
        self.assertEqual(metadata["file_format"], "raw_csv")
        self.assertEqual(metadata["record_count"], 42)
        self.assertEqual(metadata["job_href"], "/orgs/1/traffic_flows/async_queries/77")
        self.assertEqual(metadata["filters"]["src_label"], "role:web")

    def test_build_report_metadata_contains_attack_summary(self):
        mock_cm = MagicMock()
        mock_cm.config = {"settings": {}}
        gen = ReportGenerator(mock_cm, api_client=MagicMock())

        result = ReportResult(
            record_count=15,
            date_range=("2026-04-01", "2026-04-02"),
            module_results={
                "mod12": {
                    "kpis": [{"label": "Total Flows", "value": "15"}],
                    "boundary_breaches": [{"finding": "Cross-boundary traffic observed", "action": "Restrict east-west access"}],
                    "suspicious_pivot_behavior": [{"finding": "Pivot chain detected", "action": "Investigate source app"}],
                    "blast_radius": [],
                    "blind_spots": [],
                    "action_matrix": [{"action": "Enable enforcement", "priority": 100}],
                }
            },
        )

        metadata = gen._build_report_metadata(result, file_format="html")

        self.assertEqual(metadata["report_type"], "traffic")
        self.assertEqual(metadata["file_format"], "html")
        self.assertEqual(metadata["record_count"], 15)
        self.assertIn("attack_summary", metadata)
        self.assertIn("boundary_breaches", metadata["attack_summary"])
        self.assertIn("action_matrix", metadata["attack_summary"])
        self.assertEqual(metadata["attack_summary_counts"]["boundary_breaches"], 1)


if __name__ == "__main__":
    unittest.main()
