"""Switching to another PCE: everything collected from the old one goes, in one place.

The flow database is rebuilt (it holds only PCE-derived data); in the application database the
PCE-derived tables are listed once below and cleared through their owners; archive files are
moved aside, never deleted (they are the customer's records).

The same PCE at a new address (decision D3, spec §6.4) keeps everything instead: the flow database is
rebound and every app.sqlite row that names its PCE follows it to the new address (move_to_new_address).
"""
from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from loguru import logger

from illumio_ops.services import pce_health
from illumio_ops.services.collect.guard import normalize_target
from illumio_ops.services.context import AppContext
from illumio_ops.settings.schema import PceSettings
from illumio_ops.store import alerts as alerts_store
from illumio_ops.store import annotations as tamper_annotations
from illumio_ops.store import (
    detection_annotations,
    quarantine_actions,
    reports,
    rule_schedules,
)
from illumio_ops.store import siem as siem_store
from illumio_ops.store.flowdb import binding

# app.sqlite tables that describe one PCE (cleared on a switch) and those that do not.
# tests/services/collect/test_reset.py checks that every app.sqlite table is in exactly one.
APP_DB_PCE_DERIVED: tuple[str, ...] = ("pce_probe", "alert_eval_state", "siem_cursor")
# tamper_annotations and detection_annotations are the operator's input, not derived data: each row names its PCE and is listed only
# while that PCE is configured, so switching back finds the notes again.
# Alert records are kept the same way (spec §6.4: a PCE switch never touches them): each names its PCE. The
# evaluation watermarks are not: they point into the flow database the switch clears, so they go with it (a
# switch back would otherwise resume from a cursor into the old data). Rule state, rule status and channel state
# belong to the rules and channels, which do not change with the PCE. Generated reports are outputs the operator
# keeps or deletes; each row names the PCE it was made from (P5a), so a switch leaves them, and the schedules'
# last-due times belong to the schedules. Quarantine actions are a record of writes made to a PCE: each names it. Custom
# reports are the operator's definitions, like the schedules that use them. The SIEM cursors into the flow store go
# with it — they restart at the new store's beginning (the alerts cursor stays: alerts do); the SIEM DLQ holds lines already formatted, and the alert id floor
# belongs to the alerts. Rule schedules and their runs name their PCE (an operator's definitions and a record of
# writes, like quarantine actions): a switch leaves them, and they are checked again only while that PCE is set.
APP_DB_PCE_INDEPENDENT: tuple[str, ...] = ("job_health", "tamper_annotations", "detection_annotations", "alerts",
                                           "alert_deliveries",
                                           "alert_notes", "alert_rule_state", "alert_rule_status", "channel_state",
                                           "reports", "report_schedule_state", "quarantine_actions",
                                           "custom_reports", "alert_id_floor", "siem_dlq", "rule_schedules",
                                           "rule_schedule_runs")


def _forget_alert_watermarks(ctx: AppContext) -> None:
    with ctx.db() as conn:
        alerts_store.clear_eval_state(conn)


def _forget_siem_cursors(ctx: AppContext) -> None:
    pce = ctx.settings.current().pce  # already the new one
    with ctx.db() as conn:
        siem_store.restart_flow_cursors(conn, pce_url=pce.url, org_id=pce.org_id)


_CLEARERS: dict[str, Callable[[AppContext], None]] = {"pce_probe": pce_health.forget,
                                                       "alert_eval_state": _forget_alert_watermarks,
                                                       "siem_cursor": _forget_siem_cursors}


# app.sqlite tables whose rows name their PCE (a pce_url or pce_target column), moved with the same PCE to its new
# address by their owners (tests/services/collect/test_reset.py checks the list against the columns; pce_probe is
# forgotten instead: the next probe checks the new address).
APP_DB_REKEYED: tuple[str, ...] = ("alerts", "alert_eval_state", "tamper_annotations", "detection_annotations",
                                   "quarantine_actions", "siem_cursor", "rule_schedules", "rule_schedule_runs",
                                   "reports")


def _report_target(pce: PceSettings) -> str:
    url, org = normalize_target(pce.url, pce.org_id)  # as services.reports.generate.pce_target
    return f"{url}#{org}"


def move_to_new_address(ctx: AppContext, conn: sqlite3.Connection, old: PceSettings, new: PceSettings,
                        *, now: datetime) -> None:
    """The same PCE (already verified) at a new address: the flow database `conn` (held under its write lock by the
    caller, with the settings saved in the same hold) is rebound, and every app.sqlite row naming the old address
    names the new one."""
    url, org = normalize_target(new.url, new.org_id)
    binding.rebind(conn, url, org, now)
    moved = {"old_url": old.url, "new_url": new.url, "org_id": new.org_id}
    with ctx.db() as app:
        alerts_store.move_pce(app, **moved)
        tamper_annotations.move_pce(app, **moved)
        detection_annotations.move_pce(app, **moved)
        quarantine_actions.move_pce(app, **moved)
        siem_store.move_pce(app, **moved)
        rule_schedules.move_pce(app, **moved)
        reports.move_pce(app, old_target=_report_target(old), new_target=_report_target(new))
        app.commit()
    pce_health.forget(ctx)


@dataclass(frozen=True)
class ResetReport:
    cleared: list[str] = field(default_factory=list)
    archive_moved_to: str | None = None   # folder name under data/archive


def pce_target_changed(old: PceSettings, new: PceSettings) -> bool:
    return normalize_target(old.url, old.org_id) != normalize_target(new.url, new.org_id)


def _bound_elsewhere(ctx: AppContext, conn: sqlite3.Connection) -> bool:
    pce = ctx.settings.current().pce
    bound = binding.current(conn)
    return bound is not None and normalize_target(bound.pce_url, bound.org_id) != normalize_target(pce.url, pce.org_id)


def reset_for_new_pce(ctx: AppContext, *, now: datetime | None = None) -> ResetReport:
    report = _reset(ctx, now=now, only_if_bound_elsewhere=False)
    if report is None:  # an unconditional reset always resets (or raises FlowDbBusy)
        raise RuntimeError("the flow database was not reset")
    return report


def clear_collected(ctx: AppContext, *, now: datetime | None = None) -> ResetReport:
    """5.x `cache flush --confirm`, from Modes and data sources: the same clearing as a PCE switch, for the same PCE —
    the collected traffic, events and analysis go, archive files are moved aside, settings, alert records and reports
    stay; collection and a first backfill start again. Raises FlowDbBusy (nothing deleted) as the switch does."""
    return reset_for_new_pce(ctx, now=now)


def _reset(ctx: AppContext, *, now: datetime | None, only_if_bound_elsewhere: bool) -> ResetReport | None:
    """only_if_bound_elsewhere: checked again under the write lock; None (nothing done) when the store is no longer
    bound to another PCE than the settings name."""
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
    if not fdb.reset(also=move_archive_aside,
                     still_wanted=(lambda conn: _bound_elsewhere(ctx, conn)) if only_if_bound_elsewhere else None):
        return None
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
    # Asked again under the write lock: the PCE page may have rebound the store to the same PCE's new address since
    # the read above (decision D3), and that data must not be cleared.
    return _reset(ctx, now=now, only_if_bound_elsewhere=True)
