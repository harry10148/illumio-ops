"""
Phase 9 Task 4 (Q1): Tests for the four private methods extracted from
Analyzer.run_analysis().

Covered methods:
  - _fetch_traffic(self) -> tuple
  - _run_event_analysis(self) -> list
  - _run_rule_engine(self, traffic_stream, tr_rules, now_utc) -> list
  - _dispatch_alerts(self, triggers, tr_rules) -> None
"""
import datetime
import unittest
from unittest.mock import MagicMock, patch, call

from src.analyzer import Analyzer
from src.events.poller import EventBatch


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_analyzer(rules=None):
    """Build an Analyzer with minimal mocks; no state file I/O."""
    mock_cm = MagicMock()
    mock_cm.config = {"rules": rules or []}
    mock_api = MagicMock()
    mock_rep = MagicMock()
    analyzer = Analyzer(mock_cm, mock_api, mock_rep)
    # Patch out load_state / save_state so tests are side-effect-free
    analyzer.load_state = MagicMock()
    analyzer.save_state = MagicMock()
    return analyzer


def _make_event_batch(events=None, overflow_risk=False, watermark="2026-01-01T00:00:00Z"):
    """Build a minimal EventBatch for use in tests."""
    evts = events or []
    return EventBatch(
        events=evts,
        next_watermark=watermark,
        query_since="2026-01-01T00:00:00Z",
        query_until=watermark,
        raw_count=len(evts),
        overflow_risk=overflow_risk,
        seen_events={},
    )


def _traffic_rule(rule_id="r1", rtype="traffic", threshold=1, window=10):
    return {
        "id": rule_id,
        "name": f"Rule {rule_id}",
        "type": rtype,
        "threshold_type": "count",
        "threshold_count": threshold,
        "threshold_window": window,
        "pd": -1,
    }


def _flow(num_connections=5, pd="blocked", timestamp_offset_secs=30):
    """Return a minimal traffic flow dict."""
    now = datetime.datetime.now(datetime.timezone.utc)
    ts = (now - datetime.timedelta(seconds=timestamp_offset_secs)).strftime('%Y-%m-%dT%H:%M:%SZ')
    return {
        "timestamp": ts,
        "policy_decision": pd,
        "num_connections": num_connections,
        "pd": 2 if pd == "blocked" else 0,
        "src": {},
        "dst": {},
        "service": {},
    }


# ─── _fetch_traffic ────────────────────────────────────────────────────────────

class TestFetchTraffic(unittest.TestCase):
    def test_returns_none_stream_when_no_traffic_rules(self):
        """_fetch_traffic returns (None, [], now) when there are no traffic rules."""
        rules = [{"id": "ev1", "type": "event", "name": "E", "threshold_type": "count",
                  "threshold_count": 1, "threshold_window": 10}]
        az = _make_analyzer(rules)
        stream, tr_rules, now_utc = az._fetch_traffic()
        self.assertIsNone(stream)
        self.assertEqual(tr_rules, [])
        self.assertIsInstance(now_utc, datetime.datetime)

    def test_calls_api_with_correct_policy_decisions(self):
        """_fetch_traffic queries the full vendor policy_decision domain (incl. unknown)."""
        rule = _traffic_rule()
        az = _make_analyzer([rule])
        fake_stream = iter([_flow()])
        az.api.execute_traffic_query_stream.return_value = fake_stream

        stream, tr_rules, now_utc = az._fetch_traffic()

        az.api.execute_traffic_query_stream.assert_called_once()
        args = az.api.execute_traffic_query_stream.call_args[0]
        self.assertEqual(args[2], ["blocked", "potentially_blocked", "allowed", "unknown"])

    def test_returns_traffic_rules_in_tuple(self):
        """_fetch_traffic returns only traffic/bandwidth/volume rules."""
        rules = [
            _traffic_rule("r1", "traffic"),
            _traffic_rule("r2", "bandwidth"),
            _traffic_rule("r3", "volume"),
            {"id": "ev1", "type": "event", "name": "E", "threshold_type": "count",
             "threshold_count": 1, "threshold_window": 10},
        ]
        az = _make_analyzer(rules)
        az.api.execute_traffic_query_stream.return_value = iter([])
        _, tr_rules, _ = az._fetch_traffic()
        self.assertEqual(len(tr_rules), 3)
        types = {r["type"] for r in tr_rules}
        self.assertNotIn("event", types)

    def test_respects_max_window_for_start_time(self):
        """_fetch_traffic uses the largest threshold_window + 2 as the query window."""
        rules = [
            _traffic_rule("r1", window=5),
            _traffic_rule("r2", window=30),
        ]
        az = _make_analyzer(rules)
        az.api.execute_traffic_query_stream.return_value = iter([])

        before = datetime.datetime.now(datetime.timezone.utc)
        az._fetch_traffic()
        after = datetime.datetime.now(datetime.timezone.utc)

        args = az.api.execute_traffic_query_stream.call_args[0]
        start_str = args[0]
        start_dt = datetime.datetime.strptime(start_str, '%Y-%m-%dT%H:%M:%SZ').replace(
            tzinfo=datetime.timezone.utc)
        # start should be ~32 minutes ago (window=30 + 2)
        expected_min = before - datetime.timedelta(minutes=33)
        expected_max = after - datetime.timedelta(minutes=31)
        self.assertGreaterEqual(start_dt, expected_min)
        self.assertLessEqual(start_dt, expected_max)


