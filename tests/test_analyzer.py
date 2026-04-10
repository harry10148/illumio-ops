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

if __name__ == '__main__':
    unittest.main()
