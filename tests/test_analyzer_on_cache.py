"""
Phase 15 Task 4: Tests for Analyzer cache-subscriber integration.

Covered invariants:
  1. _run_event_analysis() calls subscriber.poll_new_rows() when subscriber_events is set
  2. _run_event_analysis() falls back to legacy API path when subscriber_events is None
  3. _run_event_analysis() handles empty poll result without dispatching any alert
  4. _run_event_analysis() processes events from cache through the normalizer/matcher pipeline

Also covers _fetch_query_flows hybrid (partial) path:
  5. Empty API stream on hybrid → source='cache'
  6. API stream exception on hybrid → falls back to full API path → source='api'
"""
import datetime
import unittest
from unittest.mock import MagicMock, patch

from src.analyzer import Analyzer
from src.events.poller import EventBatch


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_analyzer(rules=None, subscriber_events=None, subscriber_flows=None):
    """Build an Analyzer with minimal mocks; no state file I/O."""
    mock_cm = MagicMock()
    mock_cm.config = {"rules": rules or []}
    mock_api = MagicMock()
    mock_rep = MagicMock()
    analyzer = Analyzer(
        mock_cm,
        mock_api,
        mock_rep,
        subscriber_events=subscriber_events,
        subscriber_flows=subscriber_flows,
    )
    analyzer.load_state = MagicMock()
    analyzer.save_state = MagicMock()
    return analyzer


def _make_cache_reader_for_flows(cover_state="partial", cache_start=None, flows=None):
    """Build a cache reader mock suitable for _fetch_query_flows tests."""
    cr = MagicMock()
    cr.cover_state.return_value = cover_state
    cr.earliest_data_timestamp.return_value = cache_start
    cr.read_flows_raw.return_value = flows or [{"policy_decision": "allowed"}]
    return cr


_START = "2026-01-01T00:00:00Z"
_END = "2026-01-08T00:00:00Z"
_CACHE_START = datetime.datetime(2026, 1, 4, tzinfo=datetime.timezone.utc)  # middle of window


def _event_rule(rule_id="ev1", threshold=1):
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


def _raw_event(event_type="user.login"):
    return {
        "timestamp": "2026-01-01T00:00:00Z",
        "event_type": event_type,
        "severity": "warning",
        "status": "success",
        "created_by": {},
    }


# ─── Tests ─────────────────────────────────────────────────────────────────────