# ─── _run_event_analysis ──────────────────────────────────────────────────────

class TestRunEventAnalysis(unittest.TestCase):
    def _make_event_rule(self, rule_id="ev1", threshold=1):
        return {
            "id": rule_id,
            "name": f"Event Rule {rule_id}",
            "type": "event",
            "threshold_type": "instant",
            "threshold_count": threshold,
            "threshold_window": 10,
            "filter_type": "any",
            "filter_value": "",
        }

    def test_returns_empty_list_when_no_events(self):
        """_run_event_analysis returns [] when the event batch is empty."""
        az = _make_analyzer([self._make_event_rule()])
        az._fetch_event_batch = MagicMock(return_value=_make_event_batch(events=[]))
        result = az._run_event_analysis()
        self.assertEqual(result, [])

    def test_returns_empty_list_when_no_event_rules(self):
        """_run_event_analysis returns [] when there are no event rules."""
        az = _make_analyzer([_traffic_rule()])
        raw_event = {"timestamp": "2026-01-01T00:00:00Z", "event_type": "user.login",
                     "severity": "info", "status": "success", "created_by": {}}
        az._fetch_event_batch = MagicMock(return_value=_make_event_batch(events=[raw_event]))
        result = az._run_event_analysis()
        self.assertEqual(result, [])

    def test_dispatches_event_alert_and_returns_trigger(self):
        """Triggered event rule fires reporter.add_event_alert and is returned in list."""
        rule = self._make_event_rule(threshold=1)
        az = _make_analyzer([rule])
        raw_event = {"timestamp": "2026-01-01T00:00:00Z", "event_type": "user.login",
                     "severity": "warning", "status": "success", "created_by": {}}
        az._fetch_event_batch = MagicMock(return_value=_make_event_batch(events=[raw_event]))

        # Patch matches_event_rule so the event always matches
        with patch("src.analyzer.matches_event_rule", return_value=True):
            result = az._run_event_analysis()

        az.reporter.add_event_alert.assert_called_once()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["rule"], rule["name"])

    def test_no_alert_when_below_threshold(self):
        """No alert is dispatched when match count is below threshold_count."""
        rule = self._make_event_rule(threshold=5)
        az = _make_analyzer([rule])
        raw_event = {"timestamp": "2026-01-01T00:00:00Z", "event_type": "user.login",
                     "severity": "info", "status": "success", "created_by": {}}
        az._fetch_event_batch = MagicMock(return_value=_make_event_batch(events=[raw_event]))

        with patch("src.analyzer.matches_event_rule", return_value=True):
            result = az._run_event_analysis()

        az.reporter.add_event_alert.assert_not_called()
        self.assertEqual(result, [])

    def test_polling_error_does_not_raise(self):
        """_run_event_analysis swallows API errors and returns empty list."""
        az = _make_analyzer([self._make_event_rule()])
        az._fetch_event_batch = MagicMock(side_effect=RuntimeError("PCE down"))
        result = az._run_event_analysis()
        self.assertEqual(result, [])


# ─── _run_rule_engine ─────────────────────────────────────────────────────────

