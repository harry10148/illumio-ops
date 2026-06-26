import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock
from src.analyzer import Analyzer
from src.api_client import TrafficQuerySpec
from src.config import ConfigManager

class TestAnalyzer(unittest.TestCase):
    def setUp(self):
        self.mock_cm = MagicMock()
        self.mock_api = MagicMock()
        self.mock_rep = MagicMock()
        self.analyzer = Analyzer(self.mock_cm, self.mock_api, self.mock_rep)

    def test_calculate_mbps_interval(self):
        flow = {"dst_dbo": 1000000, "dst_dbi": 1000000, "ddms": 1000}
        val, note, _, _ = self.analyzer.calculate_mbps(flow)
        self.assertAlmostEqual(val, 16.0)
        self.assertEqual(note, "(Interval)")

    def test_calculate_mbps_fallback(self):
        flow = {"dst_dbo": 0, "dst_tbo": 500000, "dst_tbi": 500000, "interval_sec": 1}
        val, note, _, _ = self.analyzer.calculate_mbps(flow)
        self.assertAlmostEqual(val, 8.0)
        self.assertEqual(note, "(Avg)")
        
    def test_calculate_volume_mb(self):
        flow = {"dst_dbo": 1048576, "dst_dbi": 1048576} # 2 MB total
        val, note = self.analyzer.calculate_volume_mb(flow)
        self.assertAlmostEqual(val, 2.0)
        self.assertEqual(note, "(Interval)")
        
        flow_total = {"dst_tbo": 2097152, "dst_tbi": 0} # 2 MB total
        val_total, note_total = self.analyzer.calculate_volume_mb(flow_total)
        self.assertAlmostEqual(val_total, 2.0)
        self.assertEqual(note_total, "(Total)")

    def test_sliding_window_filter(self):
        rule = {"type": "traffic", "threshold_window": 10, "pd": -1, "name": "test rule"}
        
        now = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        start_limit = now - timedelta(minutes=10)
        
        # In window
        f_in = {"timestamp": "2023-01-01T11:55:00Z", "pd": 2}
        self.assertTrue(self.analyzer.check_flow_match(rule, f_in, start_limit))
        
        # Out of window
        f_out = {"timestamp": "2023-01-01T11:45:00Z", "pd": 2}
        self.assertFalse(self.analyzer.check_flow_match(rule, f_out, start_limit))

    def test_check_flow_match_filters(self):
        rule = {"type": "traffic", "port": 443, "pd": 2, "name": "test rule"}
        f_match = {"timestamp": "2023-01-01T12:00:00Z", "dst_port": 443, "pd": 2}
        self.assertTrue(self.analyzer.check_flow_match(rule, f_match, None))
        
        f_mismatch = {"timestamp": "2023-01-01T12:00:00Z", "dst_port": 80, "pd": 2}
        self.assertFalse(self.analyzer.check_flow_match(rule, f_mismatch, None))

    def test_cooldown_logic(self):
        rule = {'id': 'rule1', 'name': 'Rule 1', 'cooldown_minutes': 10}
        now = datetime.now(timezone.utc)
        
        self.assertTrue(self.analyzer._check_cooldown(rule))
        
        self.analyzer.state['alert_history']['rule1'] = now.strftime('%Y-%m-%dT%H:%M:%SZ')
        self.assertFalse(self.analyzer._check_cooldown(rule))
        
        past = now - timedelta(minutes=15)
        self.analyzer.state['alert_history']['rule1'] = past.strftime('%Y-%m-%dT%H:%M:%SZ')
        self.assertTrue(self.analyzer._check_cooldown(rule))

    def test_query_flows_passes_filters_to_api_layer(self):
        self.mock_api.execute_traffic_query_stream.return_value = iter([])
        self.mock_api.build_traffic_query_spec.side_effect = lambda filters: TrafficQuerySpec(
            raw_filters=dict(filters),
            native_filters={"src_label": filters.get("src_label"), "dst_ip_in": filters.get("dst_ip_in"), "port": filters.get("port")},
            fallback_filters={},
            report_only_filters={},
        )

        self.analyzer.query_flows({
            "start_time": "2026-04-01T00:00:00Z",
            "end_time": "2026-04-01T00:30:00Z",
            "src_label": "role:web",
            "dst_ip_in": "10.0.0.5",
            "port": 443,
        })

        _, kwargs = self.mock_api.execute_traffic_query_stream.call_args
        self.assertIsInstance(kwargs["filters"], TrafficQuerySpec)
        self.assertEqual(kwargs["filters"].native_filters["src_label"], "role:web")
        self.assertEqual(kwargs["filters"].native_filters["dst_ip_in"], "10.0.0.5")
        self.assertEqual(kwargs["filters"].native_filters["port"], 443)

    def test_check_flow_match_non_numeric_pd_does_not_raise(self):
        """A malformed (non-numeric) 'pd' field must not raise; the matcher
        degrades gracefully instead of aborting the monitor cycle."""
        rule = {"type": "traffic", "pd": -1, "name": "test rule"}
        f = {"timestamp": "2023-01-01T12:00:00Z", "pd": "not-a-number"}
        # pd filter is disabled (-1), so the flow still matches.
        self.assertTrue(self.analyzer.check_flow_match(rule, f, None))

    def test_check_flow_match_empty_pd_does_not_raise(self):
        """An empty-string 'pd' must not raise; it is treated as unknown (-1)
        and excluded from a pd-specific rule rather than crashing."""
        rule = {"type": "traffic", "pd": 2, "name": "test rule"}
        f = {"timestamp": "2023-01-01T12:00:00Z", "pd": ""}
        self.assertFalse(self.analyzer.check_flow_match(rule, f, None))

    def test_build_criteria_str_traffic_uses_ge(self):
        """Traffic/volume rules fire at '>=' threshold, so the criteria text
        must advertise '>=' (matches _dispatch_alerts)."""
        rule = {"type": "traffic", "threshold_count": 5}
        self.assertEqual(self.analyzer._build_criteria_str(rule), "Threshold: >= 5")

    def test_build_criteria_str_bandwidth_uses_gt(self):
        """Bandwidth rules fire at a strict '>' threshold."""
        rule = {"type": "bandwidth", "threshold_count": 5}
        self.assertEqual(self.analyzer._build_criteria_str(rule), "Threshold: > 5")

    def test_event_count_in_window_counts_each_record_once(self):
        """Each history record represents exactly one event (no 'c' compression)."""
        rid = "rule1"
        now = datetime.now(timezone.utc)
        recent = now.strftime('%Y-%m-%dT%H:%M:%SZ')
        self.analyzer.state["history"] = {rid: [
            {"t": recent, "event_id": "e1"},
            {"t": recent, "event_id": "e2"},
            {"t": recent, "event_id": "e3"},
        ]}
        window_start = now - timedelta(minutes=10)
        self.assertEqual(self.analyzer._event_count_in_window(rid, window_start), 3)

if __name__ == '__main__':
    unittest.main()
