import json, os, tempfile
from unittest.mock import patch, MagicMock

import src.dashboard_store as dashboard_store


def _wl(host, hb_hours, status="active"):
    return {"hostname": host,
            "interfaces": [{"address": "10.0.0.1"}],
            "labels": [],
            "agent": {"status": {"status": status,
                                 "hours_since_last_heartbeat": hb_hours,
                                 "security_policy_sync_state": "active",
                                 "last_heartbeat_on": "2026-05-31T00:00:00Z",
                                 "agent_version": "21.5.35"}}}


def test_run_ven_summary_writes_counts(tmp_path, monkeypatch):
    from src.scheduler.jobs import run_ven_summary

    dashboard_path = str(tmp_path / "dashboard_summary.json")
    state_file = str(tmp_path / "state.json")

    monkeypatch.setattr(dashboard_store, "_dashboard_file", lambda: dashboard_path)

    cm = MagicMock()
    cm.config = {"settings": {"timezone": "UTC"}}
    api = MagicMock()
    api.fetch_managed_workloads.return_value = [
        _wl("a", 0.2), _wl("b", 0.3), _wl("c", 99.0)]  # 2 online, 1 offline
    api.__enter__.return_value = api
    api.__exit__.return_value = False

    with patch("src.scheduler.jobs.ApiClient", return_value=api), \
         patch("src.scheduler.jobs._resolve_state_file", return_value=state_file):
        run_ven_summary(cm)

    s = json.load(open(dashboard_path))["ven_summary"]
    assert s["total"] == 3 and s["online"] == 2 and s["offline"] == 1
    assert s["degraded"] == 0
    assert len(s["attention"]) == 1 and s["attention"][0]["host"] == "c"
    assert s["updated_at"]


def test_run_ven_summary_preserves_last_good_on_error(tmp_path, monkeypatch):
    from src.scheduler.jobs import run_ven_summary
    from src.dashboard_store import write_dashboard_summary

    dashboard_path = str(tmp_path / "dashboard_summary.json")
    state_file = str(tmp_path / "state.json")

    monkeypatch.setattr(dashboard_store, "_dashboard_file", lambda: dashboard_path)
    write_dashboard_summary(lambda d: {**d, "ven_summary": {"total": 5, "online": 5, "offline": 0}})

    cm = MagicMock(); cm.config = {"settings": {}}
    api = MagicMock(); api.__enter__.return_value = api; api.__exit__.return_value = False
    api.fetch_managed_workloads.side_effect = RuntimeError("PCE down")

    with patch("src.scheduler.jobs.ApiClient", return_value=api), \
         patch("src.scheduler.jobs._resolve_state_file", return_value=state_file):
        run_ven_summary(cm)

    s = json.load(open(dashboard_path))["ven_summary"]
    assert s["total"] == 5          # last-good counts preserved
    assert "last_error" in s and "PCE down" in s["last_error"]