class TestRunRuleEngine(unittest.TestCase):
    def test_empty_stream_returns_all_rules_with_zero_metrics(self):
        """With no flows, all rules appear in result with max_val=0 and no matches."""
        rules = [_traffic_rule("r1"), _traffic_rule("r2")]
        az = _make_analyzer(rules)
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        result = az._run_rule_engine(iter([]), rules, now_utc)
        self.assertEqual(len(result), 2)
        rule_ids = {rule["id"] for rule, res in result}
        self.assertEqual(rule_ids, {"r1", "r2"})
        for _, res in result:
            self.assertEqual(res["max_val"], 0.0)
            self.assertEqual(res["top_matches"], [])

    def test_matching_flow_increments_traffic_count(self):
        """A matching traffic flow increments the rule's max_val by num_connections."""
        rule = _traffic_rule("r1", "traffic", threshold=1)
        az = _make_analyzer([rule])
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        flows = [_flow(num_connections=3)]

        with patch.object(az, "check_flow_match", return_value=True):
            result = az._run_rule_engine(iter(flows), [rule], now_utc)

        self.assertEqual(len(result), 1)
        _, res = result[0]
        self.assertEqual(res["max_val"], 3.0)
        self.assertEqual(len(res["top_matches"]), 1)

    def test_non_matching_flow_excluded(self):
        """Flows that don't match check_flow_match are not accumulated."""
        rule = _traffic_rule("r1")
        az = _make_analyzer([rule])
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        flows = [_flow(num_connections=10)]

        with patch.object(az, "check_flow_match", return_value=False):
            result = az._run_rule_engine(iter(flows), [rule], now_utc)

        _, res = result[0]
        self.assertEqual(res["max_val"], 0.0)
        self.assertEqual(res["top_matches"], [])

    def test_bandwidth_rule_tracks_max_not_sum(self):
        """Bandwidth rules keep the maximum bw_val, not the running sum."""
        rule = _traffic_rule("r1", "bandwidth", threshold=0)
        az = _make_analyzer([rule])
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        # Two flows with different bandwidth values
        flow_low = {**_flow(), "dst_dbo": 1_000_000, "dst_dbi": 0, "ddms": 1000}
        flow_high = {**_flow(), "dst_dbo": 10_000_000, "dst_dbi": 0, "ddms": 1000}

        with patch.object(az, "check_flow_match", return_value=True):
            result = az._run_rule_engine(iter([flow_low, flow_high]), [rule], now_utc)

        _, res = result[0]
        # max_val should equal the higher bandwidth value
        bw_low, _, _, _ = az.calculate_mbps(flow_low)
        bw_high, _, _, _ = az.calculate_mbps(flow_high)
        self.assertAlmostEqual(res["max_val"], bw_high)
        self.assertGreater(res["max_val"], bw_low)

    def test_volume_rule_accumulates_sum(self):
        """Volume rules accumulate the total volume across all matching flows."""
        rule = _traffic_rule("r1", "volume", threshold=0)
        az = _make_analyzer([rule])
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        flow = {**_flow(), "dst_dbo": 1_048_576, "dst_dbi": 1_048_576}  # 2 MB each

        with patch.object(az, "check_flow_match", return_value=True):
            result = az._run_rule_engine(iter([flow, flow]), [rule], now_utc)

        _, res = result[0]
        vol_per_flow, _ = az.calculate_volume_mb(flow)
        self.assertAlmostEqual(res["max_val"], vol_per_flow * 2, places=4)

    def test_non_numeric_count_does_not_abort_cycle(self):
        """A single flow with a non-numeric num_connections must not raise — one
        malformed PCE/cache row cannot kill the monitor cycle. The bad count
        coerces to 0 so it simply contributes nothing."""
        rule = _traffic_rule("r1", "traffic", threshold=1)
        az = _make_analyzer([rule])
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        bad_flow = {**_flow(), "num_connections": "not-a-number"}

        with patch.object(az, "check_flow_match", return_value=True):
            result = az._run_rule_engine(iter([bad_flow]), [rule], now_utc)

        self.assertEqual(len(result), 1)
        _, res = result[0]
        self.assertEqual(res["max_val"], 0.0)

    def test_none_count_falls_back_without_crashing(self):
        """A None num_connections falls back to the count default (1) and the
        cycle continues normally."""
        rule = _traffic_rule("r1", "traffic", threshold=1)
        az = _make_analyzer([rule])
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        none_flow = {**_flow(), "num_connections": None}

        with patch.object(az, "check_flow_match", return_value=True):
            result = az._run_rule_engine(iter([none_flow]), [rule], now_utc)

        _, res = result[0]
        self.assertEqual(res["max_val"], 1.0)


# ─── _run_rule_engine: bounded top_matches accumulation (Task C6) ────────────

