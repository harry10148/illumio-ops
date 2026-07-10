"""Alert DLQ: alerts survive a full-channel outage and are retried next cycle,
dropped with a dispatch_history record after 3 attempts."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

import src.reporter as reporter_mod
from src.reporter import Reporter


@pytest.fixture
def rep(tmp_path, monkeypatch):
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(reporter_mod, "STATE_FILE", str(state_file))
    from src.config import ConfigManager
    cm = ConfigManager()
    cm.config["alerts"]["active"] = ["webhook"]
    cm.config["alerts"]["webhook_url"] = "https://hooks.example.com/x"
    r = Reporter(cm)
    return r, state_file


def _failing_send(self, reporter, subject, *, lang="en"):
    return {"channel": "webhook", "status": "failed", "target": "https://hooks.example.com/...", "error": "boom"}


def _ok_send(self, reporter, subject, *, lang="en"):
    return {"channel": "webhook", "status": "success", "target": "https://hooks.example.com/..."}


def _dlq(state_file):
    if not state_file.exists():
        return []
    return json.loads(state_file.read_text()).get("alert_dlq", [])


def test_full_failure_persists_alerts_to_dlq(rep):
    r, state_file = rep
    r.add_health_alert({"time": "t", "rule": "R", "status": "503", "details": "d"})
    with patch("src.alerts.plugins.WebhookAlertPlugin.send", _failing_send):
        r.send_alerts()
    entries = _dlq(state_file)
    assert len(entries) == 1
    assert entries[0]["attempts"] == 1
    assert entries[0]["buckets"]["health"][0]["rule"] == "R"


def test_dlq_replayed_and_cleared_on_success(rep):
    r, state_file = rep
    r.add_health_alert({"time": "t", "rule": "R", "status": "503", "details": "d"})
    with patch("src.alerts.plugins.WebhookAlertPlugin.send", _failing_send):
        r.send_alerts()
    r2 = Reporter(r.cm)
    with patch("src.alerts.plugins.WebhookAlertPlugin.send", _ok_send):
        results = r2.send_alerts()  # empty buckets + DLQ replay -> must still send
    assert results and results[0]["status"] == "success"
    assert _dlq(state_file) == []


def test_dropped_after_max_attempts(rep):
    r, state_file = rep
    r.add_health_alert({"time": "t", "rule": "R", "status": "503", "details": "d"})
    with patch("src.alerts.plugins.WebhookAlertPlugin.send", _failing_send):
        r.send_alerts()
        for _ in range(Reporter.ALERT_DLQ_MAX_ATTEMPTS - 1):
            Reporter(r.cm).send_alerts()
    assert _dlq(state_file) == []
    history = json.loads(state_file.read_text()).get("dispatch_history", [])
    assert any(h["channel"] == "dlq" and h["status"] == "dropped" for h in history)


def test_all_skipped_does_not_enqueue(rep):
    r, state_file = rep
    r.cm.config["alerts"]["webhook_url"] = ""
    r.add_health_alert({"time": "t", "rule": "R", "status": "503", "details": "d"})
    r.send_alerts()
    assert _dlq(state_file) == []
