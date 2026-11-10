"""The workbench's pulled period (spec §6.4, P6a): in lightweight mode, or for a period older than the kept traffic,
the period is read from the PCE once (services/ondemand.open_period, whole hours) and kept KEEP for the clicks that
follow — every dimension, ranking and detail reads it. One is held at a time; another period, the PCE changing, or
KEEP passing closes and deletes it (a leftover file is swept at start, ondemand.sweep_leftovers).

A period older than the kept traffic that the archive reaches is read from the archive instead (6.5.0 B1, spec §6.3:
the one reader reports use, services/archive_read): no request to the PCE. It is held and dropped the same way."""
from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel

from illumio_ops.domain.values import CollectionMode
from illumio_ops.services import archive_read
from illumio_ops.services.context import AppContext
from illumio_ops.services.ondemand import INTERACTIVE_PULL, OnDemandResult, open_period
from illumio_ops.store.flowdb.db import StaleGeneration

KEEP = timedelta(minutes=30)
HOUR = timedelta(hours=1)


class PullInfo(BaseModel):
    """What was read for this answer, from the PCE or from the archive: said on the page (anti-goal: nothing
    silent)."""
    source: Literal["pce", "archive"] = "pce"
    start: datetime
    end: datetime
    rows: int
    capped: bool  # the pull stopped at its row limit
    unread_from: datetime | None
    truncated_windows: int  # windows whose answer the PCE capped
    read_at: datetime
    # source "archive": the days read from archive files, the days before the kept traffic that no file holds, and
    # the archive lines that could not be loaded. capped: loading stopped at archive_read.ARCHIVE_MAX_ROWS.
    archive_days: int = 0
    archive_first: str | None = None
    archive_last: str | None = None
    missing_days: list[str] = []
    unreadable: int = 0


@dataclass
class _Held:
    key: tuple[str, str, int]
    start: datetime
    end: datetime
    ctx: AppContext  # the throwaway store's context
    info: PullInfo
    close: Callable[[], None]
    since: float
    refs: int = 0  # requests reading it now
    retired: bool = False  # replaced or expired: closed when the last reader is done (security review #1)


_held: _Held | None = None
_lock = threading.Lock()  # bookkeeping only, never held while the PCE answers
_pull_lock = INTERACTIVE_PULL  # one pull at a time, shared with the lateral page (a pull no longer blocks readers)


def _floor(t: datetime) -> datetime:
    return t.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def _ceil(t: datetime) -> datetime:
    f = _floor(t)
    return f if f == t.astimezone(UTC) else f + HOUR


def needs_pull(ctx: AppContext, start: datetime, now: datetime) -> bool:
    settings = ctx.settings.current()
    return (settings.collection.mode is CollectionMode.LIGHTWEIGHT
            or start < now - timedelta(days=settings.collection.retention.flow_days))


def from_archive(ctx: AppContext, start: datetime, now: datetime) -> bool:
    """Whether a period starting at `start` is read from the archive: it starts before the kept traffic, the
    archive is on and reaches it. Lightweight mode keeps no traffic and has no archive of it: it reads the PCE."""
    collection = ctx.settings.current().collection
    if collection.mode is CollectionMode.LIGHTWEIGHT or not collection.archive.enabled:
        return False
    return start < archive_read.floors(ctx, now)["flows"] and archive_read.earliest(ctx, "flows", now) <= start


def _open(ctx: AppContext, a: datetime, b: datetime, at: datetime) -> tuple[AppContext, PullInfo, Callable[[], None]]:
    if from_archive(ctx, a, at):
        held = ExitStack()  # the throwaway store stays open until the pull is retired
        arc = held.enter_context(archive_read.archive_period(ctx, start=a, end=b, now=at, kinds=("flows",)))
        days = arc.archived_days.get("flows") or []
        return arc.ctx, PullInfo(
            source="archive", start=a, end=b, rows=arc.rows, capped=arc.unread_from is not None,
            unread_from=arc.unread_from, truncated_windows=0, read_at=at, archive_days=len(days),
            archive_first=days[0] if days else None, archive_last=days[-1] if days else None,
            missing_days=list(arc.missing_days.get("flows") or []),
            unreadable=arc.unreadable), held.close
    result, close = open_period(ctx, start=a, end=b, now=at)
    return result.ctx, _pce_info(result, a, b, at), close


def _pce_info(r: OnDemandResult, a: datetime, b: datetime, at: datetime) -> PullInfo:
    return PullInfo(start=a, end=b, rows=r.rows, capped=r.capped_total, unread_from=r.unread_from,
                    truncated_windows=len(r.truncated), read_at=at)


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
    cannot see the install's reset). Raises OnDemandFailed when the PCE could not answer. An archived period is
    read from the archive (from_archive), held and dropped the same way."""
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
                read, info, close = _open(ctx, a, b, at)
                with _lock:
                    if _held is not None:
                        _retire(_held)
                    h = _held = _Held(key=key, start=a, end=b, ctx=read, info=info, close=close, since=clock,
                                      refs=1)
    held = h

    def check() -> None:
        if not _same_pce(ctx, key):
            with _lock:
                if not held.retired:
                    _retire(held)
            raise StaleGeneration
    try:
        yield held.ctx, held.info, check
    finally:
        _release(held)
