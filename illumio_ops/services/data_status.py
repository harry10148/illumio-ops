"""System › Modes and data sources (UI redesign spec §4.10): how far each collection has read, how much baseline
and live activity the detectors have, the gaps still open, and what each part of the install takes on disk."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from illumio_ops.domain.values import CollectionMode, IngestSource
from illumio_ops.services.analysis.context import load_lateral_context
from illumio_ops.services.collect.guard import require_same_pce
from illumio_ops.services.context import AppContext
from illumio_ops.store.flowdb import ingest_state


class OpenGap(BaseModel):
    source: str
    start: datetime
    end: datetime
    kind: str


class DiskPart(BaseModel):
    name: Literal["flows", "archive", "app", "reports"]
    bytes: int


class DataStatus(BaseModel):
    mode: Literal["basic", "advanced"]
    events_latest: datetime | None   # the events collection's watermark
    flows_latest: datetime | None    # the traffic collection's watermark; None in basic mode (no traffic kept)
    baseline_days: float | None      # how many days of baseline the detectors have; None in basic mode
    baseline_target_days: int
    live_hours_days: int | None      # days with live-collection hours (quiet host, off hours); None in basic mode
    gaps: list[OpenGap]
    disk: list[DiskPart]


def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    if path.is_dir():
        return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    return 0


def _db_size(path: Path) -> int:
    """A SQLite file with its write-ahead log and shared memory."""
    return sum(_size(Path(str(path) + suffix)) for suffix in ("", "-wal", "-shm"))


def status(ctx: AppContext, *, now: datetime | None = None) -> DataStatus:
    at = (now or datetime.now(UTC)).astimezone(UTC)
    s = ctx.settings.current()
    basic = s.collection.mode is CollectionMode.LIGHTWEIGHT
    with ctx.flows().connect() as conn:
        require_same_pce(conn, s.pce)  # another PCE's store not yet cleared after a switch is not this one's state
        events = ingest_state.get(conn, IngestSource.EVENTS)
        traffic = ingest_state.get(conn, IngestSource.TRAFFIC)
        gaps = ingest_state.open_gaps(conn)
        days = None if basic else int(conn.execute(
            "SELECT COUNT(DISTINCT substr(hour, 1, 10)) FROM live_activity_hours").fetchone()[0])
    baseline = None if basic else round(load_lateral_context(ctx, now=at).baseline_days, 1)
    p = ctx.paths
    return DataStatus(
        mode="basic" if basic else "advanced", events_latest=events.watermark if events else None,
        flows_latest=None if basic or traffic is None else traffic.watermark, baseline_days=baseline,
        baseline_target_days=s.collection.retention.baseline_days, live_hours_days=days,
        gaps=[OpenGap(source=g.source, start=g.window_start, end=g.window_end, kind=g.kind) for g in gaps],
        disk=[DiskPart(name="flows", bytes=_db_size(p.flows_db)), DiskPart(name="archive", bytes=_size(p.archive_dir)),
              DiskPart(name="app", bytes=_db_size(p.app_db)), DiskPart(name="reports", bytes=_size(p.reports_dir))])
