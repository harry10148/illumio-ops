"""The start and failure bookkeeping every windowed collector shares."""
from __future__ import annotations

from datetime import datetime, timedelta

from illumio_ops.store.flowdb import ingest_state
from illumio_ops.store.flowdb.db import FlowDb

COLD_START_KEY = "cold_start_from"


def begin(fdb: FlowDb, source: str, at: datetime, *, overlap: timedelta, cold_start: timedelta) -> datetime:
    """Record the start (under the write lock) and return where this cycle's window begins.

    With a watermark: watermark - overlap. Without one, the first cold-start bound is remembered
    until a cycle succeeds, so a failed first attempt is retried from the same place instead of
    sliding forward and silently skipping its oldest part."""
    with fdb.write_lock, fdb.connect() as conn:
        state = ingest_state.get(conn, source)
        ingest_state.mark_started(conn, source, at)
        if state is not None and state.watermark is not None:
            return state.watermark - overlap
        pending = (state.progress or {}).get(COLD_START_KEY) if state is not None else None
        if pending:
            return datetime.fromisoformat(pending)
        start = at - cold_start
        ingest_state.set_progress(conn, source, {COLD_START_KEY: start.isoformat()})
        return start


def fail(fdb: FlowDb, source: str, start: datetime, at: datetime, exc: BaseException) -> None:
    """The whole window failed: keep the watermark, record the gap and the error."""
    detail = f"{type(exc).__name__}: {exc}"
    with fdb.write_lock, fdb.connect() as conn:
        ingest_state.record_gap(conn, source, start, at, "failed", detail, at)
        ingest_state.mark_failed(conn, source, at, detail)
