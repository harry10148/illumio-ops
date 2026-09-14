import json, os, tempfile
from unittest.mock import patch, MagicMock

import pytest

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
        # 失敗要先寫 last_error（保留 last-good counts），再 re-raise 給
        # _instrument 記 job_health status=error
        with pytest.raises(RuntimeError):
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
        with pytest.raises(RuntimeError):
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


# ── fleet 快照（Task 2）─────────────────────────────────────────────────────

def test_run_ven_summary_also_writes_the_fleet_snapshot(tmp_path, monkeypatch):
    """同一次 fetch 產出 ven_summary 與 fleet，不得多抓一次 workloads。

    這支同時守著「不新增第二次全量抓取」——`fetch_managed_workloads` 只能被
    呼叫一次。多一次全量抓取在 1 萬台的環境是幾分鐘與一次 PCE 負載。
    """
    from src.scheduler.jobs import run_ven_summary

    dashboard_path = str(tmp_path / "dashboard_summary.json")
    monkeypatch.setattr(dashboard_store, "_dashboard_file", lambda: dashboard_path)

    cm = MagicMock()
    cm.config = {"settings": {"timezone": "UTC", "fleet_target_ven_version": "21.5.35"}}
    api = MagicMock()
    api.fetch_managed_workloads.return_value = [_wl("a", 0.2), _wl("b", 0.3), _wl("c", 99.0)]
    api.__enter__.return_value = api
    api.__exit__.return_value = False

    with patch("src.scheduler.jobs.ApiClient", return_value=api), \
         patch("src.scheduler.jobs._resolve_state_file", return_value=str(tmp_path / "s.json")):
        run_ven_summary(cm)

    assert api.fetch_managed_workloads.call_count == 1

    fleet = json.load(open(dashboard_path))["fleet"]
    assert fleet["total"] == 3
    assert fleet["managed_online"] == 2
    assert fleet["versions"]["target"] == "21.5.35"
    assert fleet["versions"]["on_target"] == 3
    assert fleet["updated_at"]
    assert len(fleet["workloads_index"]) == 3


def test_fleet_target_defaults_to_none_when_the_setting_is_blank(tmp_path, monkeypatch):
    """設定是空字串時 target 必須是 None，不是 ""。

    空字串會讓 `version == target` 對每一台「版本也是空」的工作負載成立，
    on_target 因此虛報。
    """
    from src.scheduler.jobs import run_ven_summary

    dashboard_path = str(tmp_path / "dashboard_summary.json")
    monkeypatch.setattr(dashboard_store, "_dashboard_file", lambda: dashboard_path)

    cm = MagicMock()
    cm.config = {"settings": {"timezone": "UTC", "fleet_target_ven_version": "   "}}
    api = MagicMock()
    api.fetch_managed_workloads.return_value = [_wl("a", 0.2)]
    api.__enter__.return_value = api
    api.__exit__.return_value = False

    with patch("src.scheduler.jobs.ApiClient", return_value=api), \
         patch("src.scheduler.jobs._resolve_state_file", return_value=str(tmp_path / "s.json")):
        run_ven_summary(cm)

    fleet = json.load(open(dashboard_path))["fleet"]
    assert fleet["versions"]["target"] is None
    assert fleet["versions"]["needs_upgrade"] is None


def test_a_pce_failure_keeps_the_last_good_fleet_and_records_the_error(tmp_path, monkeypatch):
    """PCE 掛掉時保留上一份 fleet，只補 last_error／updated_at——不得寫 0。

    比照 ven_summary 的既有行為。把失敗寫成「0 台」會讓看板顯示一個從未
    存在過的車隊，而那正是 `raise_on_error` 當初被加上去的原因。
    """
    from src.scheduler.jobs import run_ven_summary

    dashboard_path = str(tmp_path / "dashboard_summary.json")
    monkeypatch.setattr(dashboard_store, "_dashboard_file", lambda: dashboard_path)
    with open(dashboard_path, "w") as fh:
        json.dump({"fleet": {"total": 7, "managed_online": 7}}, fh)

    cm = MagicMock()
    cm.config = {"settings": {"timezone": "UTC"}}
    api = MagicMock()
    api.fetch_managed_workloads.side_effect = RuntimeError("PCE down")
    api.__enter__.return_value = api
    api.__exit__.return_value = False

    with patch("src.scheduler.jobs.ApiClient", return_value=api), \
         patch("src.scheduler.jobs._resolve_state_file", return_value=str(tmp_path / "s.json")):
        # 先落地 last_error，再 re-raise 給 _instrument 記 job_health status=error
        with pytest.raises(RuntimeError):
            run_ven_summary(cm)

    fleet = json.load(open(dashboard_path))["fleet"]
    assert fleet["total"] == 7, "失敗把上一份好資料洗成 0 了"
    assert "PCE down" in fleet["last_error"]
    assert fleet["updated_at"]


def test_index_cap_setting_reaches_the_analysis(tmp_path, monkeypatch):
    from src.scheduler.jobs import run_ven_summary

    dashboard_path = str(tmp_path / "dashboard_summary.json")
    monkeypatch.setattr(dashboard_store, "_dashboard_file", lambda: dashboard_path)

    cm = MagicMock()
    cm.config = {"settings": {"timezone": "UTC", "fleet_index_cap": 2}}
    api = MagicMock()
    api.fetch_managed_workloads.return_value = [_wl("a", 0.2), _wl("b", 0.3), _wl("c", 0.4)]
    api.__enter__.return_value = api
    api.__exit__.return_value = False

    with patch("src.scheduler.jobs.ApiClient", return_value=api), \
         patch("src.scheduler.jobs._resolve_state_file", return_value=str(tmp_path / "s.json")):
        run_ven_summary(cm)

    fleet = json.load(open(dashboard_path))["fleet"]
    assert fleet["index_truncated"] is True
    assert fleet["workloads_index"] == []
    assert fleet["total"] == 3
