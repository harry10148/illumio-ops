"""Tests for lag_monitor alert throttling (AL-Task 11 — 容量案移交 Alert 案的
對帳掛帳項). Neither the level-based alerts (level=="error"/"warning") nor the
status-based alert (status_alerts(), Task 2) throttle repeats — every 60s tick
re-logs while the condition persists. This produces an alert storm on a
sustained outage. lag_monitor has no reporter/STATE_FILE lifecycle (unlike the
analyzer watchdog, AL-Task 6), so throttling here uses a module-level dict
keyed by alert identity, per the task spec."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _reset_alert_cooldown_state():
    from src.pce_cache import lag_monitor
    lag_monitor._last_alert_at.clear()
    lag_monitor._suppression_logged.clear()
    yield
    lag_monitor._last_alert_at.clear()
    lag_monitor._suppression_logged.clear()


def _make_cm(tmp_path):
    cm = MagicMock()
    cm.models.pce_cache.db_path = str(tmp_path / "c.sqlite")
    cm.models.pce_cache.events_poll_interval_seconds = 300
    cm.models.pce_cache.traffic_poll_interval_seconds = 3600
    return cm


def _run_with_result(cm, result):
    from src.pce_cache import lag_monitor
    with patch("src.gui._helpers._get_cache_engine"), \
         patch("src.pce_cache.lag_monitor.check_cache_lag", return_value=[result]):
        lag_monitor.run_cache_lag_monitor(cm)


def _errors(caplog):
    return [r for r in caplog.records if r.levelname == "ERROR"]


def test_same_tick_double_call_logs_level_error_once(tmp_path, caplog):
    cm = _make_cm(tmp_path)
    result = {"source": "events", "level": "error", "lag_seconds": 900,
              "last_status": "ok", "last_error": None}
    _run_with_result(cm, result)
    _run_with_result(cm, result)
    assert len(_errors(caplog)) == 1


def test_cooldown_suppresses_repeat_within_window(tmp_path, caplog):
    from src.pce_cache import lag_monitor
    cm = _make_cm(tmp_path)
    result = {"source": "events", "level": "error", "lag_seconds": 900,
              "last_status": "ok", "last_error": None}
    _run_with_result(cm, result)
    key = ("level", "events", "error")
    lag_monitor._last_alert_at[key] = datetime.now(timezone.utc) - timedelta(minutes=30)
    caplog.clear()
    _run_with_result(cm, result)
    assert len(_errors(caplog)) == 0


def test_recovery_then_refail_alerts_immediately(tmp_path, caplog):
    cm = _make_cm(tmp_path)
    error_result = {"source": "events", "level": "error", "lag_seconds": 900,
                     "last_status": "ok", "last_error": None}
    ok_result = {"source": "events", "level": "ok", "lag_seconds": 10,
                 "last_status": "ok", "last_error": None}
    _run_with_result(cm, error_result)
    caplog.clear()
    _run_with_result(cm, ok_result)  # recovery clears the cooldown timestamp
    caplog.clear()
    _run_with_result(cm, error_result)  # re-fail immediately after recovery
    assert len(_errors(caplog)) == 1


def test_different_sources_independent(tmp_path, caplog):
    cm = _make_cm(tmp_path)
    events_result = {"source": "events", "level": "error", "lag_seconds": 900,
                      "last_status": "ok", "last_error": None}
    traffic_result = {"source": "traffic", "level": "error", "lag_seconds": 900,
                       "last_status": "ok", "last_error": None}
    from src.pce_cache import lag_monitor
    with patch("src.gui._helpers._get_cache_engine"), \
         patch("src.pce_cache.lag_monitor.check_cache_lag",
               return_value=[events_result, traffic_result]):
        lag_monitor.run_cache_lag_monitor(cm)
    assert len(_errors(caplog)) == 2


def test_suppression_logs_debug_once_at_start(tmp_path, caplog):
    """壓制起點記一條 debug（身份 + 起訖），壓制期間後續 tick 不重複記
    （避免洗版；本 sweep 新增，不改既有節流語意）。"""
    import logging
    caplog.set_level(logging.DEBUG)
    cm = _make_cm(tmp_path)
    result = {"source": "events", "level": "error", "lag_seconds": 900,
              "last_status": "ok", "last_error": None}
    _run_with_result(cm, result)  # first tick: alert fires, no suppression yet
    debug_records = [r for r in caplog.records if r.levelname == "DEBUG"]
    assert len(debug_records) == 0
    caplog.clear()
    _run_with_result(cm, result)  # second tick within cooldown: suppressed
    debug_records = [r for r in caplog.records if r.levelname == "DEBUG"]
    assert len(debug_records) == 1
    assert "events" in debug_records[0].message
    caplog.clear()
    _run_with_result(cm, result)  # third tick still suppressed: no repeat debug log
    debug_records = [r for r in caplog.records if r.levelname == "DEBUG"]
    assert len(debug_records) == 0


def test_status_alert_throttled_independently_of_level(tmp_path, caplog):
    cm = _make_cm(tmp_path)
    result = {"source": "traffic", "level": "ok", "lag_seconds": 10,
              "last_status": "error", "last_error": "boom"}
    _run_with_result(cm, result)
    assert len(_errors(caplog)) == 1  # first call: status alert fires
    caplog.clear()
    _run_with_result(cm, result)
    assert len(_errors(caplog)) == 0  # second call within cooldown: suppressed
