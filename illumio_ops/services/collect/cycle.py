"""The start and failure bookkeeping every windowed collector shares."""
from __future__ import annotations

from datetime import datetime, timedelta

from illumio_ops.store.flowdb import ingest_state
from illumio_ops.store.flowdb.db import FlowDb

COLD_START_KEY = "cold_start_from"
COVERED_FROM_KEY = "covered_from"


def begin(fdb: FlowDb, source: str, at: datetime, *, overlap: timedelta,
          cold_start: timedelta) -> tuple[datetime, dict[str, str]]:
    """Record the start (under the write lock); return where this cycle's window begins and the
    progress to store when it succeeds.

    With a watermark: watermark - overlap. Without one, the first cold-start bound is remembered
    until a cycle succeeds, so a failed first attempt is retried from the same place instead of
    sliding forward and silently skipping its oldest part. The first successful window's start is
    kept as covered_from: the earliest moment live collection has read (FlowSource reports
    anything older as a gap)."""
    with fdb.write_lock, fdb.connect() as conn:
        state = ingest_state.get(conn, source)
        ingest_state.mark_started(conn, source, at)
        progress = (state.progress or {}) if state is not None else {}
        if state is not None and state.watermark is not None:
            return state.watermark - overlap, {COVERED_FROM_KEY: progress.get(COVERED_FROM_KEY, "")}
        pending = progress.get(COLD_START_KEY)
        start = datetime.fromisoformat(pending) if pending else at - cold_start
        if not pending:
            ingest_state.set_progress(conn, source, {COLD_START_KEY: start.isoformat()})
        return start, {COVERED_FROM_KEY: start.isoformat()}


def fail(fdb: FlowDb, source: str, start: datetime, at: datetime, exc: BaseException) -> None:
    """The whole window failed: keep the watermark, record the gap and the error."""
    detail = f"{type(exc).__name__}: {exc}"
    with fdb.write_lock, fdb.connect() as conn:
        ingest_state.record_gap(conn, source, start, at, "failed", detail, at)
        ingest_state.mark_failed(conn, source, at, detail)