class TestAnalyzerOnCache(unittest.TestCase):

    def test_analyzer_uses_subscriber_when_enabled(self):
        """When subscriber_events is set, _run_event_analysis calls poll_new_rows,
        not _fetch_event_batch (the legacy API path)."""
        mock_sub = MagicMock()
        mock_sub.poll_new_rows.return_value = []

        az = _make_analyzer(rules=[_event_rule()], subscriber_events=mock_sub)
        az._fetch_event_batch = MagicMock()

        az._run_event_analysis()

        mock_sub.poll_new_rows.assert_called_once()
        az._fetch_event_batch.assert_not_called()

    def test_analyzer_falls_back_to_api_when_subscriber_none(self):
        """When subscriber_events=None (default), _fetch_event_batch is called
        instead of any subscriber."""
        az = _make_analyzer(rules=[_event_rule()])
        az._fetch_event_batch = MagicMock(
            return_value=EventBatch(
                events=[],
                next_watermark="2026-01-01T00:00:00Z",
                query_since="2026-01-01T00:00:00Z",
                query_until="2026-01-01T00:00:00Z",
                raw_count=0,
                overflow_risk=False,
                seen_events={},
            )
        )

        az._run_event_analysis()

        az._fetch_event_batch.assert_called_once()

    def test_analyzer_processes_empty_poll_without_dispatching(self):
        """When subscriber returns [], _run_event_analysis completes without
        dispatching any alert and returns an empty list."""
        mock_sub = MagicMock()
        mock_sub.poll_new_rows.return_value = []

        az = _make_analyzer(rules=[_event_rule(threshold=1)], subscriber_events=mock_sub)

        result = az._run_event_analysis()

        az.reporter.add_event_alert.assert_not_called()
        self.assertEqual(result, [])

    def test_analyzer_dispatches_on_new_events_from_cache(self):
        """When subscriber returns event dicts, the events pass through the
        normalizer/matcher pipeline and trigger reporter.add_event_alert when
        the rule threshold is met."""
        mock_sub = MagicMock()
        mock_sub.poll_new_rows.return_value = [_raw_event()]

        rule = _event_rule(threshold=1)
        az = _make_analyzer(rules=[rule], subscriber_events=mock_sub)

        with patch("src.analyzer.matches_event_rule", return_value=True):
            result = az._run_event_analysis()

        az.reporter.add_event_alert.assert_called_once()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["rule"], rule["name"])

    def test_cache_poll_records_event_poll_status_ok(self):
        """The cache event path must record event_poll_status='ok' — the dashboard
        'Event Poll' card reads pce_stats.event_poll_status. The legacy path set it;
        the cache path must too, else the card is stuck 'unknown' despite live polls."""
        mock_sub = MagicMock()
        mock_sub.poll_new_rows.return_value = []  # successful poll, no new rows

        az = _make_analyzer(rules=[_event_rule()], subscriber_events=mock_sub)
        # clean baseline — don't depend on any state file the ctor may have loaded
        az.state["pce_stats"].update({"event_poll_status": "unknown", "last_event_poll": ""})
        az._run_event_analysis()

        ps = az.state["pce_stats"]
        self.assertEqual(ps["event_poll_status"], "ok")
        self.assertTrue(ps["last_event_poll"])  # timestamp recorded

    def test_cache_poll_failure_records_event_poll_status_error(self):
        """When the cache poll raises, event_poll_status must flip to 'error' with
        the reason captured (parity with the legacy path's record_pce_error)."""
        mock_sub = MagicMock()
        mock_sub.poll_new_rows.side_effect = Exception("cache db locked")

        az = _make_analyzer(rules=[_event_rule()], subscriber_events=mock_sub)
        # clean baseline — don't depend on any state file the ctor may have loaded
        az.state["pce_stats"].update({"event_poll_status": "unknown", "last_error": ""})
        az._run_event_analysis()

        ps = az.state["pce_stats"]
        self.assertEqual(ps["event_poll_status"], "error")
        self.assertIn("cache db locked", ps["last_error"])


    # ─── _fetch_query_flows hybrid (partial) ──────────────────────────────────

    def test_query_flows_partial_with_empty_api_stream_tags_as_cache(self):
        """Analyzer hybrid: when execute_traffic_query_stream yields zero items
        (success but empty), source must be 'cache' — the effective result is
        entirely from the cache, so 'mixed' would be misleading."""
        az = _make_analyzer()
        az._cache_reader = _make_cache_reader_for_flows(
            cover_state="partial", cache_start=_CACHE_START,
        )
        # Generator that yields nothing — always truthy, but drains to [].
        az.api.execute_traffic_query_stream.return_value = iter([])
        az.api.build_traffic_query_spec = MagicMock(return_value=MagicMock(
            report_only_filters={}, requires_draft_pd=False,
        ))

        flows, source = az._fetch_query_flows(
            _START, _END, ["allowed"], az.api.build_traffic_query_spec({}), False,
        )

        self.assertEqual(source, "cache")
        # The cached flows should still be returned.
        self.assertGreater(len(flows), 0)

    def test_query_flows_partial_with_api_exception_falls_back_to_api(self):
        """Analyzer hybrid: when execute_traffic_query_stream raises (gap call),
        the partial branch must fall through to the full-API path, not silently
        return cache data as source='cache'."""
        az = _make_analyzer()
        az._cache_reader = _make_cache_reader_for_flows(
            cover_state="partial", cache_start=_CACHE_START,
        )
        # First call (gap) raises; second call (full fallthrough) returns a stream.
        api_fallback_flow = {"policy_decision": "blocked"}
        call_count = {"n": 0}

        def _stream_side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise Exception("PCE connection error")
            return iter([api_fallback_flow])

        az.api.execute_traffic_query_stream.side_effect = _stream_side_effect
        az.api.build_traffic_query_spec = MagicMock(return_value=MagicMock(
            report_only_filters={}, requires_draft_pd=False,
        ))

        flows, source = az._fetch_query_flows(
            _START, _END, ["allowed"], az.api.build_traffic_query_spec({}), False,
        )

        self.assertEqual(source, "api")
        # execute_traffic_query_stream should have been called twice:
        # once for the gap (raises), once for the full-range fallthrough.
        self.assertEqual(az.api.execute_traffic_query_stream.call_count, 2)

    def test_query_flows_hybrid_gap_end_excludes_cache_start(self):
        """Behavior lock (Task C6): the API gap query and the cache read must
        not both include the flow sitting exactly on cache_start. read_flows_raw
        is inclusive on both ends ('last_detected >= start'), so the gap query's
        end boundary sent to the API must be strictly before cache_start (a
        half-open [start, cache_start) gap) — not cache_start itself, which
        would double-count any flow whose last_detected == cache_start.
        """
        az = _make_analyzer()
        cr = _make_cache_reader_for_flows(cover_state="partial", cache_start=_CACHE_START)
        az._cache_reader = cr
        az.api.execute_traffic_query_stream.return_value = iter([])
        az.api.build_traffic_query_spec = MagicMock(return_value=MagicMock(
            report_only_filters={}, requires_draft_pd=False,
        ))

        az._fetch_query_flows(
            _START, _END, ["allowed"], az.api.build_traffic_query_spec({}), False,
        )

        gap_end_arg = az.api.execute_traffic_query_stream.call_args[0][1]
        gap_end_dt = datetime.datetime.strptime(gap_end_arg, '%Y-%m-%dT%H:%M:%SZ').replace(
            tzinfo=datetime.timezone.utc)
        self.assertLess(gap_end_dt, _CACHE_START)

        # Cache read must still start exactly at cache_start (unchanged contract).
        cr.read_flows_raw.assert_called_once()
        cache_read_start = cr.read_flows_raw.call_args[0][0]
        self.assertEqual(cache_read_start, _CACHE_START)

    def test_query_flows_hybrid_boundary_flow_counted_exactly_once(self):
        """資料層行為鎖（Task C6）：last_detected 恰好等於 cache_start 的 flow，
        在合併結果中必須恰好出現一次。

        兩個 mock 資料來源皆持有同一筆 boundary flow，且各自忠實模擬
        「兩端皆含端點」的查詢語意（API 依收到的 start/end 參數過濾、
        cache 依 last_detected >= start 過濾）。修正前 API gap 以
        cache_start 結束，兩側都會回傳 boundary flow → 合併後出現兩次；
        修正後 gap 結束於 cache_start 之前，只有 cache 側回傳它 → 一次。
        """
        boundary_flow = {
            "policy_decision": "allowed",
            "last_detected": _CACHE_START.strftime('%Y-%m-%dT%H:%M:%SZ'),
            "id": "boundary",
        }
        gap_only_flow = {
            "policy_decision": "allowed",
            "last_detected": "2026-01-02T00:00:00Z",
            "id": "gap-only",
        }
        all_flows = [gap_only_flow, boundary_flow]

        def _parse(ts):
            return datetime.datetime.strptime(ts, '%Y-%m-%dT%H:%M:%SZ').replace(
                tzinfo=datetime.timezone.utc)

        def _api_stream(start_str, end_str, *args, **kwargs):
            # 模擬 PCE API：回傳 [start, end] 兩端皆含端點的 flow
            s, e = _parse(start_str), _parse(end_str)
            return iter([f for f in all_flows if s <= _parse(f["last_detected"]) <= e])

        def _cache_read(start, end, *args, **kwargs):
            # 模擬 read_flows_raw：last_detected >= start AND <= end（皆含端點）
            return [f for f in all_flows if start <= _parse(f["last_detected"]) <= end]

        az = _make_analyzer()
        cr = MagicMock()
        cr.cover_state.return_value = "partial"
        cr.earliest_data_timestamp.return_value = _CACHE_START
        cr.read_flows_raw.side_effect = _cache_read
        az._cache_reader = cr
        az.api.execute_traffic_query_stream.side_effect = _api_stream
        az.api.build_traffic_query_spec = MagicMock(return_value=MagicMock(
            report_only_filters={}, requires_draft_pd=False,
        ))

        flows, source = az._fetch_query_flows(
            _START, _END, ["allowed"], az.api.build_traffic_query_spec({}), False,
        )

        merged = list(flows)
        ids = [f["id"] for f in merged]
        self.assertEqual(ids.count("boundary"), 1)  # 端點 flow 恰好一次
        self.assertEqual(ids.count("gap-only"), 1)  # gap 段 flow 不受影響
        self.assertEqual(source, "mixed")


