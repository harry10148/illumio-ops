"""Writes to the events table."""
from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import datetime

from illumio_ops.domain.events import EventRecord
from illumio_ops.domain.values import DataOrigin
from illumio_ops.store.flowdb.db import db_time, transaction


def upsert_events(conn: sqlite3.Connection, records: Sequence[EventRecord], *, origin: DataOrigin,
                  now: datetime) -> int:
    """Insert events not seen before (an event never changes); returns how many were new."""
    stamp = db_time(now)
    with transaction(conn):
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


def delete_events_before(conn: sqlite3.Connection, cutoff: datetime, *, archived_days: set[str] | None) -> int:
    rows = conn.execute("SELECT DISTINCT substr(timestamp, 1, 10) FROM events WHERE timestamp < ?",
                        (db_time(cutoff),)).fetchall()
    days = [r[0] for r in rows if archived_days is None or r[0] in archived_days]
    with transaction(conn):
        return sum(conn.execute("DELETE FROM events WHERE timestamp < ? AND substr(timestamp, 1, 10) = ?",
                                (db_time(cutoff), d)).rowcount for d in days)
