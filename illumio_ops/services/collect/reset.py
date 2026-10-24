"""Switching to another PCE: everything collected from the old one goes, in one place.

The flow database is rebuilt (it holds only PCE-derived data); in the application database the
PCE-derived tables are listed once below and cleared through their owners; archive files are
moved aside, never deleted (they are the customer's records).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from illumio_ops.services import pce_health
from illumio_ops.services.collect.guard import normalize_target
from illumio_ops.services.context import AppContext
from illumio_ops.settings.schema import PceSettings

# app.sqlite tables that describe one PCE (cleared on a switch) and those that do not.
# tests_v6/services/collect/test_reset.py checks that every app.sqlite table is in exactly one.
APP_DB_PCE_DERIVED: tuple[str, ...] = ("pce_probe",)
APP_DB_PCE_INDEPENDENT: tuple[str, ...] = ("job_health",)
_CLEARERS: dict[str, Callable[[AppContext], None]] = {"pce_probe": pce_health.forget}


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
    with fdb.write_lock:  # waits for a collector that is mid-write
        archive_dir = ctx.paths.archive_dir
        files = [p for p in archive_dir.iterdir() if p.is_file()] if archive_dir.is_dir() else []
        if files:
            moved = f"previous-{at.strftime('%Y%m%dT%H%M%SZ')}"
            target = archive_dir / moved
            target.mkdir(mode=0o700)
            for p in files:
                p.rename(target / p.name)
    fdb.reset()  # takes the write lock itself
    for table in APP_DB_PCE_DERIVED:
        _CLEARERS[table](ctx)
    return ResetReport(cleared=["flows", *APP_DB_PCE_DERIVED], archive_moved_to=moved)
