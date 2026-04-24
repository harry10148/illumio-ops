"""
Phase 15 E2E test — subscriber cursor + cache lag detection.

Scenario:
  1. In-memory SQLite DB with init_schema.
  2. Seed 3 PceEvent rows.
  3. Build CacheSubscriber for consumer="analyzer", source_table="pce_events".
  4. Instantiate Analyzer with subscriber_events=<subscriber>.
  5. Call _run_event_analysis() — verify all 3 events are consumed.
  6. Second call returns 0 (cursor advanced).
  7. Add 1 new event — next call picks up exactly 1.
  8. Simulate lag — IngestionWatermark.last_sync_at 2 hours ago;
     check_cache_lag(sf, max_lag_seconds=300) yields level=="error".
"""
from __future__ import annotations

import datetime
import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.pce_cache.schema import init_schema
from src.pce_cache.models import PceEvent, IngestionWatermark
from src.pce_cache.subscriber import CacheSubscriber
from src.pce_cache.lag_monitor import check_cache_lag


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_engine():
    engine = create_engine("sqlite:///:memory:")
    init_schema(engine)
    return engine


def _seed_event(sf: sessionmaker, uuid: str, ingested_at: datetime.datetime) -> None:
    with sf.begin() as s:
        s.add(PceEvent(
            pce_href=f"/orgs/1/events/{uuid}",
            pce_event_id=uuid,
            timestamp=ingested_at,
            event_type="policy.update",
            severity="info",
            status="success",
            pce_fqdn="pce.example.com",
            raw_json="{}",
            ingested_at=ingested_at,
        ))


def _make_analyzer(subscriber_events):
    from src.analyzer import Analyzer
    mock_cm = MagicMock()
    mock_cm.config = {"rules": []}
    mock_api = MagicMock()
    mock_rep = MagicMock()
    az = Analyzer(mock_cm, mock_api, mock_rep, subscriber_events=subscriber_events)
    az.load_state = MagicMock()
    az.save_state = MagicMock()
    return az


# ─── Tests ─────────────────────────────────────────────────────────────────────

class TestPhase15E2E(unittest.TestCase):

    def setUp(self):
        self.engine = _make_engine()
        self.sf = sessionmaker(self.engine)
        base_ts = datetime.datetime(2026, 4, 20, 10, 0, 0, tzinfo=datetime.timezone.utc)
        for i, uid in enumerate(["ev-a", "ev-b", "ev-c"]):
            _seed_event(
                self.sf,
                uid,
                base_ts + datetime.timedelta(seconds=i),
            )

    def test_all_three_events_consumed_on_first_call(self):
        """First _run_event_analysis() reads all 3 seeded events via subscriber."""
        sub = CacheSubscriber(self.sf, consumer="analyzer", source_table="pce_events")
        az = _make_analyzer(subscriber_events=sub)

        rows_seen = []
        original_poll = sub.poll_new_rows

        def capture_poll(**kw):
            result = original_poll(**kw)
            rows_seen.extend(result)
            return result

        sub.poll_new_rows = capture_poll
        az._run_event_analysis()
        self.assertEqual(len(rows_seen), 3)

    def test_second_call_returns_empty(self):
        """After draining the 3 events, a second call yields no new rows."""
        sub = CacheSubscriber(self.sf, consumer="analyzer", source_table="pce_events")
        az = _make_analyzer(subscriber_events=sub)

        # First drain
        az._run_event_analysis()

        # Patch poll on second call to capture what subscriber returns
        second_poll_result = []
        original_poll = sub.poll_new_rows

        def capture_second(**kw):
            result = original_poll(**kw)
            second_poll_result.extend(result)
            return result

        sub.poll_new_rows = capture_second
        az._run_event_analysis()
        self.assertEqual(second_poll_result, [])

    def test_new_event_picked_up_after_cursor_advance(self):
        """After cursor is advanced past initial 3 events, adding 1 more yields exactly 1."""
        sub = CacheSubscriber(self.sf, consumer="analyzer", source_table="pce_events")
        az = _make_analyzer(subscriber_events=sub)

        # Drain initial rows
        az._run_event_analysis()

        # Add 1 new event
        _seed_event(
            self.sf,
            "ev-d",
            datetime.datetime(2026, 4, 20, 10, 1, 0, tzinfo=datetime.timezone.utc),
        )

        new_rows = []
        original_poll = sub.poll_new_rows

        def capture(**kw):
            result = original_poll(**kw)
            new_rows.extend(result)
            return result

        sub.poll_new_rows = capture
        az._run_event_analysis()
        self.assertEqual(len(new_rows), 1)

    def test_lag_monitor_reports_error_when_last_sync_2h_ago(self):
        """check_cache_lag returns level=='error' when last_sync_at is 2 hours ago."""
        two_hours_ago = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=2)
        with self.sf.begin() as s:
            s.add(IngestionWatermark(
                source="events",
                last_sync_at=two_hours_ago,
                last_status="ok",
            ))

        results = check_cache_lag(self.sf, max_lag_seconds=300)
        error_results = [r for r in results if r["level"] == "error"]
        self.assertTrue(
            len(error_results) >= 1,
            f"Expected at least one 'error' entry; got: {results}",
        )


if __name__ == "__main__":
    unittest.main()
