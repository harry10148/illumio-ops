"""Phase 3A Task 2 — dispatched alerts land in AlertStore; DLQ replay updates, never duplicates."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import src.reporter as reporter_mod
from src.alerts.store import AlertStore
from src.reporter import Reporter


@pytest.fixture
def rep(tmp_path, monkeypatch):
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(reporter_mod, "STATE_FILE", str(state_file))
    db = tmp_path / "alerts.sqlite"
    monkeypatch.setattr(Reporter, "alert_store_factory", staticmethod(lambda: AlertStore(str(db))))
    from src.config import ConfigManager
    cm = ConfigManager()
    cm.config["alerts"]["active"] = ["webhook"]
    cm.config["alerts"]["webhook_url"] = "https://hooks.example.com/x"
    return Reporter(cm), db


def _ok(self, reporter, subject, *, lang="en"):
    return {"channel": "webhook", "status": "success", "target": "https://hooks.example.com/...", "error": ""}


def _fail(self, reporter, subject, *, lang="en"):
    return {"channel": "webhook", "status": "failed", "target": "https://hooks.example.com/...", "error": "boom"}


def _fill(r):
    r.add_traffic_alert({"rule": "SSH", "rule_id": "r1", "rule_type": "traffic", "count": "24",
                         "criteria": "port 22 > 20", "details": "d", "raw_data": [{"i": i} for i in range(15)]})
    r.add_event_alert({"time": "2026-09-03T08:00:00Z", "rule": "Login failed", "rule_id": "18",
                       "rule_type": "event", "severity": "warning", "count": 3, "source": "10.0.0.1",
                       "target": "pce", "raw_data": [{"event_type": "user.login"}], "parsed_data": []})
    r.add_health_alert({"time": "t", "rule": "PCE health", "rule_id": "7", "rule_type": "system",
                        "status": "critical", "details": "d"})
    r.add_health_alert({"time": "t", "rule": "Watchdog", "status": "503", "details": "no rule object"})


def test_dispatch_persists_one_row_per_alert(rep):
    r, db = rep
    _fill(r)
    with patch("src.alerts.plugins.WebhookAlertPlugin.send", _ok):
        r.send_alerts()
    st = AlertStore(str(db))
    rows = st.list()["items"]
    assert st.list()["total"] == 4
    by_name = {x["rule_name"]: x for x in rows}
    assert by_name["SSH"]["type"] == "traffic" and by_name["SSH"]["severity"] == "warning"
    assert by_name["Login failed"]["type"] == "event" and by_name["Login failed"]["severity"] == "warning"
    assert by_name["PCE health"]["type"] == "system" and by_name["PCE health"]["severity"] == "critical"
    assert by_name["Watchdog"]["rule_id"] is None and by_name["Watchdog"]["severity"] == "warning"
    full = st.get(by_name["SSH"]["id"])
    assert full["dispatch"][0]["status"] == "success"
    assert len(full["payload"]["raw_data"]) == 10          # capped
    assert full["fired_at"].endswith("Z") and "T" in full["fired_at"]
    assert full["summary"].startswith("SSH")
    assert full["criteria"] == "port 22 > 20"


def test_force_test_does_not_persist(rep):
    r, db = rep
    with patch("src.alerts.plugins.WebhookAlertPlugin.send", _ok):
        r.send_alerts(force_test=True)
    assert AlertStore(str(db)).list()["total"] == 0


def test_dlq_replay_updates_dispatch_without_duplicating(rep):
    r, db = rep
    _fill(r)
    with patch("src.alerts.plugins.WebhookAlertPlugin.send", _fail):
        r.send_alerts()
    st = AlertStore(str(db))
    assert st.list()["total"] == 4
    first = {x["rule_name"]: st.get(x["id"]) for x in st.list()["items"]}
    assert all(v["dispatch"][0]["status"] == "failed" for v in first.values())
    dlq = json.loads((db.parent / "state.json").read_text())["alert_dlq"]
    assert dlq and "alert_ids" in dlq[0]
    assert len(dlq[0]["alert_ids"]["health"]) == len(dlq[0]["buckets"]["health"]) == 2
    # no internal key leaked onto the alert items themselves (webhook serialises them wholesale)
    assert all(not k.startswith("_") for item in dlq[0]["buckets"]["traffic"] for k in item)

    r2 = Reporter(r.cm)
    with patch("src.alerts.plugins.WebhookAlertPlugin.send", _ok):
        r2.send_alerts()          # empty buckets + DLQ replay
    st = AlertStore(str(db))
    assert st.list()["total"] == 4
    after = {x["rule_name"]: st.get(x["id"]) for x in st.list()["items"]}
    for name, row in after.items():
        assert row["id"] == first[name]["id"]
        assert row["dispatch"][0]["status"] == "success"


def test_store_failure_does_not_break_dispatch(rep, monkeypatch, caplog):
    r, db = rep
    _fill(r)

    def _boom():
        raise RuntimeError("disk full")

    monkeypatch.setattr(Reporter, "alert_store_factory", staticmethod(_boom))
    with patch("src.alerts.plugins.WebhookAlertPlugin.send", _ok):
        results = r.send_alerts()
    assert results and results[0]["status"] == "success"
    assert "alert persistence failed" in caplog.text


def test_run_alerts_retention_prunes_with_archive_days(monkeypatch):
    from src.scheduler import jobs
    calls = {}

    class _Store:
        def prune(self, *, days):
            calls["days"] = days
            return 3

        def close(self):
            pass

    monkeypatch.setattr(jobs, "AlertStore", _Store)
    cm = SimpleNamespace(models=SimpleNamespace(pce_cache=SimpleNamespace(archive_retention_days=45)))
    assert jobs.run_alerts_retention(cm) == 3
    assert calls["days"] == 45
    # 0 = keep forever (the archive setting's default); prune must not run at all
    calls.clear()
    cm.models.pce_cache.archive_retention_days = 0
    assert jobs.run_alerts_retention(cm) == 0
    assert calls == {}


def test_alerts_retention_scheduled_even_when_cache_disabled(tmp_path):
    """The job must not sit under the pce_cache.enabled guard (same harness as
    tests/test_scheduler_cache_archive.py)."""
    import datetime
    from src.scheduler import build_scheduler
    cm = MagicMock()
    cm.models.pce_cache.enabled = False
    cm.models.pce_cache.db_path = str(tmp_path / "cache.sqlite")
    cm.models.siem.enabled = False
    cm.config = {}
    sched = build_scheduler(cm)
    try:
        job = sched.get_job("alerts_retention")
        assert job is not None
        assert sched.get_job("pce_cache_retention") is None      # proves the guard is off for ours only
        delta = (job.next_run_time - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
        assert 0 <= delta <= 900, "needs a startup kick like the other 24h jobs"
    finally:
        for j in list(sched.get_jobs()):
            sched.remove_job(j.id)
