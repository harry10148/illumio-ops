"""Which days have been written to data/archive (archive_log)."""
from __future__ import annotations

import sqlite3
from datetime import datetime

from illumio_ops.store.flowdb.db import db_time, transaction


def record(conn: sqlite3.Connection, kind: str, day: str, rows: int, path: str, at: datetime) -> None:
    with transaction(conn):
        conn.execute("INSERT OR REPLACE INTO archive_log (kind, day, rows, path, written_at) VALUES (?, ?, ?, ?, ?)",
                     (kind, day, rows, path, db_time(at)))


def archived_days(conn: sqlite3.Connection, kind: str) -> set[str]:
    return {r[0] for r in conn.execute("SELECT day FROM archive_log WHERE kind = ?", (kind,))}


def entries_before(conn: sqlite3.Connection, day: str) -> list[tuple[str, str, str]]:
    return [(r[0], r[1], r[2]) for r in conn.execute("SELECT kind, day, path FROM archive_log WHERE day < ?", (day,))]


def forget(conn: sqlite3.Connection, kind: str, day: str) -> None:
    with transaction(conn):
        conn.execute("DELETE FROM archive_log WHERE kind = ? AND day = ?", (kind, day))
