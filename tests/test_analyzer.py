import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock
from src.analyzer import Analyzer, BOUND_BASIS_NOTE
from src.api_client import TrafficQuerySpec
from src.config import ConfigManager

class TestAnalyzer(unittest.TestCase):
    def setUp(self):
        self.mock_cm = MagicMock()
        self.mock_api = MagicMock()
        # Task 2 (deferred minors hardening): query_flows raises TrafficQueryError
        # when last_fetch_error is truthy after an api/mixed fetch; a bare
        # MagicMock attribute is truthy, so pin the real default (None).
        self.mock_api.last_fetch_error = None
        self.mock_rep = MagicMock()
        self.analyzer = Analyzer(self.mock_cm, self.mock_api, self.mock_rep)

    def test_calculate_mbps_interval(self):
        flow = {"dst_dbo": 1000000, "dst_dbi": 1000000, "ddms": 1000}
        val, note, _, _ = self.analyzer.calculate_mbps(flow)
        self.assertAlmostEqual(val, 16.0)
        self.assertEqual(note, "(Interval)")

    def test_calculate_mbps_fallback(self):
        # No tdms and no usable timestamps → unavailable. `interval_sec` is a
        # leftover PCE syslog/fluentd field the async query this tool uses
        # never sends; it must not be read as a fallback denominator anymore.
        flow = {"dst_dbo": 0, "dst_tbo": 500000, "dst_tbi": 500000, "interval_sec": 1}
        val, note, _, _ = self.analyzer.calculate_mbps(flow)
        self.assertIsNone(val)
        self.assertEqual(note, "")

    def test_calculate_mbps_bound_from_timestamp_span(self):
        """No ddms/tdms: fall back to bytes / (span+1) as a provable lower
        bound. 12.05 TB over ~2.5 days (214848s) is ~493 Mbps — not the
        176,640 Mbps the old 600s-assumed-interval code reported."""
        flow = {
            "dst_tbo": 13248009806581,
            "dst_tbi": 0,
            "timestamp_range": {
                "first_detected": "2026-07-01T00:00:00Z",
                "last_detected": "2026-07-03T11:40:48Z",
            },
        }
        val, note, byts, _ = self.analyzer.calculate_mbps(flow)
        span_seconds = 214848  # 2026-07-01T00:00:00Z .. 2026-07-03T11:40:48Z
        expected = (13248009806581 * 8.0) / (span_seconds + 1) / 1_000_000.0
        self.assertAlmostEqual(val, expected)
        self.assertAlmostEqual(val, 493.3, places=1)
        self.assertNotAlmostEqual(val, 176640.13, places=0)
        self.assertEqual(note, BOUND_BASIS_NOTE)
        self.assertAlmostEqual(byts, 13248009806581)

    def test_calculate_mbps_bound_zero_span_uses_one_second_denom(self):
        """first_detected == last_detected → span is 0s, but timestamps are
        only second-resolution, so the true duration could still be up to
        ~1s either side. span+1 is the same formula as any other span, not
        a special-cased divide-by-zero guard."""
        flow = {
            "dst_tbo": 1_000_000,
            "first_detected": "2026-07-01T00:00:00Z",
            "last_detected": "2026-07-01T00:00:00Z",
        }
        val, note, _, _ = self.analyzer.calculate_mbps(flow)
        self.assertAlmostEqual(val, (1_000_000 * 8.0) / 1.0 / 1_000_000.0)
        self.assertEqual(note, BOUND_BASIS_NOTE)

    def test_calculate_mbps_zero_bytes_is_unavailable(self):
        flow = {
            "timestamp_range": {
                "first_detected": "2026-07-01T00:00:00Z",
                "last_detected": "2026-07-01T01:00:00Z",
            },
        }
        val, note, _, _ = self.analyzer.calculate_mbps(flow)
        self.assertIsNone(val)
        self.assertEqual(note, "")

    def test_calculate_mbps_missing_timestamps_is_unavailable(self):
        flow = {"dst_tbo": 500000, "dst_tbi": 500000}
        val, note, _, _ = self.analyzer.calculate_mbps(flow)
        self.assertIsNone(val)
        self.assertEqual(note, "")

    def test_calculate_mbps_unparsable_timestamps_is_unavailable(self):
        flow = {
            "dst_tbo": 500000,
            "timestamp_range": {"first_detected": "not-a-timestamp",
                                 "last_detected": "also-not-a-timestamp"},
        }
        val, note, _, _ = self.analyzer.calculate_mbps(flow)
        self.assertIsNone(val)
        self.assertEqual(note, "")

    def test_calculate_mbps_reversed_timestamps_is_unavailable_not_a_crash(self):
        """last_detected before first_detected is corrupt data (or a
        1-second-resolution rounding edge), not evidence of a negative
        duration. Must not raise (ZeroDivisionError/negative rate) out of
        the per-flow hot loop -- same no-crash contract as malformed bytes."""
        flow = {
            "dst_tbo": 1000,
            "first_detected": "2026-07-01T00:00:01Z",
            "last_detected": "2026-07-01T00:00:00Z",
        }
        val, note, _, _ = self.analyzer.calculate_mbps(flow)
        self.assertIsNone(val)
        self.assertEqual(note, "")

    def test_calculate_mbps_nonfinite_bound_value_is_unavailable_not_a_bound(self):
        """A byte field arriving as the literal string "nan" makes _safe_float
        produce NaN. NaN compares False in both directions, so `total_bytes <= 0`
        never catches it and (pre-fix) the Priority-3 branch computed
        val=NaN and still attached BOUND_BASIS_NOTE -- "at least NaN Mbps",
        a bound claim with no content. A non-finite value is not a lower
        bound of anything; must fall through to the unavailable state, same
        as zero bytes or missing timestamps (Task 3 fix round 1)."""
        flow = {
            "dst_tbo": "nan",
            "dst_tbi": 0,
            "timestamp_range": {
                "first_detected": "2026-07-01T00:00:00Z",
                "last_detected": "2026-07-01T01:00:00Z",
            },
        }
        val, note, _, _ = self.analyzer.calculate_mbps(flow)
        self.assertIsNone(val)
        self.assertEqual(note, "")

    def test_calculate_mbps_no_longer_assumes_a_sampling_interval(self):
        """600 秒是 PCE interval_sec 的文件預設值，但該欄位不在 async query 的回傳裡，
        所以它曾是唯一會用到的分母。任何一個重新出現都代表假分母回來了。"""
        import inspect, re
        from src import analyzer
        src = inspect.getsource(analyzer.calculate_mbps)
        banned = {"interval_sec", "600"}
        found = {b for b in banned if re.search(r"\b%s\b" % re.escape(b), src)}
        assert found == set(), f"assumed-denominator tokens are back: {found}"

    def test_calculate_mbps_uses_real_tdms(self):
        """A real tdms is a measured duration → basis is '(Avg)'."""
        flow = {"dst_tbo": 500000, "dst_tbi": 500000, "tdms": 1000}
        val, note, _, tdms = self.analyzer.calculate_mbps(flow)
        self.assertAlmostEqual(val, 8.0)
        self.assertEqual(note, "(Avg)")
        self.assertEqual(tdms, 1000)

    def test_calculate_mbps_subsecond_tdms_is_clamped_not_replaced(self):
        """A genuine sub-second duration must be clamped up to 1000 ms (as the
        delta branch does), never swapped for the 600 s sampling-interval
        default — that under-reported a real 80 Mbps burst as 0.07 Mbps."""
        flow = {"dst_tbo": 5_000_000, "tdms": 500}
        val, note, _, tdms = self.analyzer.calculate_mbps(flow)
        self.assertEqual(tdms, 1000.0)
        self.assertAlmostEqual(val, 40.0)
        self.assertEqual(note, "(Avg)")

    def test_calculate_metrics_tolerate_malformed_byte_fields(self):
        """A non-numeric byte field must not raise out of the per-flow hot loop
        (it would abort the whole monitor cycle)."""
        flow = {"dst_tbo": "1,234", "dst_tbi": None, "tdms": "abc"}
        val, _note, _, _ = self.analyzer.calculate_mbps(flow)
        self.assertIsNone(val)
        # Task final-review Finding 2: an unparsable byte field yields no
        # real byte count, same as an absent one -- unavailable, not a
        # measured zero.
        vol, vol_note = self.analyzer.calculate_volume_mb(flow)
        self.assertIsNone(vol)
        self.assertEqual(vol_note, "")


    def test_calculate_volume_mb(self):
        flow = {"dst_dbo": 1048576, "dst_dbi": 1048576} # 2 MB total
        val, note = self.analyzer.calculate_volume_mb(flow)
        self.assertAlmostEqual(val, 2.0)
        self.assertEqual(note, "(Interval)")

        flow_total = {"dst_tbo": 2097152, "dst_tbi": 0} # 2 MB total
        val_total, note_total = self.analyzer.calculate_volume_mb(flow_total)
        self.assertAlmostEqual(val_total, 2.0)
        self.assertEqual(note_total, "(Total)")

    def test_calculate_volume_mb_zero_bytes_is_unavailable(self):
        """Appendix C.3(2): a flow with no byte counters must not report
        0.0 MB -- that reads as "measured zero bytes" when nothing was
        measured at all. Async query never omits dst_bi/dst_bo (always
        sends 0), so a true zero and an unmeasured flow are indistinguishable
        -- same reasoning as calculate_mbps's own zero-bytes guard."""
        val, note = self.analyzer.calculate_volume_mb({})
        self.assertIsNone(val)
        self.assertEqual(note, "")

    def test_calculate_volume_mb_nonfinite_value_is_unavailable_not_a_measured_zero(self):
        """A byte field arriving as the literal string "nan" makes
        _safe_float produce NaN. NaN compares False in both directions, so
        `total_bytes <= 0` alone would not catch it and the function would
        return (nan, "(Total)") -- "nan MB (Total)" downstream. Must fall
        through to unavailable, mirroring calculate_mbps's own isfinite
        guard (Task 2 fix round 1)."""
        flow = {"dst_tbo": "nan", "dst_tbi": 0}
        val, note = self.analyzer.calculate_volume_mb(flow)
        self.assertIsNone(val)
        self.assertEqual(note, "")

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

    def test_query_flows_sort_is_none_safe_for_unavailable_bandwidth(self):
        """A flow with no ddms/tdms/bytes has bw_val=None (Task 1 contract).
        Sorting query_flows results by bandwidth must not raise TypeError
        from comparing None to a float, and the unavailable flow must sort
        last -- not get silently conflated with a real zero-Mbps flow."""
        self.mock_api.build_traffic_query_spec.side_effect = lambda filters: TrafficQuerySpec(
            raw_filters=dict(filters),
            native_filters={},
            fallback_filters={},
            report_only_filters={},
        )
        measured_flow = {
            "src": {"ip": "10.0.0.1", "workload": {}},
            "dst": {"ip": "10.0.0.2", "workload": {}},
            "service": {"port": 443, "proto": 6},
            "policy_decision": "allowed",
            "num_connections": 1,
            "dst_dbo": 1_000_000, "dst_dbi": 0, "ddms": 1000,
            "timestamp_range": {"first_detected": "2026-07-01T00:00:00Z",
                                 "last_detected": "2026-07-01T00:00:01Z"},
        }
        unavailable_flow = {
            "src": {"ip": "10.0.0.3", "workload": {}},
            "dst": {"ip": "10.0.0.4", "workload": {}},
            "service": {"port": 443, "proto": 6},
            "policy_decision": "allowed",
            "num_connections": 1,
            # no byte fields at all -> calculate_mbps returns val=None
            "timestamp_range": {"first_detected": "2026-07-01T00:00:00Z",
                                 "last_detected": "2026-07-01T00:00:01Z"},
        }
        self.mock_api.execute_traffic_query_stream.return_value = iter(
            [unavailable_flow, measured_flow])

        out = self.analyzer.query_flows({
            "start_time": "2026-07-01T00:00:00Z",
            "end_time": "2026-07-01T01:00:00Z",
        })

        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]['_metric_val'], 8.0)
        self.assertIsNone(out[-1]['_metric_val'])

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