class TestRunRuleEngineBoundedTopN(unittest.TestCase):
    """Behavior lock: _run_rule_engine must not accumulate unbounded top_matches
    (O(flows) memory). The accumulated structure must stay bounded to the same
    N that _dispatch_alerts trims to (currently 10), and the resulting top-10
    set/order (after dispatch's own final sort) must be identical to the
    original 'accumulate everything, then stable-sort descending, slice[:10]'
    algorithm — including tie-break behavior at the rank-10/11 boundary.
    """

    def _volume_flow(self, mb: float, idx: int):
        return {**_flow(), "dst_dbo": int(mb * 1024 * 1024), "dst_dbi": 0, "id": idx}

    def test_accumulated_structure_stays_bounded_to_dispatch_limit(self):
        """White-box bound: len(top_matches) after the engine run must never
        exceed the dispatch-side top-N (10), even with far more matching flows."""
        rule = _traffic_rule("r1", "volume", threshold=0)
        az = _make_analyzer([rule])
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        flows = [self._volume_flow(mb=float(i), idx=i) for i in range(37)]

        with patch.object(az, "check_flow_match", return_value=True):
            result = az._run_rule_engine(iter(flows), [rule], now_utc)

        _, res = result[0]
        self.assertLessEqual(len(res["top_matches"]), 10)

    def test_bounded_top_matches_equals_golden_full_sort_with_boundary_ties(self):
        """Golden-oracle equivalence: with >10 matches including a 3-way tie
        straddling the rank-10/11 cutoff, the bounded accumulation must select
        the exact same top-10 set/order as full-accumulate + stable sort.

        Flow layout (15 flows):
          idx 0..8  -> unique volumes 15,14,...,7 MB   (9 flows, all in top 10)
          idx 9..11 -> tied volume 6 MB                (3-way tie for the 10th slot)
          idx 12..14 -> volumes 3,2,1 MB                (below cutoff, excluded)
        Original algorithm (stable sort desc by metric, ties keep append order)
        picks idx 9 (earliest of the tie) for the 10th slot, dropping idx 10/11.
        """
        rule = _traffic_rule("r1", "volume", threshold=0)
        az = _make_analyzer([rule])
        now_utc = datetime.datetime.now(datetime.timezone.utc)

        flows = []
        for i in range(9):
            flows.append(self._volume_flow(mb=float(15 - i), idx=i))  # 15..7
        for i in range(9, 12):
            flows.append(self._volume_flow(mb=6.0, idx=i))            # tie at 6
        for i, mb in zip(range(12, 15), (3.0, 2.0, 1.0)):
            flows.append(self._volume_flow(mb=mb, idx=i))             # below cutoff

        with patch.object(az, "check_flow_match", return_value=True):
            result = az._run_rule_engine(iter(flows), [rule], now_utc)

        _, res = result[0]
        self.assertLessEqual(len(res["top_matches"]), 10)

        # Golden oracle: replicate the ORIGINAL unbounded algorithm inline.
        all_matches = []
        for f in flows:
            vol_val, _ = az.calculate_volume_mb(f)
            fc = dict(f)
            fc["_metric_val"] = vol_val
            all_matches.append(fc)
        all_matches.sort(key=lambda x: x.get("_metric_val", 0), reverse=True)
        golden_top10_ids = [m["id"] for m in all_matches[:10]]

        # Dispatch performs its own final stable sort on whatever top_matches
        # it receives; simulate that step here to compare final dispatch order.
        dispatch_sorted = sorted(
            res["top_matches"], key=lambda x: x.get("_metric_val", 0), reverse=True
        )
        self.assertEqual([m["id"] for m in dispatch_sorted], golden_top10_ids)
        self.assertEqual(golden_top10_ids[:9], list(range(9)))
        self.assertEqual(golden_top10_ids[9], 9)  # earliest of the 3-way tie wins


# ─── _dispatch_alerts ─────────────────────────────────────────────────────────

