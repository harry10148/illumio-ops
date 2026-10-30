"""The workbench's pulled period (spec §6.4, P6a): in lightweight mode, or for a period older than the kept traffic,
the period is read from the PCE once (services/ondemand.open_period, whole hours) and kept KEEP for the clicks that
follow — every dimension, ranking and detail reads it. One is held at a time; another period, the PCE changing, or
KEEP passing closes and deletes it (a leftover file is swept at start, ondemand.sweep_leftovers)."""
from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel

from illumio_ops.domain.values import CollectionMode
from illumio_ops.services.context import AppContext
from illumio_ops.services.ondemand import OnDemandResult, open_period
from illumio_ops.store.flowdb.db import StaleGeneration

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
    refs: int = 0  # requests reading it now
    retired: bool = False  # replaced or expired: closed when the last reader is done (security review #1)


_held: _Held | None = None
_lock = threading.Lock()  # bookkeeping only, never held while the PCE answers
_pull_lock = threading.Lock()  # one pull at a time (security review #2: a pull no longer blocks readers)


def _floor(t: datetime) -> datetime:
    return t.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def _ceil(t: datetime) -> datetime:
    f = _floor(t)
    return f if f == t.astimezone(UTC) else f + HOUR


def needs_pull(ctx: AppContext, start: datetime, now: datetime) -> bool:
    settings = ctx.settings.current()
    return (settings.collection.mode is CollectionMode.LIGHTWEIGHT
            or start < now - timedelta(days=settings.collection.retention.flow_days))


def _retire(h: _Held) -> None:
    """Under _lock."""
    global _held
    h.retired = True
    if _held is h:
        _held = None
    if h.refs == 0:
        h.close()


def _covering(key: tuple[str, str, int], start: datetime, end: datetime, clock: float) -> _Held | None:
    """The held pull answering [start, end), leased; a stale one is retired."""
    with _lock:
        h = _held
        if h is None:
            return None
        if h.key != key or clock - h.since > KEEP.total_seconds():
            _retire(h)
            return None
        if h.start <= start and end <= h.end:
            h.refs += 1
            return h
        return None


def _release(h: _Held) -> None:
    with _lock:
        h.refs -= 1
        if h.retired and h.refs == 0:
            h.close()


def _same_pce(install: AppContext, key: tuple[str, str, int]) -> bool:
    pce = install.settings.current().pce
    return (pce.url, pce.org_id, install.flows().generation) == key


def drop() -> None:
    with _lock:
        if _held is not None:
            _retire(_held)


@contextmanager
def lease(ctx: AppContext, start: datetime, end: datetime, *,
          now: datetime | None = None) -> Iterator[tuple[AppContext, PullInfo | None, Callable[[], None]]]:
    """The context a workbench request reads, for the length of the request — the install's own, or the held pull
    covering [start, end) (read now if none does) — and a check to call once the answer is computed: it raises
    StaleGeneration when the PCE changed meanwhile and retires the pull (final review #1: the pull's own store
    cannot see the install's reset). Raises OnDemandFailed when the PCE could not answer."""
    global _held
    at = (now or datetime.now(UTC)).astimezone(UTC)
    if not needs_pull(ctx, start, at):
        yield ctx, None, lambda: None  # the install's own reads check their generation themselves
        return
    pce = ctx.settings.current().pce
    key = (pce.url, pce.org_id, ctx.flows().generation)
    clock = time.monotonic() if now is None else at.timestamp()
    h = _covering(key, start, end, clock)
    if h is None:
        with _pull_lock:
            h = _covering(key, start, end, clock)  # pulled while this request waited
            if h is None:
                a, b = _floor(start), _ceil(end)
                result, close = open_period(ctx, start=a, end=b, now=at)
                with _lock:
                    if _held is not None:
                        _retire(_held)
                    h = _held = _Held(key=key, start=a, end=b, result=result, close=close, read_at=at, since=clock,
                                      refs=1)
    held = h

    def check() -> None:
        if not _same_pce(ctx, key):
            with _lock:
                if not held.retired:
                    _retire(held)
            raise StaleGeneration
    try:
        r = held.result
        yield r.ctx, PullInfo(start=held.start, end=held.end, rows=r.rows, capped=r.capped_total,
                              unread_from=r.unread_from, truncated_windows=len(r.truncated),
                              read_at=held.read_at), check
    finally:
        _release(held)
