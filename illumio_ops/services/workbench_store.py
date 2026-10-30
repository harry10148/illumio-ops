"""The workbench's pulled period (spec §6.4, P6a): in lightweight mode, or for a period older than the kept traffic,
the period is read from the PCE once (services/ondemand.open_period, whole hours) and kept KEEP for the clicks that
follow — every dimension, ranking and detail reads it. One is held at a time; another period, the PCE changing, or
KEEP passing closes and deletes it (a leftover file is swept at start, ondemand.sweep_leftovers)."""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel

from illumio_ops.domain.values import CollectionMode
from illumio_ops.services.context import AppContext
from illumio_ops.services.ondemand import OnDemandResult, open_period

KEEP = timedelta(minutes=30)
HOUR = timedelta(hours=1)


class PullInfo(BaseModel):
    """What was read from the PCE for this answer: said on the page (anti-goal: nothing silent)."""
    start: datetime
    end: datetime
    rows: int
    capped: bool  # the pull stopped at its row limit
    unread_from: datetime | None
    truncated_windows: int  # windows whose answer the PCE capped
    read_at: datetime


@dataclass
class _Held:
    key: tuple[str, str, int]
    start: datetime
    end: datetime
    result: OnDemandResult
    close: Callable[[], None]
    read_at: datetime
    since: float


_held: _Held | None = None
_lock = threading.Lock()


def _floor(t: datetime) -> datetime:
    return t.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def _ceil(t: datetime) -> datetime:
    f = _floor(t)
    return f if f == t.astimezone(UTC) else f + HOUR


def needs_pull(ctx: AppContext, start: datetime, now: datetime) -> bool:
    settings = ctx.settings.current()
    return (settings.collection.mode is CollectionMode.LIGHTWEIGHT
            or start < now - timedelta(days=settings.collection.retention.flow_days))


def drop() -> None:
    global _held
    with _lock:
        if _held is not None:
            _held.close()
            _held = None


def context_for(ctx: AppContext, start: datetime, end: datetime, *,
                now: datetime | None = None) -> tuple[AppContext, PullInfo | None]:
    """The context a workbench request reads: the install's own, or the held pull covering [start, end) (read now
    if none does). Raises OnDemandFailed when the PCE could not answer."""
    global _held
    at = (now or datetime.now(UTC)).astimezone(UTC)
    if not needs_pull(ctx, start, at):
        return ctx, None
    pce = ctx.settings.current().pce
    key = (pce.url, pce.org_id, ctx.flows().generation)
    clock = time.monotonic() if now is None else at.timestamp()
    with _lock:
        h = _held
        if h is not None and (h.key != key or clock - h.since > KEEP.total_seconds()
                              or not (h.start <= start and end <= h.end)):
            h.close()
            _held = h = None
        if h is None:
            a, b = _floor(start), _ceil(end)
            result, close = open_period(ctx, start=a, end=b, now=at)
            h = _held = _Held(key=key, start=a, end=b, result=result, close=close, read_at=at, since=clock)
        r = h.result
        return r.ctx, PullInfo(start=h.start, end=h.end, rows=r.rows, capped=r.capped_total,
                               unread_from=r.unread_from, truncated_windows=len(r.truncated), read_at=h.read_at)
