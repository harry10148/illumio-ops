"""Tests for src.dashboard_store — durable dashboard summary store."""
import json
import os
import tempfile
from unittest.mock import patch, MagicMock

import pytest

import src.dashboard_store as dashboard_store
from src.dashboard_store import read_dashboard_summary, write_dashboard_summary


# ── helpers ──────────────────────────────────────────────────────────────────

def _patch_file(tmp_path, monkeypatch):
    path = str(tmp_path / "dashboard_summary.json")
    monkeypatch.setattr(dashboard_store, "_dashboard_file", lambda: path)
    return path


# ── unit tests ────────────────────────────────────────────────────────────────

def test_read_returns_empty_dict_when_missing(tmp_path, monkeypatch):
    _patch_file(tmp_path, monkeypatch)
    assert read_dashboard_summary() == {}


def test_write_then_read_roundtrip(tmp_path, monkeypatch):
    _patch_file(tmp_path, monkeypatch)
    written = write_dashboard_summary(lambda d: {**d, "ven_summary": {"total": 10}})
    assert written == {"ven_summary": {"total": 10}}
    assert read_dashboard_summary() == {"ven_summary": {"total": 10}}


def test_updater_callable_preserves_other_keys(tmp_path, monkeypatch):
    path = _patch_file(tmp_path, monkeypatch)
    # pre-seed with another key
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"other_key": "preserved"}, f)
    write_dashboard_summary(lambda d: {**d, "ven_summary": {"total": 5}})
    result = read_dashboard_summary()
    assert result["other_key"] == "preserved"
    assert result["ven_summary"]["total"] == 5


def test_plain_dict_updater_merges(tmp_path, monkeypatch):
    path = _patch_file(tmp_path, monkeypatch)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"existing": 1}, f)
    write_dashboard_summary({"new_key": 2})
    result = read_dashboard_summary()
    assert result["existing"] == 1
    assert result["new_key"] == 2


def test_read_returns_empty_dict_on_invalid_json(tmp_path, monkeypatch):
    path = _patch_file(tmp_path, monkeypatch)
    with open(path, "w", encoding="utf-8") as f:
        f.write("not valid json{{")
    assert read_dashboard_summary() == {}


def test_write_creates_logs_dir_if_missing(tmp_path, monkeypatch):
    nested = str(tmp_path / "newdir" / "dashboard_summary.json")
    monkeypatch.setattr(dashboard_store, "_dashboard_file", lambda: nested)
    write_dashboard_summary(lambda d: {**d, "x": 1})
    assert os.path.exists(nested)
    assert json.load(open(nested))["x"] == 1


def test_write_is_atomic_no_partial_file(tmp_path, monkeypatch):
    """os.replace is atomic; the target should never hold a partial write."""
    path = _patch_file(tmp_path, monkeypatch)
    # Write a large enough payload and verify the file is complete after
    big_data = {"data": list(range(10000))}
    write_dashboard_summary(lambda d: {**d, **big_data})
    result = read_dashboard_summary()
    assert result["data"] == list(range(10000))


# ── integration: run_ven_summary writes to dashboard store ─────────────────

def _wl(host, hb_hours, status="active", os_type="linux", mode="enforced"):
    return {
        "hostname": host,
        "interfaces": [{"address": "10.0.0.1"}],
        "labels": [],
        "os_type": os_type,
        "agent": {
            "status": {
                "status": status,
                "hours_since_last_heartbeat": hb_hours,
                "security_policy_sync_state": "active",
                "last_heartbeat_on": "2026-05-31T00:00:00Z",
                "agent_version": "21.5.35",
            }
        },
        "enforcement_mode": mode,
    }


def test_run_ven_summary_writes_to_dashboard_store(tmp_path, monkeypatch):
    """run_ven_summary must write ven_summary to dashboard store, not state.json."""
    from src.scheduler.jobs import run_ven_summary

    dashboard_path = str(tmp_path / "dashboard_summary.json")
    state_path = str(tmp_path / "state.json")

    monkeypatch.setattr(dashboard_store, "_dashboard_file", lambda: dashboard_path)

    cm = MagicMock()
    cm.config = {"settings": {"timezone": "UTC"}}
    api = MagicMock()
    api.fetch_managed_workloads.return_value = [
        _wl("a", 0.2, os_type="linux", mode="enforced"),
        _wl("b", 0.3, os_type="windows", mode="illuminated"),
        _wl("c", 99.0, os_type="linux", mode="enforced"),
    ]
    api.__enter__.return_value = api
    api.__exit__.return_value = False

    with patch("src.scheduler.jobs.ApiClient", return_value=api), \
         patch("src.scheduler.jobs._resolve_state_file", return_value=state_path):
        run_ven_summary(cm)

    # Dashboard store must have the summary
    ds = read_dashboard_summary()
    assert "ven_summary" in ds, "ven_summary must be in dashboard store"
    vs = ds["ven_summary"]
    assert vs["total"] == 3
    assert vs["online"] == 2
    assert vs["offline"] == 1
    assert "os_distribution" in vs
    assert "enforcement_distribution" in vs

    # state.json must NOT contain ven_summary
    if os.path.exists(state_path):
        state = json.load(open(state_path))
        assert "ven_summary" not in state, "ven_summary must NOT be written to state.json"


def test_run_ven_summary_error_writes_last_error_to_dashboard_store(tmp_path, monkeypatch):
    """On failure, last_error should be recorded in the dashboard store."""
    from src.scheduler.jobs import run_ven_summary
    from src.dashboard_store import write_dashboard_summary as wds

    dashboard_path = str(tmp_path / "dashboard_summary.json")
    state_path = str(tmp_path / "state.json")

    monkeypatch.setattr(dashboard_store, "_dashboard_file", lambda: dashboard_path)

    # Pre-seed last-good data
    monkeypatch.setattr(dashboard_store, "_dashboard_file", lambda: dashboard_path)
    wds(lambda d: {**d, "ven_summary": {"total": 7, "online": 7, "offline": 0}})

    cm = MagicMock()
    cm.config = {"settings": {}}
    api = MagicMock()
    api.__enter__.return_value = api
    api.__exit__.return_value = False
    api.fetch_managed_workloads.side_effect = RuntimeError("PCE unreachable")

    with patch("src.scheduler.jobs.ApiClient", return_value=api), \
         patch("src.scheduler.jobs._resolve_state_file", return_value=state_path):
        run_ven_summary(cm)

    ds = read_dashboard_summary()
    vs = ds["ven_summary"]
    assert vs["total"] == 7          # last-good counts preserved
    assert "last_error" in vs
    assert "PCE unreachable" in vs["last_error"]
