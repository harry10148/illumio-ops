"""Tests for cron_expr timezone-aware scheduling."""
from __future__ import annotations
import datetime
import pytest
from freezegun import freeze_time


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
    """08:00 UTC = 16:00 Taipei; a schedule for 08:00 Taipei must NOT fire at 16:00 Taipei."""
    from src.report_scheduler import ReportScheduler
    schedule = {
        "id": 1, "name": "morning-report",
        "cron_expr": "0 8 * * *",
        "timezone": "Asia/Taipei",
    }
    # 16:00 Taipei local — next fire is tomorrow at 08:00 Taipei
    now_taipei_16 = datetime.datetime(2026, 1, 1, 16, 0, 0)
    rs = ReportScheduler.__new__(ReportScheduler)
    assert rs.should_run(schedule, now=now_taipei_16, last_run_str=None) is False


def test_cron_fires_at_midnight_utc_when_tz_is_taipei():
    """08:00 Taipei = 00:00 UTC: schedule for 08:00 Taipei MUST fire when now=08:00 Taipei local.
    The old UTC-hardcoded code would NOT fire here because it would treat 08:00 naive as
    08:00 UTC (= 16:00 Taipei) and would not match cron 0 8 * * *.
    The new code fires because now=08:00 naive is interpreted as 08:00 Asia/Taipei.
    """
    from src.report_scheduler import ReportScheduler
    schedule = {
        "id": 1, "name": "morning-report",
        "enabled": True,
        "cron_expr": "0 8 * * *",
        "timezone": "Asia/Taipei",
    }
    # 08:00 Taipei local = 00:00 UTC — new code fires, old UTC-hardcoded code would not
    now = datetime.datetime(2026, 1, 1, 8, 0, 0)
    rs = ReportScheduler.__new__(ReportScheduler)
    assert rs.should_run(schedule, now=now, last_run_str=None) is True


def test_cron_fires_at_eight_utc_when_no_tz():
    """Without timezone, schedule defaults to UTC: 08:00 naive fires at 08:00 UTC.
    Verifies that UTC default behavior is preserved.
    """
    from src.report_scheduler import ReportScheduler
    schedule = {
        "id": 1, "name": "morning-report",
        "enabled": True,
        "cron_expr": "0 8 * * *",
        # no timezone key
    }
    now = datetime.datetime(2026, 1, 1, 8, 0, 0)
    rs = ReportScheduler.__new__(ReportScheduler)
    assert rs.should_run(schedule, now=now, last_run_str=None) is True


# ─── Bug: _now_in_schedule_tz mishandles IANA names (Important, 2026-07-02) ────
#
# _now_in_schedule_tz's offset resolver only recognised 'local'/'UTC'/'UTC±N';
# an IANA name like 'Asia/Taipei' silently fell through to offset 0, so the
# naive 'now' it produced was UTC wall-clock mislabeled as Taipei local. The
# cron branch in should_run() then tagged that UTC wall-clock with the Taipei
# tzinfo, shifting every cron trigger by a full UTC offset (09:00 Asia/Taipei
# actually fired at 09:00 UTC = 17:00 Taipei). These tests freeze real wall-clock
# time and go through the *real* _now_in_schedule_tz (unlike the tests above,
# which inject `now` directly and therefore never exercised the bug).

def test_now_in_schedule_tz_resolves_iana_local_wall_clock():
    """At a frozen UTC instant, _now_in_schedule_tz('Asia/Taipei') must return
    the actual Taipei wall-clock (UTC+8), not the UTC wall-clock mislabeled."""
    from src.report_scheduler import _now_in_schedule_tz
    with freeze_time("2026-01-01T01:00:00+00:00"):  # 09:00 Asia/Taipei
        now = _now_in_schedule_tz("Asia/Taipei")
        assert (now.hour, now.minute) == (9, 0)


def test_cron_iana_tz_fires_at_correct_local_time_through_real_now():
    """End-to-end (real _now_in_schedule_tz, not an injected `now`): a cron
    schedule for 09:00 Asia/Taipei must fire when the frozen UTC instant is
    01:00 UTC (= 09:00 Taipei), not when it is 09:00 UTC (= 17:00 Taipei)."""
    from src.report_scheduler import ReportScheduler, _now_in_schedule_tz
    schedule = {
        "id": 1, "name": "morning-report", "enabled": True,
        "cron_expr": "0 9 * * *", "timezone": "Asia/Taipei",
    }
    rs = ReportScheduler.__new__(ReportScheduler)

    with freeze_time("2026-01-01T01:00:00+00:00"):  # 09:00 Asia/Taipei — should fire
        now = _now_in_schedule_tz("Asia/Taipei")
        assert rs.should_run(schedule, now, last_run_str=None) is True

    with freeze_time("2026-01-01T09:00:00+00:00"):  # 17:00 Asia/Taipei — must NOT fire
        now = _now_in_schedule_tz("Asia/Taipei")
        assert rs.should_run(schedule, now, last_run_str=None) is False
