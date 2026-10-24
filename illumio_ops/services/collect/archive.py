"""Archive: write each complete UTC day of flows and events to data/archive as gzipped JSON lines
(written to a temporary name, then renamed); a day whose rows changed afterwards (a backfill, a
late record) is written again. Archive files expire after retention_days."""
from __future__ import annotations

import gzip
import json
import os
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from loguru import logger

from illumio_ops.services.context import AppContext
from illumio_ops.store.flowdb import archive
from illumio_ops.store.flowdb.db import StaleGeneration, db_day, db_time

_KINDS = {
    # kind -> (day expression, query for one day's rows as a time range, so the time index serves it)
    "flows": ("substr(last_detected, 1, 10)",
              "SELECT * FROM flows WHERE last_detected >= ? AND last_detected < ? ORDER BY id"),
    "events": ("substr(timestamp, 1, 10)", "SELECT * FROM events WHERE timestamp >= ? AND timestamp < ? ORDER BY id"),
}


def _day_range(day: str) -> tuple[str, str]:
    start = datetime.fromisoformat(f"{day}T00:00:00+00:00")
    return db_time(start), db_time(start + timedelta(days=1))


def _write_atomic(path: Path, lines: Iterable[str]) -> int:
    """Write lines as they come (a 1M-row day held in memory peaked at 3.1 GB); return how many."""
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    count = 0
    try:
        with os.fdopen(fd, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb") as gz:
            for line in lines:
                gz.write(line.encode("utf-8") + b"\n")
                count += 1
            gz.close()
            raw.flush()
            os.fsync(raw.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return count


def run_archive(ctx: AppContext, *, now: datetime | None = None) -> int:
    gen = ctx.flows().generation  # a PCE switch moves the archive aside; see FlowDb.generation
    try:
        return _archive(ctx, gen, now)
    except StaleGeneration:
        logger.info("archive: the PCE was switched while it ran; nothing more was written")
        return 0


def _archive(ctx: AppContext, gen: int, now: datetime | None) -> int:
    settings = ctx.settings.current().collection.archive
    if not settings.enabled:
        return 0
    at = (now or datetime.now(UTC)).astimezone(UTC)
    today = db_day(at)
    out_dir = ctx.paths.archive_dir
    out_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    fdb = ctx.flows()
    written = 0
    for kind, (day_expr, day_query) in _KINDS.items():
        with fdb.connect() as conn:
            done = archive.archived_days(conn, kind)
            days = [r[0] for r in conn.execute(f"SELECT DISTINCT {day_expr} FROM {kind} ORDER BY 1")]
        for day in days:
            if day >= today or day in done:
                continue
            # Read, write and record under the lock: a row changed in between would otherwise be
            # missing from the file while the day is recorded as archived.
            with fdb.writing(gen) as conn:
                rows = conn.execute(day_query, _day_range(day))
                path = out_dir / f"{kind}-{day}.jsonl.gz"
                count = _write_atomic(path, (json.dumps(dict(r), separators=(",", ":"), ensure_ascii=False)
                                             for r in rows))
                archive.record(conn, kind, day, count, str(path), at)
            written += 1
    if settings.retention_days > 0:
        cutoff = db_day(at - timedelta(days=settings.retention_days))
        with fdb.writing(gen) as conn:
            for kind, day, stored in archive.entries_before(conn, cutoff):
                try:
                    Path(stored).unlink(missing_ok=True)
                except OSError as exc:
                    logger.warning("could not delete expired archive file: {}", type(exc).__name__)
                    continue
                archive.forget(conn, kind, day)
    return written
