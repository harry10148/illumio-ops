"""Traffic and events older than the store keeps, read back from data/archive (spec §6.3: FlowSource reads the store,
the live PCE and the archive). A period reaching before the store's floor is built on a throwaway store, as an
on-demand pull is (services/ondemand.py): the install's labels, inventory and analysis copied in, every row the store
still has for the period, then each earlier day from its archive file (a row already there is kept: the store's is
the newer). What neither holds stays uncovered, and a load stopped at ARCHIVE_MAX_ROWS is a truncated gap: both are
said, never shown as no traffic."""
from __future__ import annotations

import dataclasses
import gzip
import json
import sqlite3
import uuid
import zlib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from illumio_ops.domain.values import IngestSource
from illumio_ops.services.collect.guard import ensure_binding, require_same_pce
from illumio_ops.services.context import AppContext
from illumio_ops.services.ondemand import _seed, ondemand_dir
from illumio_ops.store.flowdb import ingest_state
from illumio_ops.store.flowdb.db import FlowDb, db_time, transaction
from illumio_ops.store.flowdb.flows import refresh_rollups

# Rows one period may load from archive files in all (an on-demand pull stops at the same count): the rest of the
# period is a recorded truncated gap. A day of 1M rows took minutes to write; thirty of them would take far longer.
ARCHIVE_MAX_ROWS = 1_000_000
BATCH = 5_000
# kind -> (ingest source, time column, identity column): archive files are SELECT * of these tables, by day of time.
_KINDS = {"flows": (IngestSource.TRAFFIC, "last_detected", "record_key"),
          "events": (IngestSource.EVENTS, "timestamp", "href")}


@dataclass(frozen=True)
class ArchiveResult:
    ctx: AppContext                # the caller's context with the throwaway store in place of the install's
    archived_days: dict[str, list[str]]  # kind -> days read from archive files
    missing_days: dict[str, list[str]]   # kind -> days before the store's floor that no archive file holds
    rows: int                      # rows loaded from archive files
    unreadable: int                # archive lines that could not be loaded (damaged or not a row)
    unread_from: datetime | None   # where loading stopped at ARCHIVE_MAX_ROWS


def floors(ctx: AppContext, now: datetime) -> dict[str, datetime]:
    """Where the store's own rows start, per kind."""
    retention = ctx.settings.current().collection.retention
    return {"flows": now - timedelta(days=retention.flow_days), "events": now - timedelta(days=retention.event_days)}


def archive_files(ctx: AppContext, kind: str) -> dict[str, Path]:
    """Day -> file of every finished archive day of this kind whose file is there."""
    with ctx.flows().connect() as conn:
        rows = conn.execute("SELECT day, path FROM archive_log WHERE kind = ? AND stale = 0 AND rows >= 0",
                            (kind,)).fetchall()
    return {day: Path(p) for day, p in rows if Path(p).is_file()}


def earliest(ctx: AppContext, kind: str, now: datetime) -> datetime:
    """The earliest time this kind can be read: the first archive day, or the store's floor without one."""
    floor = floors(ctx, now)[kind]
    days = archive_files(ctx, kind)
    if not days:
        return floor
    first = datetime.fromisoformat(f"{min(days)}T00:00:00+00:00")
    return min(first, floor)


def _days(start: datetime, end: datetime) -> list[str]:
    out, d = [], start.astimezone(UTC).date()
    last = (end - timedelta(microseconds=1)).astimezone(UTC).date()
    while d <= last:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _day_window(day: str) -> tuple[datetime, datetime]:
    a = datetime.fromisoformat(f"{day}T00:00:00+00:00")
    return a, a + timedelta(days=1)


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})") if r[1] != "id"]


def _copy_store(conn: sqlite3.Connection, kind: str, start: datetime, end: datetime) -> None:
    """The store's rows of the period (the install is attached as `install`)."""
    _, col, _ = _KINDS[kind]
    cols = ", ".join(_columns(conn, kind))
    conn.execute(f"INSERT OR IGNORE INTO {kind} ({cols}) SELECT {cols} FROM install.{kind} WHERE {col} >= ? AND {col} < ?",
                 (db_time(start), db_time(end)))


def _copy_coverage(conn: sqlite3.Connection, source: str, start: datetime, end: datetime, floor: datetime,
                   at: datetime) -> None:
    """What the store covers of the period from its floor on, and its recorded gaps there (the install attached)."""
    lo = max(start, floor)
    if lo >= end:
        return
    for a, b in conn.execute("SELECT range_start, range_end FROM install.ingest_coverage WHERE source = ?", (source,)):
        x, y = max(datetime.fromisoformat(a), lo), min(datetime.fromisoformat(b), end)
        if x < y:
            ingest_state.add_coverage(conn, source, x, y)
    for g in conn.execute("SELECT window_start, window_end, kind, detail FROM install.ingest_gaps "
                          "WHERE source = ? AND resolved_at IS NULL AND window_start < ? AND window_end > ?",
                          (source, db_time(end), db_time(lo))):
        ingest_state.record_gap(conn, source, max(datetime.fromisoformat(g[0]), lo),
                                min(datetime.fromisoformat(g[1]), end), g[2], g[3], at)