if __name__ == "__main__":
    unittest.main()


class TestTrafficWindowOnCache(unittest.TestCase):
    """A1（2026-07-24 審查）：cache 路徑流量規則必須全視窗查詢，
    不得用 cursor 增量（視窗會退化成輪詢間隔、嚴重漏告警）。"""

    @staticmethod
    def _traffic_rule(threshold=100, window=10):
        return {"id": "t1", "type": "traffic", "name": "conn spike",
                "threshold_count": threshold, "threshold_window": window,
                "threshold_type": "count", "cooldown_minutes": 0,
                "filter_type": "port", "filter_value": "443"}

    def test_fetch_traffic_uses_window_query_not_cursor(self):
        import datetime as dt
        mock_sub = MagicMock()
        mock_sub.fetch_window_rows.return_value = []
        az = _make_analyzer(rules=[self._traffic_rule(window=10)],
                            subscriber_flows=mock_sub)
        _stream, _rules, now_utc = az._fetch_traffic()
        mock_sub.fetch_window_rows.assert_called_once()
        mock_sub.poll_new_rows.assert_not_called()
        call = mock_sub.fetch_window_rows.call_args
        since = call.args[0] if call.args else call.kwargs["since"]
        span = (now_utc - since).total_seconds()
        # legacy 語意：max_win + 2 分鐘
        self.assertGreaterEqual(span, 12 * 60 - 5)

    def test_window_accumulation_reaches_threshold(self):
        import datetime as dt
        flows = [{"num_connections": 1, "timestamp": ""} for _ in range(120)]
        mock_sub = MagicMock()
        mock_sub.fetch_window_rows.return_value = flows
        rule = self._traffic_rule(threshold=100, window=10)
        az = _make_analyzer(rules=[rule], subscriber_flows=mock_sub)
        stream, tr_rules, now_utc = az._fetch_traffic()
        with unittest.mock.patch.object(az, "check_flow_match", return_value=True):
            result = az._run_rule_engine(iter(stream), tr_rules, now_utc)
        _, res = result[0]
        self.assertGreaterEqual(res["max_val"], 100)


