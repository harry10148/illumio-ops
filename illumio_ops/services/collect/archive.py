"""Archive: write each complete UTC day of flows and events to data/archive as gzipped JSON lines
(written to a temporary name, then renamed); a day whose rows changed afterwards (a backfill, a
late record) is written again. Archive files expire after retention_days."""
from __future__ import annotations

import gzip
import json
import os
import sqlite3
from collections.abc import Callable, Iterable, Iterator
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
_KEY = {"flows": "record_key", "events": "href"}  # a row's identity across rewrites of its day
_HAS_ROWS = {
    "flows": "SELECT 1 FROM flows WHERE last_detected >= ? AND last_detected < ? LIMIT 1",
    "events": "SELECT 1 FROM events WHERE timestamp >= ? AND timestamp < ? LIMIT 1",
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
        dirfd = os.open(path.parent, os.O_RDONLY)  # the new name survives a power cut only once this is synced
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return count


CHECK_EVERY = 1000  # rows between checks that the PCE was not switched (a reset waits for this read)


def _day_lines(conn: sqlite3.Connection, kind: str, day: str, path: Path, keep_old: bool,
               current: Callable[[], bool]) -> Iterator[str]:
    """The day's file as JSON lines from one read snapshot. With keep_old, a line of the file already
    written for the day whose row is no longer stored (retention dropped it) is kept: the database
    no longer holds the whole day, the file does. Stops (StaleGeneration) once current() is false."""
    conn.execute("BEGIN")  # one snapshot for the look-ups and the day's rows
    try:
        n = 0
        if keep_old and path.exists():
            key = _KEY[kind]
            with gzip.open(path, "rt", encoding="utf-8") as old:
                for line in old:
                    if n % CHECK_EVERY == 0 and not current():
                        raise StaleGeneration
                    n += 1
                    k = json.loads(line).get(key)
                    if k is None or conn.execute(f"SELECT 1 FROM {kind} WHERE {key} = ?", (k,)).fetchone() is None:
                        yield line.rstrip("\n")
        for r in conn.execute(_KINDS[kind][1], _day_range(day)):
            if n % CHECK_EVERY == 0 and not current():
                raise StaleGeneration
            n += 1
            yield json.dumps(dict(r), separators=(",", ":"), ensure_ascii=False)
        if not current():
            raise StaleGeneration
    finally:
        conn.rollback()


def run_archive(ctx: AppContext, *, now: datetime | None = None) -> int:
    gen = ctx.flows().generation  # a PCE switch moves the archive aside; see FlowDb.generation
    try:
        return _archive(ctx, gen, now)
    except StaleGeneration:
        logger.info("archive: the PCE was switched while it ran; nothing more was written")
        return 0


def _archive(ctx: AppContext, gen: int, now: datetime | None) -> int:
    collection = ctx.settings.current().collection
    settings = collection.archive
    if not settings.enabled:
        return 0
    at = (now or datetime.now(UTC)).astimezone(UTC)
    today = db_day(at)
    # Days retention may have thinned (up to the raw cutoff's day): a rewrite keeps the file's other rows.
    thinned = {"flows": db_day(at - timedelta(days=collection.retention.flow_days)),
               "events": db_day(at - timedelta(days=collection.retention.event_days))}
    out_dir = ctx.paths.archive_dir
    out_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    fdb = ctx.flows()
    written = 0
    for kind, (day_expr, _) in _KINDS.items():
        with fdb.connect() as conn:
            done = archive.archived_days(conn, kind)
            days = [r[0] for r in conn.execute(f"SELECT DISTINCT {day_expr} FROM {kind} ORDER BY 1")]
        for day in days:
            if day >= today or day in done:
                continue
            path = out_dir / f"{kind}-{day}.jsonl.gz"
            # The file is written without the write lock (a 1M-row day took 269 s, P2 re-measure); a row
            # changed meanwhile marks the day stale, so finish() leaves it to be written again.
            with fdb.writing(gen) as conn:
                archive.begin(conn, kind, day, str(path), at)
            try:
                with fdb.connect() as conn:
                    count = _write_atomic(path, _day_lines(conn, kind, day, path, keep_old=day <= thinned[kind],
                                                           current=lambda: fdb.generation == gen))
                with fdb.writing(gen) as conn:
                    written += archive.finish(conn, kind, day, count, at)
            except StaleGeneration:
                path.unlink(missing_ok=True)  # the old PCE's day, written after its archive went aside
                raise
            except OSError:
                if fdb.generation != gen:  # the archive went aside under this write
                    raise StaleGeneration from None
                raise
    if settings.retention_days > 0:
        cutoff = db_day(at - timedelta(days=settings.retention_days))
        with fdb.writing(gen) as conn:
            for kind, day, stored in archive.entries_before(conn, cutoff):
                # Not while the day still has rows: retention drops only archived days, so a forgotten
                # day would keep its rows for good (and be archived and expired again every day).
                if conn.execute(_HAS_ROWS[kind], _day_range(day)).fetchone():
                    continue
                try:
                    Path(stored).unlink(missing_ok=True)
                except OSError as exc:
                    logger.warning("could not delete expired archive file: {}", type(exc).__name__)
                    continue
                archive.forget(conn, kind, day)
    return written