def _load_file(conn: sqlite3.Connection, kind: str, path: Path, window: tuple[datetime, datetime],
               budget: int) -> tuple[int, int, bool]:
    """A day's archive rows inside the window: (loaded, unreadable, stopped at the budget). A line written by an
    older schema loads with the columns it has; one that is damaged or breaks a constraint is counted, not loaded."""
    _, col, _ = _KINDS[kind]
    cols = set(_columns(conn, kind))
    lo, hi = db_time(window[0]), db_time(window[1])
    loaded = unreadable = 0
    batch: dict[tuple[str, ...], list[tuple[object, ...]]] = {}

    def flush() -> int:
        """Write the batch; a row the table refuses (a NOT NULL an older line lacks) is counted, the others go in."""
        refused = 0
        for keys, values in batch.items():
            sql = f"INSERT OR IGNORE INTO {kind} ({', '.join(keys)}) VALUES ({', '.join('?' * len(keys))})"
            try:
                with transaction(conn):
                    conn.executemany(sql, values)
            except sqlite3.IntegrityError:
                for v in values:
                    try:
                        conn.execute(sql, v)
                    except sqlite3.IntegrityError:
                        refused += 1
        batch.clear()
        return refused

    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except ValueError:
                    row = None
                if not isinstance(row, dict):
                    unreadable += 1
                    continue
                t = row.get(col)
                if not isinstance(t, str) or not lo <= t < hi:
                    continue
                keys = tuple(sorted(k for k in row if k in cols))
                batch.setdefault(keys, []).append(tuple(row[k] for k in keys))
                loaded += 1
                if loaded % BATCH == 0:
                    unreadable += flush()
                if loaded >= budget:
                    unreadable += flush()
                    return loaded, unreadable, True
    except (OSError, EOFError, zlib.error):
        unreadable += 1  # the file ends early or is not gzip: what was read before stays, the rest is counted
    unreadable += flush()
    return loaded, unreadable, False


@contextmanager
def archive_period(ctx: AppContext, *, start: datetime, end: datetime, now: datetime | None = None,
                   kinds: tuple[str, ...] = ("flows", "events")) -> Iterator[ArchiveResult]:
    """A throwaway store holding [start, end) from the store and the archive; deleted on exit."""
    at = (now or datetime.now(UTC)).astimezone(UTC)
    settings = ctx.settings.current()
    edge = floors(ctx, at)
    d = ondemand_dir(ctx.paths)
    d.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = d / f"archive-{uuid.uuid4().hex}.sqlite"
    fdb = FlowDb(path)
    try:
        archived: dict[str, list[str]] = {}
        missing: dict[str, list[str]] = {}
        total = unreadable = 0
        unread_from: datetime | None = None
        with ctx.flows().connect() as install, fdb.writing(fdb.generation) as conn:
            require_same_pce(install, settings.pce)
            ensure_binding(conn, settings.pce, at)
            _seed(conn, ctx.flows().path)
            conn.execute("ATTACH DATABASE ? AS install", (str(ctx.flows().path),))
            try:
                with transaction(conn):
                    for kind in kinds:
                        source = _KINDS[kind][0]
                        _copy_store(conn, kind, max(start, edge[kind]), end)
                        _copy_coverage(conn, source, start, end, edge[kind], at)
            finally:
                conn.execute("DETACH DATABASE install")
        for kind in kinds:
            source = _KINDS[kind][0]
            files = archive_files(ctx, kind)
            first = min(files, default=None)
            with ctx.flows().connect() as install:
                collected = ingest_state.coverage(install, source)
            archived[kind], missing[kind] = [], []
            for day in _days(start, min(end, edge[kind])):
                a, b = _day_window(day)
                window = (max(a, start), min(b, end, edge[kind]))
                if window[0] >= window[1]:
                    continue
                if unread_from is not None:
                    continue
                if day not in files:
                    # The archive writes a file only for a day with rows. A day after its first file that collection
                    # covered had none (retention drops only archived days); before that, or uncovered, it is missing.
                    if first is not None and day > first and any(a <= window[0] and window[1] <= b
                                                                  for a, b in collected):
                        with fdb.writing(fdb.generation) as conn:
                            ingest_state.add_coverage(conn, source, window[0], window[1])
                    else:
                        missing[kind].append(day)
                    continue
                with fdb.writing(fdb.generation) as conn, transaction(conn):
                    n, bad, stopped = _load_file(conn, kind, files[day], window, ARCHIVE_MAX_ROWS - total)
                    total += n
                    unreadable += bad
                    if stopped:
                        unread_from = window[0]
                        ingest_state.record_gap(conn, source, window[0], end, "truncated",
                                                f"stopped at {ARCHIVE_MAX_ROWS} archived rows", at)
                    ingest_state.add_coverage(conn, source, window[0], window[1])
                    if kind == "flows":
                        conn.execute("INSERT INTO rollup_state (day, dirty) VALUES (?, 1) "
                                     "ON CONFLICT(day) DO UPDATE SET dirty = 1", (day,))
                archived[kind].append(day)
        with fdb.writing(fdb.generation) as conn:
            for day in _days(max(start, edge["flows"]), end) if "flows" in kinds and start < end else []:
                conn.execute("INSERT INTO rollup_state (day, dirty) VALUES (?, 1) "
                             "ON CONFLICT(day) DO UPDATE SET dirty = 1", (day,))
            refresh_rollups(conn, at, today_every=timedelta(0))
        yield ArchiveResult(ctx=dataclasses.replace(ctx, flowdb=fdb, ondemand=True), archived_days=archived,
                            missing_days=missing, rows=total, unreadable=unreadable, unread_from=unread_from)
    finally:
        fdb.close()
        for suffix in ("", "-wal", "-shm", "-journal"):
            Path(f"{path}{suffix}").unlink(missing_ok=True)
