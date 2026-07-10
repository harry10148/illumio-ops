"""Overflow means the oldest events in the window were silently lost (the
sync events API returns only the newest max_results rows) — must self-alert."""
from __future__ import annotations

import datetime
from unittest.mock import MagicMock

import pytest

from src.events.poller import EventBatch, format_utc


@pytest.fixture
def ana(tmp_path, monkeypatch):
    import src.analyzer as analyzer_mod
    monkeypatch.setattr(analyzer_mod, "STATE_FILE", str(tmp_path / "state.json"))
    from src.analyzer import Analyzer
    from src.config import ConfigManager
    cm = ConfigManager()
    cm.config["rules"] = []
    a = Analyzer(cm, MagicMock(), MagicMock())
    return a


def _overflow_batch():
    return EventBatch(
        events=[], next_watermark="2026-07-04T00:10:00Z",
        query_since="2026-07-04T00:00:00Z", query_until="2026-07-04T00:10:00Z",
        raw_count=5000, overflow_risk=True, seen_events={},
    )


def test_overflow_fires_meta_alert(ana, monkeypatch):
    monkeypatch.setattr(ana, "_fetch_event_batch", lambda: _overflow_batch())
    ana.state["event_overflow"] = {"raw_count": 5000, "max_results": 5000,
                                   "query_since": "2026-07-04T00:00:00Z",
                                   "query_until": "2026-07-04T00:10:00Z",
                                   "detected_at": "2026-07-04T00:10:00Z"}
    ana._maybe_alert_overflow()
    ana.reporter.add_health_alert.assert_called_once()


def test_overflow_alert_respects_cooldown(ana):
    ana.state["event_overflow"] = {"raw_count": 5000, "max_results": 5000}
    ana.state["overflow_last_alert_at"] = format_utc(
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=5)
    )
    ana._maybe_alert_overflow()
    ana.reporter.add_health_alert.assert_not_called()


def test_no_overflow_no_alert(ana):
    ana.state["event_overflow"] = {}
    ana._maybe_alert_overflow()
    ana.reporter.add_health_alert.assert_not_called()
