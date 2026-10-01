"""排程報表的保留與時間區間。"""
from __future__ import annotations

import datetime as dt
import os
import time
from types import SimpleNamespace

from src.config_models import ConfigSchema
from src.report_scheduler import ReportScheduler, _report_window


def _sched(tmp_path, retention_days=30):
    cm = SimpleNamespace(models=ConfigSchema())
    cm.config = {"report": {"output_dir": str(tmp_path), "retention_days": retention_days}, "settings": {}}
    return ReportScheduler(cm, reporter=None)


def _touch(path, age_days=0):
    path.write_text("x")
    t = time.time() - age_days * 86400
    os.utime(path, (t, t))


def test_count_prune_covers_xlsx_and_csv_zip_as_one_report(tmp_path):
    s = _sched(tmp_path)
    for i, day in enumerate(("2026-09-01", "2026-09-02", "2026-09-03")):
        stamp = f"{day}_0800"
        for name in (f"illumio_audit_report_{stamp}.html", f"Illumio_Audit_Report_{stamp}.xlsx",
                     f"Illumio_Audit_Report_{stamp}_raw.zip"):
            _touch(tmp_path / name, age_days=3 - i)
    s._prune_by_count(str(tmp_path), "audit", max_reports=1)
    left = sorted(os.listdir(tmp_path))
    assert left == ["Illumio_Audit_Report_2026-09-03_0800.xlsx",
                    "Illumio_Audit_Report_2026-09-03_0800_raw.zip",
                    "illumio_audit_report_2026-09-03_0800.html"]


def test_age_prune_removes_old_xlsx_but_keeps_dashboard_summaries(tmp_path):
    s = _sched(tmp_path, retention_days=30)
    _touch(tmp_path / "Illumio_VEN_Report_2026-01-01_0800.xlsx", age_days=60)
    _touch(tmp_path / "latest_audit_summary.json", age_days=60)
    _touch(tmp_path / "latest_snapshot.json", age_days=60)
    s._prune_old_reports(str(tmp_path))
    assert sorted(os.listdir(tmp_path)) == ["latest_audit_summary.json", "latest_snapshot.json"]


def test_shared_traffic_xlsx_not_pruned_by_security_schedule_without_scope(tmp_path):
    s = _sched(tmp_path)
    _touch(tmp_path / "Illumio_Traffic_Report_2026-09-01_0800.xlsx", age_days=5)
    _touch(tmp_path / "Illumio_Traffic_Report_SecurityRisk_2026-09-02_0800.html", age_days=1)
    s._prune_by_count(str(tmp_path), "security_risk", max_reports=1)
    assert "Illumio_Traffic_Report_2026-09-01_0800.xlsx" in os.listdir(tmp_path)


def test_window_is_complete_days_in_schedule_timezone():
    now = dt.datetime(2026, 10, 1, 1, 30, tzinfo=dt.timezone.utc)  # 台北 09:30
    start, end, s_label, e_label = _report_window(7, "Asia/Taipei", now_utc=now)
    assert (s_label, e_label) == ("2026-09-24", "2026-09-30")
    assert start == "2026-09-23T16:00:00Z"   # 09-24 00:00 +08
    assert end == "2026-09-30T15:59:59Z"     # 09-30 23:59:59 +08，不含今天、不跨未來


def test_consecutive_weekly_windows_do_not_overlap():
    a = _report_window(7, "UTC", now_utc=dt.datetime(2026, 10, 1, 8, tzinfo=dt.timezone.utc))
    b = _report_window(7, "UTC", now_utc=dt.datetime(2026, 10, 8, 8, tzinfo=dt.timezone.utc))
    assert a[1] < b[0]
    assert (dt.datetime.fromisoformat(b[0].replace("Z", "+00:00"))
            - dt.datetime.fromisoformat(a[1].replace("Z", "+00:00"))).total_seconds() == 1
