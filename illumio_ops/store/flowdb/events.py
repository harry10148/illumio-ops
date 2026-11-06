"""Writes to the events table."""
from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import datetime

from illumio_ops.domain.events import EventRecord
from illumio_ops.domain.values import DataOrigin
from illumio_ops.store.flowdb import archive
from illumio_ops.store.flowdb.db import db_time, transaction


def _known(conn: sqlite3.Connection, records: Sequence[EventRecord]) -> set[str]:
    hrefs = sorted({r.href for r in records})
    known: set[str] = set()
    for i in range(0, len(hrefs), 500):
        chunk = hrefs[i:i + 500]
        known |= {h for (h,) in conn.execute(f"SELECT href FROM events WHERE href IN ({','.join('?' * len(chunk))})",
                                            chunk)}
    return known


def unseen_events(conn: sqlite3.Connection, records: Sequence[EventRecord]) -> list[EventRecord]:
    """The events not stored yet. Read-only, so a caller can leave the rest out before it takes the
    write lock."""
    known = _known(conn, records)
    return [r for r in records if r.href not in known]


def upsert_events(conn: sqlite3.Connection, records: Sequence[EventRecord], *, origin: DataOrigin,
                  now: datetime) -> int:
    """Insert events not seen before (an event never changes); returns how many were new."""
    stamp = db_time(now)
    known = _known(conn, records)
    with transaction(conn):
        archive.mark_stale(conn, "events", {db_time(r.timestamp)[:10] for r in records if r.href not in known})
        before = conn.total_changes
        conn.executemany(
            "INSERT OR IGNORE INTO events (href, event_type, severity, status, timestamp, created_by_kind, "
            "created_by_name, created_by_href, workload_href, tamper_classification, raw_json, origin, ingested_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(r.href, r.event_type, r.severity, r.status, db_time(r.timestamp), r.created_by_kind,
              r.created_by_name, r.created_by_href, r.workload_href, r.tamper_classification, r.raw_json,
              origin.value, stamp) for r in records],
        )
        return conn.total_changes - before


def _expiring_days(conn: sqlite3.Connection, cutoff: datetime, archived_days: set[str] | None) -> list[str]:
    rows = conn.execute("SELECT DISTINCT substr(timestamp, 1, 10) FROM events WHERE timestamp < ?",
                        (db_time(cutoff),)).fetchall()
    return [r[0] for r in rows if archived_days is None or r[0] in archived_days]


def count_live_events_before(conn: sqlite3.Connection, cutoff: datetime, *, archived_days: set[str] | None,
                             after_id: int) -> int:
    """Live events delete_events_before would delete with an id above after_id (a SIEM cursor's, P7)."""
    return sum(int(conn.execute("SELECT COUNT(*) FROM events WHERE id > ? AND origin = 'ingest' AND timestamp < ? "
                                "AND substr(timestamp, 1, 10) = ?", (after_id, db_time(cutoff), d)).fetchone()[0])
               for d in _expiring_days(conn, cutoff, archived_days))


def delete_events_before(conn: sqlite3.Connection, cutoff: datetime, *, archived_days: set[str] | None) -> int:
    rows = conn.execute("SELECT DISTINCT substr(timestamp, 1, 10) FROM events WHERE timestamp < ?",
                        (db_time(cutoff),)).fetchall()
    days = [r[0] for r in rows if archived_days is None or r[0] in archived_days]
    with transaction(conn):
        return sum(conn.execute("DELETE FROM events WHERE timestamp < ? AND substr(timestamp, 1, 10) = ?",
                                (db_time(cutoff), d)).rowcount for d in days)


def events_for_workload(conn: sqlite3.Connection, href: str, *, start: datetime, end: datetime,
                        limit: int) -> list[sqlite3.Row]:
    """A workload's events between start and end, newest first (the alert detail's timeline): the events that name it,
    and those its VEN sent (collected events name no workload; the VEN is matched as the event pages match it)."""
    return conn.execute("SELECT e.event_type, e.severity, e.timestamp, e.tamper_classification FROM events e "
                        "LEFT JOIN workloads w ON w.ven_href = e.created_by_href "
                        "WHERE COALESCE(e.workload_href, w.href) = ? AND e.timestamp >= ? AND e.timestamp <= ? "
                        "ORDER BY e.timestamp DESC, e.id DESC LIMIT ?",
                        (href, db_time(start), db_time(end), limit)).fetchall()


# ── a throwaway store filled for a period (services/archive_read.py) ─────────────────────────────────────────────

def events_columns(conn: sqlite3.Connection) -> list[str]:
    """The table's columns but its row id (a copied or archived row gets a new one)."""
    return [r[1] for r in conn.execute("PRAGMA table_info(events)") if r[1] != "id"]


def copy_events_from(conn: sqlite3.Connection, schema: str, start: datetime, end: datetime) -> None:
    """The attached store's rows of [start, end) by timestamp; a row already here (same identity) is kept."""
    cols = ", ".join(events_columns(conn))
    conn.execute(f"INSERT OR IGNORE INTO events ({cols}) SELECT {cols} FROM {schema}.events "
                 "WHERE timestamp >= ? AND timestamp < ?", (db_time(start), db_time(end)))


def insert_archived_events(conn: sqlite3.Connection, keys: Sequence[str], rows: Sequence[Sequence[object]]) -> int:
    """Archived rows with these columns (an older line has fewer); a row already here is kept. Returns how many the
    table refused (a NOT NULL column an older line lacks): the others go in."""
    allowed = set(events_columns(conn))
    if any(k not in allowed for k in keys):
        raise ValueError("unknown column")
    sql = f"INSERT OR IGNORE INTO events ({', '.join(keys)}) VALUES ({', '.join('?' * len(keys))})"
    try:
        with transaction(conn):
            conn.executemany(sql, rows)
        return 0
    except sqlite3.IntegrityError:
        refused = 0
        for r in rows:
            try:
                conn.execute(sql, r)
            except sqlite3.IntegrityError:
                refused += 1
        return refused
