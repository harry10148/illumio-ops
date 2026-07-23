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


def test_ven_summary_attention_reasons_localized_to_configured_language(tmp_path, monkeypatch):
    """Attention reasons render in the app's configured language, not hardcoded English."""
    from src.scheduler.jobs import run_ven_summary

    dashboard_path = str(tmp_path / "dashboard_summary.json")
    state_file = str(tmp_path / "state.json")
    monkeypatch.setattr(dashboard_store, "_dashboard_file", lambda: dashboard_path)

    cm = MagicMock()
    cm.config = {"settings": {"language": "zh_TW"}}
    api = MagicMock()
    stale = _wl("stale-host", 99.0)                       # offline by stale heartbeat
    no_status = {"hostname": "no-status-host",            # offline by unknown status
                 "agent": {"status": {"status": "", "hours_since_last_heartbeat": None}}}
    api.fetch_managed_workloads.return_value = [stale, no_status]
    api.__enter__.return_value = api
    api.__exit__.return_value = False

    with patch("src.scheduler.jobs.ApiClient", return_value=api), \
         patch("src.scheduler.jobs._resolve_state_file", return_value=state_file):
        run_ven_summary(cm)

    s = json.load(open(dashboard_path))["ven_summary"]
    reasons = {a["host"]: a["reason"] for a in s["attention"]}
    assert reasons["stale-host"] == "99 小時無心跳"
    assert reasons["no-status-host"] == "狀態：未知"


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


def test_ven_summary_writes_computed_at_on_success_only(tmp_path, monkeypatch):
    """computed_at = last successful computation time. updated_at is bumped by
    _mark_err on every attempt (success or failure), so it can't be used as a
    freshness signal — computed_at must only move on success, staying frozen
    while the job fails or hangs so the GUI can flag the frozen numbers."""
    from src.scheduler.jobs import run_ven_summary

    dashboard_path = str(tmp_path / "dashboard_summary.json")
    state_file = str(tmp_path / "state.json")
    monkeypatch.setattr(dashboard_store, "_dashboard_file", lambda: dashboard_path)

    cm = MagicMock()
    cm.config = {"settings": {}}
    api = MagicMock()
    api.fetch_managed_workloads.return_value = [_wl("a", 0.2), _wl("b", 0.3)]
    api.__enter__.return_value = api
    api.__exit__.return_value = False

    # Success run: computed_at gets written.
    with patch("src.scheduler.jobs.ApiClient", return_value=api), \
         patch("src.scheduler.jobs._resolve_state_file", return_value=state_file):
        run_ven_summary(cm)

    s = json.load(open(dashboard_path))["ven_summary"]
    assert s["computed_at"].endswith("Z")
    computed_at_after_success = s["computed_at"]

    # Failure run: computed_at must not change; last_error/updated_at do.
    api.fetch_managed_workloads.side_effect = RuntimeError("PCE down")
    with patch("src.scheduler.jobs.ApiClient", return_value=api), \
         patch("src.scheduler.jobs._resolve_state_file", return_value=state_file):
        run_ven_summary(cm)

    s2 = json.load(open(dashboard_path))["ven_summary"]
    assert s2["computed_at"] == computed_at_after_success   # frozen, not updated
    assert "last_error" in s2 and "PCE down" in s2["last_error"]
    assert s2["updated_at"]


def test_run_ven_summary_uses_raise_on_error(tmp_path, monkeypatch):
    """fetch 必須帶 raise_on_error=True：HTTP 失敗要走 last_error 路徑，
    不得以空清單偽裝成「0 個 workload」。"""
    from src.scheduler.jobs import run_ven_summary

    dashboard_path = str(tmp_path / "dashboard_summary.json")
    state_file = str(tmp_path / "state.json")
    monkeypatch.setattr(dashboard_store, "_dashboard_file", lambda: dashboard_path)

    cm = MagicMock()
    cm.config = {"settings": {"timezone": "UTC"}}
    api = MagicMock()
    api.fetch_managed_workloads.return_value = []
    api.__enter__.return_value = api
    api.__exit__.return_value = False

    with patch("src.scheduler.jobs.ApiClient", return_value=api), \
         patch("src.scheduler.jobs._resolve_state_file", return_value=state_file):
        run_ven_summary(cm)

    _args, kwargs = api.fetch_managed_workloads.call_args
    assert kwargs.get("raise_on_error") is True
