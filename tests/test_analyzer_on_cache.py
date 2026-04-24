"""
Phase 15 Task 4: Tests for Analyzer cache-subscriber integration.

Covered invariants:
  1. _run_event_analysis() calls subscriber.poll_new_rows() when subscriber_events is set
  2. _run_event_analysis() falls back to legacy API path when subscriber_events is None
  3. _run_event_analysis() handles empty poll result without dispatching any alert
  4. _run_event_analysis() processes events from cache through the normalizer/matcher pipeline
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


if __name__ == "__main__":
    unittest.main()
