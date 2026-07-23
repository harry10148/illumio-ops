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


def test_all_skipped_enqueues_without_attempt(rep):
    """B1（2026-07-24 審查）：全 skipped（設定缺失）不得遺失告警——
    入列 DLQ 但不消耗重試額度。"""
    r, state_file = rep
    r.cm.config["alerts"]["webhook_url"] = ""
    r.add_health_alert({"time": "t", "rule": "R", "status": "503", "details": "d"})
    r.send_alerts()
    entries = _dlq(state_file)
    assert len(entries) == 1
    assert entries[0]["attempts"] == 0
    assert entries[0]["buckets"]["health"][0]["rule"] == "R"


def test_dlq_survives_skipped_cycle_without_attempt_increment(rep):
    """失敗 1 次入列後，遇全 skipped cycle：DLQ 保留且 attempts 不增。"""
    r, state_file = rep
    r.add_health_alert({"time": "t", "rule": "R", "status": "503", "details": "d"})
    with patch("src.alerts.plugins.WebhookAlertPlugin.send", _failing_send):
        r.send_alerts()
    assert _dlq(state_file)[0]["attempts"] == 1
    r.cm.config["alerts"]["webhook_url"] = ""
    Reporter(r.cm).send_alerts()
    entries = _dlq(state_file)
    assert len(entries) == 1
    assert entries[0]["attempts"] == 1
    assert entries[0]["buckets"]["health"][0]["rule"] == "R"


def test_line_cooldown_reports_skipped(rep):
    """B2：LINE 自我冷卻是暫時不可用，回 skipped 而非 failed
    ——否則冷卻窗會把 DLQ 3 次額度燒完提早丟棄告警。"""
    from src.alerts.plugins import LineAlertPlugin
    import time as _time
    r, _sf = rep
    r.cm.config["alerts"]["line_channel_access_token"] = "tok"
    r.cm.config["alerts"]["line_target_id"] = "Uabc"
    plugin = LineAlertPlugin(r.cm)
    plugin._cooldown_until = _time.monotonic() + 300
    result = plugin.send(r, "subj")
    assert result["status"] == "skipped"
    assert "cooldown" in result["error"]


def test_dlq_bucket_capped(rep):
    """防無界：單 bucket 超過上限只留最新 N 筆。"""
    r, state_file = rep
    r.cm.config["alerts"]["webhook_url"] = ""
    for i in range(Reporter.ALERT_DLQ_BUCKET_CAP + 20):
        r.add_health_alert({"time": f"t{i}", "rule": f"R{i}", "status": "503", "details": "d"})
    r.send_alerts()
    entries = _dlq(state_file)
    bucket = entries[0]["buckets"]["health"]
    assert len(bucket) == Reporter.ALERT_DLQ_BUCKET_CAP
    assert bucket[-1]["rule"] == f"R{Reporter.ALERT_DLQ_BUCKET_CAP + 19}"


def test_multi_entry_replay_merges_with_min_attempts(rep):
    """B4：多筆殘留條目重播失敗 → 合併條目 attempts 取 min+1，
    避免較年輕告警被提早丟棄。"""
    from src.state_store import update_state_file
    r, state_file = rep

    def _seed(existing):
        out = dict(existing)
        out["alert_dlq"] = [
            {"buckets": {"health": [{"rule": "OLD"}], "event": [], "traffic": [], "metric": []},
             "attempts": 2, "first_failed_at": "2026-07-24T00:00:00Z"},
            {"buckets": {"health": [{"rule": "YOUNG"}], "event": [], "traffic": [], "metric": []},
             "attempts": 1, "first_failed_at": "2026-07-24T01:00:00Z"},
        ]
        return out

    update_state_file(str(state_file), _seed)
    with patch("src.alerts.plugins.WebhookAlertPlugin.send", _failing_send):
        Reporter(r.cm).send_alerts()
    entries = _dlq(state_file)
    assert len(entries) == 1
    assert entries[0]["attempts"] == 2  # min(2,1)+1
    rules = {a["rule"] for a in entries[0]["buckets"]["health"]}
    assert rules == {"OLD", "YOUNG"}
