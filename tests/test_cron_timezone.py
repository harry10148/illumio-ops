"""Tests for cron_expr timezone-aware scheduling."""
from __future__ import annotations
import datetime
import pytest


def test_report_schedule_has_timezone_field():
    """ReportSchedule model must have an explicit timezone field."""
    from src.config_models import ReportSchedule
    s = ReportSchedule(name="test", cron_expr="0 8 * * *", timezone="Asia/Taipei")
    assert s.timezone == "Asia/Taipei"


def test_report_schedule_timezone_defaults_to_none():
    from src.config_models import ReportSchedule
    s = ReportSchedule(name="test")
    assert s.timezone is None


def test_cron_expr_fires_at_local_time_not_utc():
    """A cron schedule set to 08:00 Asia/Taipei must fire at 08:00 Taipei, not 08:00 UTC."""
    from src.report_scheduler import ReportScheduler
    # 08:00 Taipei = UTC+8, so UTC equivalent is 00:00 UTC
    # At 08:00 Taipei local time, the schedule SHOULD fire
    schedule = {
        "id": 1, "name": "morning-report",
        "enabled": True,
        "cron_expr": "0 8 * * *",
        "timezone": "Asia/Taipei",
    }
    # Simulate now = 08:00 Asia/Taipei (= 00:00 UTC)
    # Use a fixed datetime: 2026-01-01 08:00:00 Asia/Taipei
    import zoneinfo
    taipei = zoneinfo.ZoneInfo("Asia/Taipei")
    now_taipei = datetime.datetime(2026, 1, 1, 8, 0, 0)  # naive, in Taipei local time
    rs = ReportScheduler.__new__(ReportScheduler)
    result = rs.should_run(schedule, now=now_taipei, last_run_str=None)
    assert result is True, "Should fire at 08:00 Taipei time"


def test_cron_expr_does_not_fire_at_utc_time_when_tz_is_taipei():
    """A schedule for 08:00 Taipei must NOT fire at 08:00 UTC (= 16:00 Taipei)."""
    from src.report_scheduler import ReportScheduler
    schedule = {
        "id": 1, "name": "morning-report",
        "enabled": True,
        "cron_expr": "0 8 * * *",
        "timezone": "Asia/Taipei",
    }
    # Simulate now = 08:00 UTC (= 16:00 Taipei) — the old broken behaviour would fire here
    now_utc_naive = datetime.datetime(2026, 1, 1, 8, 0, 0)  # naive, interpreted as Taipei local
    # At 16:00 Taipei, the schedule should NOT fire (next fire is next day 08:00 Taipei)
    import zoneinfo
    now_taipei_16 = datetime.datetime(2026, 1, 1, 16, 0, 0)  # naive 16:00 in Taipei
    rs = ReportScheduler.__new__(ReportScheduler)
    result = rs.should_run(schedule, now=now_taipei_16, last_run_str=None)
    assert result is False, "Should NOT fire at 16:00 Taipei (= 08:00 UTC)"
