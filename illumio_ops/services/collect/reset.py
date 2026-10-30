"""Switching to another PCE: everything collected from the old one goes, in one place.

The flow database is rebuilt (it holds only PCE-derived data); in the application database the
PCE-derived tables are listed once below and cleared through their owners; archive files are
moved aside, never deleted (they are the customer's records).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from loguru import logger

from illumio_ops.services import pce_health
from illumio_ops.services.collect.guard import normalize_target
from illumio_ops.services.context import AppContext
from illumio_ops.settings.schema import PceSettings
from illumio_ops.store import alerts as alerts_store
from illumio_ops.store.flowdb import binding

# app.sqlite tables that describe one PCE (cleared on a switch) and those that do not.
# tests_v6/services/collect/test_reset.py checks that every app.sqlite table is in exactly one.
APP_DB_PCE_DERIVED: tuple[str, ...] = ("pce_probe", "alert_eval_state")
# tamper_annotations and detection_annotations are the operator's input, not derived data: each row names its PCE and is listed only
# while that PCE is configured, so switching back finds the notes again.
# Alert records are kept the same way (spec §6.4: a PCE switch never touches them): each names its PCE. The
# evaluation watermarks are not: they point into the flow database the switch clears, so they go with it (a
# switch back would otherwise resume from a cursor into the old data). Rule state, rule status and channel state
# belong to the rules and channels, which do not change with the PCE. Generated reports are outputs the operator
# keeps or deletes; each row names the PCE it was made from (P5a), so a switch leaves them, and the schedules'
# last-due times belong to the schedules. Quarantine actions are a record of writes made to a PCE: each names it. Custom
# reports are the operator's definitions, like the schedules that use them.
APP_DB_PCE_INDEPENDENT: tuple[str, ...] = ("job_health", "tamper_annotations", "detection_annotations", "alerts",
                                           "alert_deliveries",
                                           "alert_notes", "alert_rule_state", "alert_rule_status", "channel_state",
                                           "reports", "report_schedule_state", "quarantine_actions",
                                           "custom_reports")


def _forget_alert_watermarks(ctx: AppContext) -> None:
    with ctx.db() as conn:
        alerts_store.clear_eval_state(conn)


_CLEARERS: dict[str, Callable[[AppContext], None]] = {"pce_probe": pce_health.forget,
                                                       "alert_eval_state": _forget_alert_watermarks}


@dataclass(frozen=True)
class ResetReport:
    cleared: list[str] = field(default_factory=list)
    archive_moved_to: str | None = None   # folder name under data/archive


def pce_target_changed(old: PceSettings, new: PceSettings) -> bool:
    return normalize_target(old.url, old.org_id) != normalize_target(new.url, new.org_id)


def reset_for_new_pce(ctx: AppContext, *, now: datetime | None = None) -> ResetReport:
    at = (now or datetime.now(UTC)).astimezone(UTC)
    fdb = ctx.flows()
    moved: str | None = None

    def move_archive_aside() -> None:
        nonlocal moved
        archive_dir = ctx.paths.archive_dir
        files = [p for p in archive_dir.iterdir() if p.is_file()] if archive_dir.is_dir() else []
        if files:
            moved = f"previous-{at.strftime('%Y%m%dT%H%M%SZ')}"
            target = archive_dir / moved
            target.mkdir(mode=0o700)
            for p in files:
                p.rename(target / p.name)

    # One hold of the write lock (it waits for a collector that is mid-write): the generation moves
    # on, the old archive goes aside and the file is rebuilt, so work begun for the old PCE writes
    # nothing afterwards (FlowDb.writing).
    fdb.reset(also=move_archive_aside)
    for table in APP_DB_PCE_DERIVED:
        _CLEARERS[table](ctx)
    return ResetReport(cleared=["flows", *APP_DB_PCE_DERIVED], archive_moved_to=moved)


def finish_pending_switch(ctx: AppContext, *, now: datetime | None = None) -> ResetReport | None:
    """The PCE page saves the new PCE, then clears the old one's data. If clearing failed or the service
    stopped in between, the flow database is still bound to the old PCE and every collector refuses to
    write; each collector run calls this first, outside the write lock, to finish the switch."""
    pce = ctx.settings.current().pce
    if not pce.url:
        return None
    with ctx.flows().connect() as conn:
        bound = binding.current(conn)
    if bound is None or normalize_target(bound.pce_url, bound.org_id) == normalize_target(pce.url, pce.org_id):
        return None
    logger.warning("the flow database still holds another PCE's data; clearing it to finish the switch")
    return reset_for_new_pce(ctx, now=now)