class TestDispatchAlerts(unittest.TestCase):
    def test_no_alert_when_triggers_empty(self):
        """_dispatch_alerts does nothing when given an empty trigger list."""
        az = _make_analyzer()
        az._dispatch_alerts([], [])
        az.reporter.add_traffic_alert.assert_not_called()
        az.reporter.add_metric_alert.assert_not_called()

    def test_traffic_alert_fires_when_threshold_met(self):
        """Traffic rule meeting threshold fires reporter.add_traffic_alert."""
        rule = _traffic_rule("r1", "traffic", threshold=2)
        az = _make_analyzer([rule])
        # Inject a result that exceeds threshold
        res = {"max_val": 5.0, "top_matches": [_flow(num_connections=5)]}
        triggers = [(rule, res)]

        with patch.object(az, "_check_cooldown", return_value=True):
            az._dispatch_alerts(triggers, [rule])

        az.reporter.add_traffic_alert.assert_called_once()
        az.reporter.add_metric_alert.assert_not_called()

    def test_bandwidth_alert_fires_when_matches_exist(self):
        """Bandwidth rule fires reporter.add_metric_alert when top_matches is non-empty."""
        rule = _traffic_rule("r1", "bandwidth", threshold=0)
        az = _make_analyzer([rule])
        res = {"max_val": 100.0, "top_matches": [_flow()]}
        triggers = [(rule, res)]

        with patch.object(az, "_check_cooldown", return_value=True):
            az._dispatch_alerts(triggers, [rule])

        az.reporter.add_metric_alert.assert_called_once()
        az.reporter.add_traffic_alert.assert_not_called()

    def test_volume_alert_fires_add_metric_alert(self):
        """Volume rule fires reporter.add_metric_alert (not add_traffic_alert)."""
        rule = _traffic_rule("r1", "volume", threshold=1)
        az = _make_analyzer([rule])
        res = {"max_val": 50.0, "top_matches": [_flow()]}
        triggers = [(rule, res)]

        with patch.object(az, "_check_cooldown", return_value=True):
            az._dispatch_alerts(triggers, [rule])

        az.reporter.add_metric_alert.assert_called_once()

    def test_no_alert_when_below_threshold(self):
        """_dispatch_alerts does not fire when value is below threshold."""
        rule = _traffic_rule("r1", "traffic", threshold=10)
        az = _make_analyzer([rule])
        res = {"max_val": 3.0, "top_matches": [_flow(num_connections=3)]}
        triggers = [(rule, res)]

        with patch.object(az, "_check_cooldown", return_value=True):
            az._dispatch_alerts(triggers, [rule])

        az.reporter.add_traffic_alert.assert_not_called()

    def test_cooldown_suppresses_alert(self):
        """_dispatch_alerts respects _check_cooldown returning False."""
        rule = _traffic_rule("r1", "traffic", threshold=1)
        az = _make_analyzer([rule])
        res = {"max_val": 5.0, "top_matches": [_flow()]}
        triggers = [(rule, res)]

        with patch.object(az, "_check_cooldown", return_value=False):
            az._dispatch_alerts(triggers, [rule])

        az.reporter.add_traffic_alert.assert_not_called()

    def test_multiple_rules_dispatched_independently(self):
        """Multiple trigger entries are each evaluated independently."""
        r_traffic = _traffic_rule("r1", "traffic", threshold=1)
        r_bw = _traffic_rule("r2", "bandwidth", threshold=0)
        az = _make_analyzer([r_traffic, r_bw])
        triggers = [
            (r_traffic, {"max_val": 5.0, "top_matches": [_flow()]}),
            (r_bw, {"max_val": 10.0, "top_matches": [_flow()]}),
        ]

        with patch.object(az, "_check_cooldown", return_value=True):
            az._dispatch_alerts(triggers, [r_traffic, r_bw])

        az.reporter.add_traffic_alert.assert_called_once()
        az.reporter.add_metric_alert.assert_called_once()


# ─── Integration: run_analysis orchestrates the 4 methods ─────────────────────

class TestRunAnalysisOrchestration(unittest.TestCase):
    """Verify that run_analysis() delegates to the four extracted methods."""

    def setUp(self):
        self.az = _make_analyzer(rules=[])
        self.az._run_event_analysis = MagicMock(return_value=[])
        self.az._fetch_traffic = MagicMock(return_value=(None, [], datetime.datetime.now(datetime.timezone.utc)))
        self.az._run_rule_engine = MagicMock(return_value=[])
        self.az._dispatch_alerts = MagicMock()
        self.az.save_state = MagicMock()

    def test_run_analysis_calls_event_pipeline(self):
        self.az.run_analysis()
        self.az._run_event_analysis.assert_called_once()

    def test_run_analysis_calls_fetch_traffic(self):
        self.az.run_analysis()
        self.az._fetch_traffic.assert_called_once()

    def test_run_analysis_skips_rule_engine_when_stream_is_none(self):
        """_run_rule_engine is NOT called when _fetch_traffic returns None stream."""
        self.az.run_analysis()
        self.az._run_rule_engine.assert_not_called()

    def test_run_analysis_calls_rule_engine_when_stream_available(self):
        """_run_rule_engine IS called when _fetch_traffic returns a non-None stream."""
        fake_stream = iter([])
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        self.az._fetch_traffic.return_value = (fake_stream, [_traffic_rule()], now_utc)
        self.az.run_analysis()
        self.az._run_rule_engine.assert_called_once()

    def test_run_analysis_calls_dispatch_alerts(self):
        self.az.run_analysis()
        self.az._dispatch_alerts.assert_called_once()

    def test_run_analysis_calls_save_state(self):
        self.az.run_analysis()
        self.az.save_state.assert_called_once()


if __name__ == "__main__":
    unittest.main()
