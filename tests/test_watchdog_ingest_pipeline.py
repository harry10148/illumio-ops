"""AL-6 watchdog gap fix: when pce_cache.enabled=true, the monitor cycle reads
from the local cache and never touches the live PCE, so record_pce_error()
was never called and pce_stats.consecutive_failures could never climb — the
watchdog was dead code in this deployment shape (see
.superpowers/sdd/live-verification-report.md, finding #5).

This module tests the fix: the scheduler's cache-ingest jobs
(run_events_ingest / run_traffic_ingest — the only code that actually talks
to the live PCE in this deployment shape) now mirror success/failure into the
SAME pce_stats.consecutive_failures state.json field the legacy Analyzer path
already shares across health/events checks, so Analyzer._check_watchdog
(unchanged) picks it up on its next load_state().

Counting semantic (see src/scheduler/jobs.py:_record_ingest_pce_result
docstring): shared counter across both ingest jobs. ANY successful PCE pull
resets it to 0; a failed pull increments it by 1, evaluated independently per
job invocation (no artificial "tick" grouping across the two independently-
scheduled jobs). A full PCE outage means neither job ever succeeds, so the
counter climbs monotonically; a single broken ingestor with the other still
healthy self-heals every time the healthy one succeeds.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _cm(tmp_path):
    cm = MagicMock()
    cfg = cm.models.pce_cache
    cfg.db_path = str(tmp_path / "cache.sqlite")
    cfg.async_threshold_events = 10000
    cfg.traffic_sampling.max_rows_per_batch = 200000
    cm.models.siem.enabled = False
    return cm


def _state_file(tmp_path):
    return str(tmp_path / "logs" / "state.json")


@pytest.fixture(autouse=True)
def _patch_state_file(tmp_path, monkeypatch):
    import src.scheduler.jobs as jobs_mod
    monkeypatch.setattr(jobs_mod, "_resolve_state_file", lambda: _state_file(tmp_path))
    return tmp_path


def _load_state(tmp_path):
    from src.state_store import load_state_file
    return load_state_file(_state_file(tmp_path))


def test_events_ingest_failure_increments_consecutive_failures(tmp_path):
    from src.scheduler.jobs import run_events_ingest

    cm = _cm(tmp_path)
    with patch("src.scheduler.jobs._get_cache_engine"), \
         patch("sqlalchemy.orm.sessionmaker"), \
         patch("src.scheduler.jobs.ApiClient") as mock_api, \
         patch("src.pce_cache.watermark.WatermarkStore") as mock_wm_cls:
        mock_api.return_value.__enter__.return_value = MagicMock()
        wm = mock_wm_cls.return_value
        wm.get.return_value = MagicMock(last_status="error", last_error="connection refused")
        with patch("src.pce_cache.ingestor_events.EventsIngestor") as mock_ing:
            mock_ing.return_value.run_once.return_value = 0
            run_events_ingest(cm)

    state = _load_state(tmp_path)
    assert state["pce_stats"]["consecutive_failures"] == 1
    assert "connection refused" in state["pce_stats"]["last_error"]


def test_events_ingest_success_resets_consecutive_failures(tmp_path):
    from src.scheduler.jobs import run_events_ingest
    from src.state_store import update_state_file

    update_state_file(_state_file(tmp_path), lambda s: {
        **s, "pce_stats": {"consecutive_failures": 5}
    })

    cm = _cm(tmp_path)
    with patch("src.scheduler.jobs._get_cache_engine"), \
         patch("sqlalchemy.orm.sessionmaker"), \
         patch("src.scheduler.jobs.ApiClient") as mock_api, \
         patch("src.pce_cache.watermark.WatermarkStore") as mock_wm_cls:
        mock_api.return_value.__enter__.return_value = MagicMock()
        wm = mock_wm_cls.return_value
        wm.get.return_value = MagicMock(last_status="ok", last_error=None)
        with patch("src.pce_cache.ingestor_events.EventsIngestor") as mock_ing:
            mock_ing.return_value.run_once.return_value = 3
            run_events_ingest(cm)

    state = _load_state(tmp_path)
    assert state["pce_stats"]["consecutive_failures"] == 0


def test_traffic_ingest_failure_increments_consecutive_failures(tmp_path):
    from src.scheduler.jobs import run_traffic_ingest

    cm = _cm(tmp_path)
    with patch("src.scheduler.jobs._get_cache_engine"), \
         patch("sqlalchemy.orm.sessionmaker"), \
         patch("src.scheduler.jobs.ApiClient") as mock_api, \
         patch("src.pce_cache.watermark.WatermarkStore") as mock_wm_cls:
        mock_api.return_value.__enter__.return_value = MagicMock()
        wm = mock_wm_cls.return_value
        wm.get.return_value = MagicMock(last_status="error", last_error="timeout")
        with patch("src.pce_cache.ingestor_traffic.TrafficIngestor") as mock_ing:
            mock_ing.return_value.run_once.return_value = 0
            mock_ing.return_value.last_run_overflow = None
            run_traffic_ingest(cm)

    state = _load_state(tmp_path)
    assert state["pce_stats"]["consecutive_failures"] == 1


def test_run_events_ingest_records_failure_on_unhandled_exception(tmp_path):
    """If the exception escapes the ingestor entirely (before a watermark row
    exists), the job's own except-clause must still bump the counter — the
    ingest didn't succeed, so the watchdog signal must reflect that even
    without a watermark row to read back."""
    from src.scheduler.jobs import run_events_ingest

    cm = _cm(tmp_path)
    with patch("src.scheduler.jobs._get_cache_engine", side_effect=RuntimeError("db open failed")):
        run_events_ingest(cm)

    state = _load_state(tmp_path)
    assert state["pce_stats"]["consecutive_failures"] == 1
    assert "db open failed" in state["pce_stats"]["last_error"]


def test_three_consecutive_ingest_failures_trigger_watchdog_via_analyzer(tmp_path):
    """End-to-end of the fixed pipeline: 3 consecutive failed ingest ticks
    (the pce_cache deployment's ONLY path that touches the live PCE) must be
    enough for Analyzer._check_watchdog (unchanged) to self-alert on its next
    cycle, exactly as it already does for the legacy path."""
    from src.scheduler.jobs import run_events_ingest
    from src.analyzer import Analyzer, WATCHDOG_FAILURE_THRESHOLD
    import src.analyzer as analyzer_mod

    cm_ingest = _cm(tmp_path)
    for _ in range(WATCHDOG_FAILURE_THRESHOLD):
        with patch("src.scheduler.jobs._get_cache_engine"), \
             patch("sqlalchemy.orm.sessionmaker"), \
             patch("src.scheduler.jobs.ApiClient") as mock_api, \
             patch("src.pce_cache.watermark.WatermarkStore") as mock_wm_cls:
            mock_api.return_value.__enter__.return_value = MagicMock()
            wm = mock_wm_cls.return_value
            wm.get.return_value = MagicMock(last_status="error", last_error="PCE unreachable")
            with patch("src.pce_cache.ingestor_events.EventsIngestor") as mock_ing:
                mock_ing.return_value.run_once.return_value = 0
                run_events_ingest(cm_ingest)

    monkeypatch_state_file = str((tmp_path / "logs" / "state.json"))
    with patch.object(analyzer_mod, "STATE_FILE", monkeypatch_state_file):
        from src.config import ConfigManager
        cm = ConfigManager()
        cm.config["rules"] = []
        ana = Analyzer(cm, MagicMock(), MagicMock())
        assert ana.state["pce_stats"]["consecutive_failures"] == WATCHDOG_FAILURE_THRESHOLD
        ana._check_watchdog()
        ana.reporter.add_health_alert.assert_called_once()


def test_partial_failure_across_jobs_does_not_falsely_trigger_watchdog(tmp_path):
    """One ingestor (traffic) chronically fails while the other (events)
    keeps succeeding: since PCE is demonstrably reachable, the shared counter
    must keep resetting to 0 on every events success and never accumulate to
    the watchdog threshold."""
    from src.scheduler.jobs import run_events_ingest, run_traffic_ingest
    from src.analyzer import WATCHDOG_FAILURE_THRESHOLD

    cm = _cm(tmp_path)
    for _ in range(WATCHDOG_FAILURE_THRESHOLD + 2):
        with patch("src.scheduler.jobs._get_cache_engine"), \
             patch("sqlalchemy.orm.sessionmaker"), \
             patch("src.scheduler.jobs.ApiClient") as mock_api, \
             patch("src.pce_cache.watermark.WatermarkStore") as mock_wm_cls:
            mock_api.return_value.__enter__.return_value = MagicMock()
            wm = mock_wm_cls.return_value
            wm.get.return_value = MagicMock(last_status="error", last_error="traffic endpoint down")
            with patch("src.pce_cache.ingestor_traffic.TrafficIngestor") as mock_ing:
                mock_ing.return_value.run_once.return_value = 0
                mock_ing.return_value.last_run_overflow = None
                run_traffic_ingest(cm)

        with patch("src.scheduler.jobs._get_cache_engine"), \
             patch("sqlalchemy.orm.sessionmaker"), \
             patch("src.scheduler.jobs.ApiClient") as mock_api, \
             patch("src.pce_cache.watermark.WatermarkStore") as mock_wm_cls:
            mock_api.return_value.__enter__.return_value = MagicMock()
            wm = mock_wm_cls.return_value
            wm.get.return_value = MagicMock(last_status="ok", last_error=None)
            with patch("src.pce_cache.ingestor_events.EventsIngestor") as mock_ing:
                mock_ing.return_value.run_once.return_value = 2
                run_events_ingest(cm)

        state = _load_state(tmp_path)
        assert state["pce_stats"]["consecutive_failures"] == 0