class TestCountRuleEdges(unittest.TestCase):
    """A2（2026-07-24 審查）：count 型規則在本 cycle 無新事件時
    不得發出 time=N/A、內容全空的空殼告警。"""

    @staticmethod
    def _count_rule(threshold=1):
        return {"id": "cr1", "name": "count rule", "type": "event",
                "threshold_type": "count", "threshold_count": threshold,
                "threshold_window": 10, "filter_type": "any",
                "filter_value": "", "cooldown_minutes": 0}

    def test_window_count_met_but_no_new_matches_no_alert(self):
        import datetime as dt
        # 非空輪詢（其他事件到達）但無一匹配本規則 → matches=[] 而視窗計數達標
        other = _raw_event(event_type="user.login")
        other["timestamp"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        mock_sub = MagicMock()
        mock_sub.poll_new_rows.return_value = [other]
        az = _make_analyzer(rules=[self._count_rule(threshold=1)],
                            subscriber_events=mock_sub)
        recent = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=2)
        az.state["history"] = {"cr1": [{"t": recent.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                        "event_id": "x"}]}
        with patch("src.analyzer.matches_event_rule", return_value=False):
            az._run_event_analysis()
        az.reporter.add_event_alert.assert_not_called()

    def test_new_match_alerts_with_window_count(self):
        import datetime as dt
        mock_sub = MagicMock()
        ev = _raw_event()
        ev["timestamp"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        mock_sub.poll_new_rows.return_value = [ev]
        az = _make_analyzer(rules=[self._count_rule(threshold=1)],
                            subscriber_events=mock_sub)
        az.state["history"] = {}
        with patch("src.analyzer.matches_event_rule", return_value=True):
            az._run_event_analysis()
        az.reporter.add_event_alert.assert_called_once()
        alert = az.reporter.add_event_alert.call_args[0][0]
        self.assertNotEqual(alert["time"], "N/A")


class TestHistoryRetention(unittest.TestCase):
    """A3（2026-07-24 審查）：history 保留期須跟著最大 count 視窗走，
    否則 >2h 視窗被靜默低估。"""

    def test_history_retained_for_large_window(self):
        import datetime as dt
        import json as _json
        import tempfile, os
        rule = {"id": "big", "name": "big", "type": "event",
                "threshold_type": "count", "threshold_count": 5,
                "threshold_window": 180, "filter_type": "any", "filter_value": ""}
        az = _make_analyzer(rules=[rule])
        az.save_state = Analyzer.save_state.__get__(az)
        old = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=150)
        az.state["history"] = {"big": [{"t": old.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                        "event_id": "x"}]}
        with tempfile.TemporaryDirectory() as td:
            sf = os.path.join(td, "state.json")
            with patch("src.analyzer.STATE_FILE", sf):
                az.save_state()
            persisted = _json.load(open(sf))
        # 150 分鐘前的紀錄在 180 分鐘視窗下必須保留（舊版 2h 固定裁剪會刪掉）
        self.assertEqual(len(persisted["history"].get("big", [])), 1)


class TestStrictWindow(unittest.TestCase):
    """A4（2026-07-24 審查）：fail-closed 只限規則引擎加總路徑
    （strict_window=True）；query/報表路徑維持舊語意——cache/archive
    投影常無 timestamp，整批誤殺會清空查詢結果。"""

    def test_missing_timestamp_excluded_only_in_strict_mode(self):
        import datetime as dt
        rule = {"id": "t1", "type": "traffic", "name": "t", "pd": -1}
        az = _make_analyzer(rules=[rule])
        flow = {"num_connections": 1}  # 無 timestamp
        win = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=10)
        self.assertFalse(az.check_flow_match(rule, flow, win, strict_window=True))
        self.assertTrue(az.check_flow_match(rule, flow, win))
