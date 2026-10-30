"""Report schedules (spec §6.5 報表 排程): when each is due in the display time zone, enqueueing through the one
generation path, and a run missed while the service was down made up once — not once per missed run."""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo

from loguru import logger

from illumio_ops.domain.values import ReportStatus
from illumio_ops.services.context import AppContext
from illumio_ops.services.reports.generate import enqueue
from illumio_ops.services.reports.registry import ReportParams
from illumio_ops.settings.schema import ReportSchedule
from illumio_ops.store import reports as store

FAILURE_LOOKBACK = 50  # reports read to count a schedule's consecutive failures


def _day_matches(s: ReportSchedule, d: date) -> bool:
    if s.frequency == "weekly":
        return d.weekday() == s.day_of_week
    if s.frequency == "monthly":
        assert s.day_of_month is not None
        return d.day == min(s.day_of_month, calendar.monthrange(d.year, d.month)[1])
    return True


def _at(d: date, s: ReportSchedule, tz: tzinfo | None) -> datetime:
    local = datetime.combine(d, time(s.hour, s.minute))
    return (local.replace(tzinfo=tz) if tz is not None else local.astimezone()).astimezone(UTC)


def due_time(s: ReportSchedule, *, after: datetime, tz: tzinfo | None) -> datetime:
    """The first run time strictly after `after` (UTC), counting the hour and minute in the display zone."""
    d = after.astimezone(tz).date() - timedelta(days=1)
    for _ in range(400):  # a monthly schedule is due within 31 days; the margin covers any zone
        if _day_matches(s, d):
            at = _at(d, s, tz)
            if at > after:
                return at
        d += timedelta(days=1)
    raise RuntimeError("no run time within 400 days")  # unreachable for a valid schedule


def params_of(s: ReportSchedule) -> ReportParams:
    return ReportParams(report_type=s.report_type, lookback_days=s.lookback_days, lang=s.lang, formats=s.formats,
                        email=s.email, recipients=s.recipients, filter=s.filter, custom_id=s.custom_id)


def tick_schedules(ctx: AppContext, *, now: datetime | None = None) -> list[int]:
    """Enqueue every enabled schedule that came due since it last did; returns the new report ids. A schedule
    seen for the first time starts counting from now (it does not run for a time already past today)."""
    at = (now or datetime.now(UTC)).astimezone(UTC)
    settings = ctx.settings.current()
    tz = settings.display.zone()
    out = []
    with ctx.db() as conn:
        last = store.schedule_last_due(conn)
        store.forget_schedules_except(conn, [s.id for s in settings.reports.schedules])
    for s in settings.reports.schedules:
        if not s.enabled:
            continue
        if s.id not in last:
            with ctx.db() as conn:
                store.set_schedule_last_due(conn, s.id, at)
            continue
        nxt = due_time(s, after=last[s.id], tz=tz)
        if nxt > at:
            continue
        latest = nxt
        while (following := due_time(s, after=latest, tz=tz)) <= at:
            latest = following
        logger.info("report schedule {} ({}) is due", s.name, s.id)
        with ctx.db() as conn:
            store.set_schedule_last_due(conn, s.id, latest)
        out.append(enqueue(ctx, params_of(s), trigger="schedule", schedule_id=s.id, now=at))
    return out


def run_now(ctx: AppContext, schedule_id: str, *, now: datetime | None = None) -> int | None:
    """Enqueue the schedule's report at once (its next run time is unchanged); None for an unknown schedule."""
    at = (now or datetime.now(UTC)).astimezone(UTC)
    found = next((s for s in ctx.settings.current().reports.schedules if s.id == schedule_id), None)
    if found is None:
        return None
    return enqueue(ctx, params_of(found), trigger="schedule", schedule_id=found.id, now=at)


@dataclass(frozen=True)
class ScheduleStatus:
    next_run: datetime | None  # None: disabled
    last_report_id: int | None
    last_status: ReportStatus | None
    last_finished_at: datetime | None
    consecutive_failures: int


def schedule_status(ctx: AppContext, *, now: datetime | None = None) -> dict[str, ScheduleStatus]:
    at = (now or datetime.now(UTC)).astimezone(UTC)
    settings = ctx.settings.current()
    tz = settings.display.zone()
    out = {}
    with ctx.db() as conn:
        last_due = store.schedule_last_due(conn)
        for s in settings.reports.schedules:
            recent = store.schedule_reports(conn, s.id, limit=FAILURE_LOOKBACK)
            failures = 0
            for r in recent:
                if r.status is not ReportStatus.FAILED:
                    break
                failures += 1
            # Overdue (the next tick runs it) shows as the time it came due.
            nxt = due_time(s, after=last_due.get(s.id, at), tz=tz) if s.enabled else None
            head = recent[0] if recent else None
            out[s.id] = ScheduleStatus(next_run=nxt, last_report_id=head.id if head else None,
                                       last_status=head.status if head else None,
                                       last_finished_at=head.finished_at if head else None,
                                       consecutive_failures=failures)
    return out
