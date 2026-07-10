"""Watchdog: after N consecutive PCE failures the analyzer must self-alert,
because a dead poller otherwise fails silent (no events -> no alerts)."""
from __future__ import annotations

import datetime
from unittest.mock import MagicMock

import pytest

from src.analyzer import Analyzer, WATCHDOG_FAILURE_THRESHOLD
from src.events.poller import format_utc


@pytest.fixture
def ana(tmp_path, monkeypatch):
    import src.analyzer as analyzer_mod
    monkeypatch.setattr(analyzer_mod, "STATE_FILE", str(tmp_path / "state.json"))
    from src.config import ConfigManager
    cm = ConfigManager()
    cm.config["rules"] = []
    a = Analyzer(cm, MagicMock(), MagicMock())
    return a


def test_watchdog_fires_at_threshold(ana):
    ana.state["pce_stats"]["consecutive_failures"] = WATCHDOG_FAILURE_THRESHOLD
    ana._check_watchdog()
    ana.reporter.add_health_alert.assert_called_once()
    alert = ana.reporter.add_health_alert.call_args[0][0]
    assert str(WATCHDOG_FAILURE_THRESHOLD) in alert["details"]
    assert ana.state["watchdog_last_alert_at"]


def test_watchdog_quiet_below_threshold(ana):
    ana.state["pce_stats"]["consecutive_failures"] = WATCHDOG_FAILURE_THRESHOLD - 1
    ana._check_watchdog()
    ana.reporter.add_health_alert.assert_not_called()


def test_watchdog_respects_own_cooldown(ana):
    ana.state["pce_stats"]["consecutive_failures"] = WATCHDOG_FAILURE_THRESHOLD
    ana.state["watchdog_last_alert_at"] = format_utc(
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=10)
    )
    ana._check_watchdog()
    ana.reporter.add_health_alert.assert_not_called()


def test_watchdog_run_by_run_analysis(ana, monkeypatch):
    monkeypatch.setattr(ana, "_run_health_check", lambda: True)
    monkeypatch.setattr(ana, "_run_event_analysis", lambda: [])
    monkeypatch.setattr(ana, "_fetch_traffic", lambda: (None, [], datetime.datetime.now(datetime.timezone.utc)))
    monkeypatch.setattr(ana, "save_state", lambda: None)
    ana.state["pce_stats"]["consecutive_failures"] = WATCHDOG_FAILURE_THRESHOLD
    ana.run_analysis()
    ana.reporter.add_health_alert.assert_called_once()
