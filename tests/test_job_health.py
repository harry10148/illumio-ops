"""job 健康儲存（2026-07-16 可觀測性 backlog）：每個排程 job 記錄
last_run/status，讓「應跑未跑」在 GUI 可見（archive 事故的根治配套）。"""
from __future__ import annotations

import datetime
import json

import pytest

from src import job_health


@pytest.fixture()
def jh_file(tmp_path, monkeypatch):
    path = str(tmp_path / "job_health.json")
    monkeypatch.setattr(job_health, "_job_health_file", lambda: path)
    return path


def test_record_and_load_roundtrip(jh_file):
    job_health.record_job_registered("pce_cache_archive", 86400)
    job_health.record_job_run("pce_cache_archive", "ok", detail="rows=12")
    data = job_health.load_job_health()
    entry = data["pce_cache_archive"]
    assert entry["last_status"] == "ok"
    assert entry["detail"] == "rows=12"
    assert entry["interval_seconds"] == 86400
    assert entry["last_run"].endswith("Z")
    assert entry["registered_at"].endswith("Z")


def test_registered_does_not_clobber_last_run(jh_file):
    """重啟時 record_job_registered 不得洗掉上一輪的 last_run/status。"""
    job_health.record_job_run("ven_summary", "ok", interval_seconds=300)
    before = job_health.load_job_health()["ven_summary"]["last_run"]
    job_health.record_job_registered("ven_summary", 300)
    after = job_health.load_job_health()["ven_summary"]
    assert after["last_run"] == before
    assert after["last_status"] == "ok"
    assert after["interval_seconds"] == 300


def test_error_status_recorded(jh_file):
    job_health.record_job_run("monitor_cycle", "error", detail="boom", interval_seconds=30)
    entry = job_health.load_job_health()["monitor_cycle"]
    assert entry["last_status"] == "error"
    assert entry["detail"] == "boom"


def test_write_throttle_skips_recent(jh_file):
    """秒級 tick job（monitor 30s/siem tick）不得每次都重寫磁碟：
    60 秒內的重複 ok 寫入直接略過。"""
    job_health.record_job_run("siem_dispatch", "ok", interval_seconds=5)
    first = json.load(open(jh_file))["siem_dispatch"]["last_run"]
    job_health.record_job_run("siem_dispatch", "ok", interval_seconds=5)
    second = json.load(open(jh_file))["siem_dispatch"]["last_run"]
    assert second == first


def test_write_throttle_never_skips_errors_or_status_change(jh_file):
    job_health.record_job_run("siem_dispatch", "ok", interval_seconds=5)
    job_health.record_job_run("siem_dispatch", "error", detail="x", interval_seconds=5)
    assert job_health.load_job_health()["siem_dispatch"]["last_status"] == "error"


def test_scheduler_jobs_are_instrumented(tmp_path, monkeypatch):
    """build_scheduler 註冊的每個 job 都必須：(a) 種下 registered 記錄；
    (b) func 為 instrument wrapper（執行時會寫 last_run）。"""
    path = str(tmp_path / "job_health.json")
    monkeypatch.setattr(job_health, "_job_health_file", lambda: path)
    from unittest.mock import MagicMock
    from src.scheduler import build_scheduler
    cm = MagicMock()
    cm.models.pce_cache.enabled = True
    cm.models.pce_cache.db_path = str(tmp_path / "c.sqlite")
    cm.models.pce_cache.archive_enabled = True
    cm.models.pce_cache.archive_dir = str(tmp_path / "archive")
    cm.models.pce_cache.archive_interval_hours = 24
    cm.models.pce_cache.archive_gzip_after_days = 7
    cm.models.pce_cache.archive_retention_days = 0
    cm.models.pce_cache.events_poll_interval_seconds = 300
    cm.models.pce_cache.traffic_poll_interval_seconds = 3600
    cm.models.siem.enabled = False
    cm.config = {}
    sched = build_scheduler(cm)
    try:
        data = job_health.load_job_health()
        for job in sched.get_jobs():
            assert job.id in data, f"{job.id} 未種下 registered 記錄"
            assert data[job.id]["last_status"] in ("registered", "ok", "error")
            assert data[job.id]["interval_seconds"] > 0
    finally:
        for j in list(sched.get_jobs()):
            sched.remove_job(j.id)


def test_prune_job_health_removes_orphans(jh_file):
    """job 改名/停用後的殘留條目會被 overview 永久判 warn——
    prune 以本次註冊集合修剪。"""
    job_health.record_job_registered("keep_me", 60)
    job_health.record_job_run("keep_me", "ok")
    job_health.record_job_registered("orphan", 60)
    job_health.prune_job_health(["keep_me"])
    data = job_health.load_job_health()
    assert "keep_me" in data
    assert "orphan" not in data


def test_build_scheduler_prunes_orphans(tmp_path, monkeypatch):
    """build_scheduler 完成註冊後，儲存內不在本次註冊集合的條目必須消失。"""
    path = str(tmp_path / "job_health.json")
    monkeypatch.setattr(job_health, "_job_health_file", lambda: path)
    job_health.record_job_registered("renamed_away_job", 300)
    from unittest.mock import MagicMock
    from src.scheduler import build_scheduler
    cm = MagicMock()
    cm.models.pce_cache.enabled = True
    cm.models.pce_cache.db_path = str(tmp_path / "c.sqlite")
    cm.models.pce_cache.archive_enabled = True
    cm.models.pce_cache.archive_dir = str(tmp_path / "archive")
    cm.models.pce_cache.archive_interval_hours = 24
    cm.models.pce_cache.archive_gzip_after_days = 7
    cm.models.pce_cache.archive_retention_days = 0
    cm.models.pce_cache.events_poll_interval_seconds = 300
    cm.models.pce_cache.traffic_poll_interval_seconds = 3600
    cm.models.siem.enabled = False
    cm.config = {}
    sched = build_scheduler(cm)
    try:
        data = job_health.load_job_health()
        assert "renamed_away_job" not in data
        assert all(job.id in data for job in sched.get_jobs())
    finally:
        for j in list(sched.get_jobs()):
            sched.remove_job(j.id)


def test_run_tls_renew_check_invokes_helper(tmp_path, monkeypatch):
    from unittest.mock import MagicMock, patch
    from src.scheduler.jobs import run_tls_renew_check
    cm = MagicMock()
    cm.config = {"web_gui": {"tls": {"enabled": True, "self_signed": True,
                                      "auto_renew": True, "auto_renew_days": 30}}}
    with patch("src.gui._helpers._maybe_auto_renew_self_signed",
               return_value=(True, 396)) as mock_renew:
        run_tls_renew_check(cm)
    mock_renew.assert_called_once()
    _args, kwargs = mock_renew.call_args
    assert kwargs.get("threshold_days") == 30


def test_run_tls_renew_check_swallows_exceptions():
    from unittest.mock import MagicMock, patch
    from src.scheduler.jobs import run_tls_renew_check
    cm = MagicMock()
    cm.config = {"web_gui": {"tls": {"enabled": True, "self_signed": True,
                                      "auto_renew": True}}}
    with patch("src.gui._helpers._maybe_auto_renew_self_signed",
               side_effect=RuntimeError("boom")), \
         patch("src.scheduler.jobs.logger") as mock_logger:
        run_tls_renew_check(cm)
    assert mock_logger.exception.called
