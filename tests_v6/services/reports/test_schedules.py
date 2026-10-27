"""Report schedules (P5a Task 7): when each is due, one catch-up after downtime, run-now, per-schedule keep."""
from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from illumio_ops.domain.values import ReportStatus
from illumio_ops.services.reports import retention, schedules
from illumio_ops.services.reports.schedules import due_time
from illumio_ops.settings.schema import ReportSchedule
from illumio_ops.store import reports as store
from tests_v6.services.collect.conftest import configured_ctx
from tests_v6.services.reports.test_generate import FakeBuilder, _register

SID = "a" * 32


def sched(**over):
    base = {"id": SID, "name": "Weekly lateral", "enabled": True, "report_type": "lateral_posture",
            "lookback_days": 7, "frequency": "daily", "day_of_week": None, "day_of_month": None, "hour": 9,
            "minute": 30, "formats": ["html", "xlsx"], "email": False, "recipients": [], "lang": None, "keep": 30}
    base.update(over)
    return ReportSchedule.model_validate(base)


def test_daily_due():
    s = sched()
    assert due_time(s, after=datetime(2026, 10, 27, 8, tzinfo=UTC), tz=UTC) == datetime(2026, 10, 27, 9, 30, tzinfo=UTC)
    assert due_time(s, after=datetime(2026, 10, 27, 9, 30, tzinfo=UTC), tz=UTC) == \
        datetime(2026, 10, 28, 9, 30, tzinfo=UTC)


def test_weekly_and_monthly_short_month():
    weekly = sched(frequency="weekly", day_of_week=0)  # Monday
    assert due_time(weekly, after=datetime(2026, 10, 27, tzinfo=UTC), tz=UTC) == \
        datetime(2026, 11, 2, 9, 30, tzinfo=UTC)
    monthly = sched(frequency="monthly", day_of_month=31)
    assert due_time(monthly, after=datetime(2026, 11, 1, tzinfo=UTC), tz=UTC) == \
        datetime(2026, 11, 30, 9, 30, tzinfo=UTC)  # November has 30 days
    assert due_time(monthly, after=datetime(2026, 12, 31, 10, tzinfo=UTC), tz=UTC) == \
        datetime(2027, 1, 31, 9, 30, tzinfo=UTC)


def test_due_in_offset_zone():
    s = sched(hour=8, minute=0)
    plus8 = timezone(timedelta(hours=8))
    assert due_time(s, after=datetime(2026, 10, 27, tzinfo=UTC), tz=plus8) == datetime(2026, 10, 28, 0, tzinfo=UTC)
    ny = ZoneInfo("America/New_York")  # DST ends 2026-11-01 02:00 local
    assert due_time(s, after=datetime(2026, 10, 31, 13, tzinfo=UTC), tz=ny) == datetime(2026, 11, 1, 13, tzinfo=UTC)
    assert due_time(s, after=datetime(2026, 10, 30, 13, tzinfo=UTC), tz=ny) == datetime(2026, 10, 31, 12, tzinfo=UTC)


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    c = configured_ctx(tmp_path)
    def mutate(d):
        d["reports"].update(schedules=[sched().model_dump(mode="json")])
        d["display"]["timezone"] = "UTC"  # the run times below are UTC wall clock
    c.settings.update(c.settings.current().revision, mutate)
    _register(monkeypatch, FakeBuilder())
    return c


def _reports(ctx):
    with ctx.db() as conn:
        return store.list_reports(conn, limit=100, offset=0)[0]


def test_new_schedule_waits_for_its_next_time(ctx):
    t0 = datetime(2026, 10, 27, 10, tzinfo=UTC)  # after today's 09:30
    assert schedules.tick_schedules(ctx, now=t0) == []
    assert schedules.tick_schedules(ctx, now=datetime(2026, 10, 28, 9, 31, tzinfo=UTC)) != []


def test_due_after_downtime_runs_once(ctx):
    schedules.tick_schedules(ctx, now=datetime(2026, 10, 1, tzinfo=UTC))
    later = datetime(2026, 10, 27, 12, tzinfo=UTC)  # 26 missed days
    ids = schedules.tick_schedules(ctx, now=later)
    assert len(ids) == 1
    assert schedules.tick_schedules(ctx, now=later + timedelta(hours=1)) == []
    assert len(schedules.tick_schedules(ctx, now=datetime(2026, 10, 28, 9, 30, tzinfo=UTC))) == 1
    row = _reports(ctx)[-1]
    assert row.trigger == "schedule" and row.schedule_id == SID and row.params["lookback_days"] == 7


def test_disabled_not_run(ctx):
    ctx.settings.update(ctx.settings.current().revision,
                        lambda d: d["reports"]["schedules"][0].update(enabled=False))
    schedules.tick_schedules(ctx, now=datetime(2026, 10, 1, tzinfo=UTC))
    assert schedules.tick_schedules(ctx, now=datetime(2026, 10, 27, 12, tzinfo=UTC)) == []


def test_run_now_keeps_last_due(ctx):
    schedules.tick_schedules(ctx, now=datetime(2026, 10, 27, 10, tzinfo=UTC))
    rid = schedules.run_now(ctx, SID, now=datetime(2026, 10, 27, 11, tzinfo=UTC))
    assert rid is not None and schedules.run_now(ctx, "f" * 32, now=datetime(2026, 10, 27, tzinfo=UTC)) is None
    assert len(schedules.tick_schedules(ctx, now=datetime(2026, 10, 28, 9, 30, tzinfo=UTC))) == 1


def test_status_from_reports(ctx):
    for _ in range(3):
        rid = schedules.run_now(ctx, SID, now=datetime(2026, 10, 27, tzinfo=UTC))
        with ctx.db() as conn:
            store.claim_next(conn, at=datetime(2026, 10, 27, tzinfo=UTC))
            store.finish(conn, rid, status=ReportStatus.FAILED, at=datetime(2026, 10, 27, tzinfo=UTC), files=[],
                         kpis=[], error_key="rpt_err_internal")
    st = schedules.schedule_status(ctx, now=datetime(2026, 10, 27, 12, tzinfo=UTC))[SID]
    assert st.consecutive_failures == 3 and st.last_status is ReportStatus.FAILED
    assert st.next_run == datetime(2026, 10, 28, 9, 30, tzinfo=UTC)


def test_keep_prunes_per_schedule(ctx):
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["reports"]["schedules"][0].update(keep=2))
    ids = [schedules.run_now(ctx, SID, now=datetime(2026, 10, 27, tzinfo=UTC)) for _ in range(4)]
    for _ in ids:
        from illumio_ops.services.reports import generate
        generate.run_queued(ctx, now=datetime(2026, 10, 27, tzinfo=UTC))
    retention.run_report_retention(ctx, now=datetime(2026, 10, 27, 1, tzinfo=UTC))
    assert sorted(r.id for r in _reports(ctx)) == ids[2:]


@pytest.mark.parametrize("over", [{"frequency": "weekly"}, {"frequency": "monthly"},
                                  {"frequency": "daily", "day_of_week": 1}, {"formats": []},
                                  {"hour": 24}, {"id": "nothex"}, {"name": ""}])
def test_schedule_validation(over):
    with pytest.raises(ValidationError):
        sched(**over)
