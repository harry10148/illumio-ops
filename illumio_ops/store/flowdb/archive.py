"""Which days have been written to data/archive (archive_log). A day whose rows change after its
file was written is marked stale: the archive job writes it again and retention keeps its rows
until then."""
from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import datetime

from illumio_ops.store.flowdb.db import db_time, transaction


def record(conn: sqlite3.Connection, kind: str, day: str, rows: int, path: str, at: datetime) -> None:
    with transaction(conn):
        conn.execute("INSERT OR REPLACE INTO archive_log (kind, day, rows, path, written_at) VALUES (?, ?, ?, ?, ?)",
                     (kind, day, rows, path, db_time(at)))


def archived_days(conn: sqlite3.Connection, kind: str) -> set[str]:
    """Days whose file holds every row the database has for them."""
    return {r[0] for r in conn.execute("SELECT day FROM archive_log WHERE kind = ? AND stale = 0", (kind,))}


def mark_stale(conn: sqlite3.Connection, kind: str, days: Iterable[str]) -> None:
    """Rows of these days changed; called by the writers of flows and events."""
    with transaction(conn):
        conn.executemany("UPDATE archive_log SET stale = 1 WHERE kind = ? AND day = ? AND stale = 0",
                         [(kind, d) for d in sorted(set(days))])


def entries_before(conn: sqlite3.Connection, day: str) -> list[tuple[str, str, str]]:
    return [(r[0], r[1], r[2]) for r in conn.execute("SELECT kind, day, path FROM archive_log WHERE day < ?", (day,))]


def forget(conn: sqlite3.Connection, kind: str, day: str) -> None:
    with transaction(conn):
        conn.execute("DELETE FROM archive_log WHERE kind = ? AND day = ?", (kind, day))
