"""Collection progress per source (ingest_state) and the windows that failed or were truncated
(ingest_gaps). A watermark only moves through mark_ok; a failure never advances it."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from illumio_ops.store.flowdb.db import db_time, transaction

GapKind = Literal["failed", "truncated"]


@dataclass(frozen=True)
class IngestState:
    source: str
    watermark: datetime | None
    last_started_at: datetime | None
    last_finished_at: datetime | None
    last_ok_at: datetime | None
    last_error: str | None
    last_rows: int | None
    consecutive_failures: int
    progress: dict[str, Any] | None


@dataclass(frozen=True)
class Gap:
    id: int
    source: str
    window_start: datetime
    window_end: datetime
    kind: str
    detail: str | None
    recorded_at: datetime
    resolved_at: datetime | None


def _t(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def get(conn: sqlite3.Connection, source: str) -> IngestState | None:
    row = conn.execute("SELECT * FROM ingest_state WHERE source = ?", (source,)).fetchone()
    if row is None:
        return None
    return IngestState(
        source=row["source"], watermark=_t(row["watermark"]), last_started_at=_t(row["last_started_at"]),
        last_finished_at=_t(row["last_finished_at"]), last_ok_at=_t(row["last_ok_at"]),
        last_error=row["last_error"], last_rows=row["last_rows"],
        consecutive_failures=row["consecutive_failures"],
        progress=json.loads(row["progress_json"]) if row["progress_json"] else None,
    )


def all_states(conn: sqlite3.Connection) -> dict[str, IngestState]:
    out: dict[str, IngestState] = {}
    for (source,) in conn.execute("SELECT source FROM ingest_state").fetchall():
        state = get(conn, source)
        if state is not None:
            out[source] = state
    return out


def mark_started(conn: sqlite3.Connection, source: str, at: datetime) -> None:
    with transaction(conn):
        conn.execute("INSERT INTO ingest_state (source, last_started_at) VALUES (?, ?) "
                     "ON CONFLICT(source) DO UPDATE SET last_started_at = excluded.last_started_at",
                     (source, db_time(at)))


def mark_ok(conn: sqlite3.Connection, source: str, at: datetime, *, watermark: datetime | None, rows: int,
            progress: dict[str, Any] | None = None) -> None:
    with transaction(conn):
        conn.execute(
            "INSERT INTO ingest_state (source, watermark, last_finished_at, last_ok_at, last_error, last_rows, "
            "consecutive_failures, progress_json) VALUES (?, ?, ?, ?, NULL, ?, 0, ?) "
            "ON CONFLICT(source) DO UPDATE SET watermark = COALESCE(excluded.watermark, watermark), "
            "last_finished_at = excluded.last_finished_at, last_ok_at = excluded.last_ok_at, last_error = NULL, "
            "last_rows = excluded.last_rows, consecutive_failures = 0, "
            "progress_json = COALESCE(excluded.progress_json, progress_json)",
            (source, db_time(watermark) if watermark else None, db_time(at), db_time(at), rows,
             json.dumps(progress) if progress is not None else None))


def mark_failed(conn: sqlite3.Connection, source: str, at: datetime, error: str) -> None:
    with transaction(conn):
        conn.execute(
            "INSERT INTO ingest_state (source, last_finished_at, last_error, consecutive_failures) "
            "VALUES (?, ?, ?, 1) ON CONFLICT(source) DO UPDATE SET last_finished_at = excluded.last_finished_at, "
            "last_error = excluded.last_error, consecutive_failures = consecutive_failures + 1",
            (source, db_time(at), error[:500]))


def set_progress(conn: sqlite3.Connection, source: str, progress: dict[str, Any] | None) -> None:
    with transaction(conn):
        conn.execute("INSERT INTO ingest_state (source, progress_json) VALUES (?, ?) "
                     "ON CONFLICT(source) DO UPDATE SET progress_json = excluded.progress_json",
                     (source, json.dumps(progress) if progress is not None else None))


def record_gap(conn: sqlite3.Connection, source: str, start: datetime, end: datetime, kind: GapKind,
               detail: str | None, at: datetime) -> None:
    with transaction(conn):
        conn.execute("INSERT INTO ingest_gaps (source, window_start, window_end, kind, detail, recorded_at) "
                     "VALUES (?, ?, ?, ?, ?, ?)",
                     (source, db_time(start), db_time(end), kind, (detail or "")[:500] or None, db_time(at)))


def resolve_failed_gaps(conn: sqlite3.Connection, source: str, start: datetime, end: datetime,
                        at: datetime) -> int:
    """A later successful read of [start, end] covers earlier failed windows inside it."""
    with transaction(conn):
        cur = conn.execute(
            "UPDATE ingest_gaps SET resolved_at = ? WHERE source = ? AND kind = 'failed' AND resolved_at IS NULL "
            "AND window_start >= ? AND window_end <= ?", (db_time(at), source, db_time(start), db_time(end)))
        return cur.rowcount


def open_gaps(conn: sqlite3.Connection, source: str | None = None) -> list[Gap]:
    sql = "SELECT * FROM ingest_gaps WHERE resolved_at IS NULL"
    args: tuple[Any, ...] = ()
    if source is not None:
        sql += " AND source = ?"
        args = (source,)
    rows = conn.execute(sql + " ORDER BY window_start", args).fetchall()
    return [Gap(id=r["id"], source=r["source"], window_start=datetime.fromisoformat(r["window_start"]),
                window_end=datetime.fromisoformat(r["window_end"]), kind=r["kind"], detail=r["detail"],
                recorded_at=datetime.fromisoformat(r["recorded_at"]), resolved_at=_t(r["resolved_at"]))
            for r in rows]


def delete_gaps_before(conn: sqlite3.Connection, cutoff: datetime) -> int:
    with transaction(conn):
        return conn.execute("DELETE FROM ingest_gaps WHERE recorded_at < ?", (db_time(cutoff),)).rowcount
