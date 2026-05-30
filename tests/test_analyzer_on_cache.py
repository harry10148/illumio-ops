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


if __name__ == "__main__":
    unittest.main()
