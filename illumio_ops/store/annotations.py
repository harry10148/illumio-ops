"""Known causes of tampering (owner of tamper_annotations, in data/app.sqlite)."""
from __future__ import annotations

import sqlite3
from datetime import datetime


def add(conn: sqlite3.Connection, *, pce_url: str, org_id: str, host_href: str | None, pattern: str | None,
        process: str | None, reason: str, created_by: str, at: datetime) -> int:
    cur = conn.execute("INSERT INTO tamper_annotations (pce_url, org_id, host_href, pattern, process, reason, created_at, "
                       "created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                       (pce_url, org_id, host_href, pattern, process, reason, at.isoformat(), created_by))
    return int(cur.lastrowid or 0)


def remove(conn: sqlite3.Connection, annotation_id: int, *, pce_url: str, org_id: str) -> bool:
    return conn.execute("DELETE FROM tamper_annotations WHERE id = ? AND pce_url = ? AND org_id = ?",
                        (annotation_id, pce_url, org_id)).rowcount > 0


def for_pce(conn: sqlite3.Connection, pce_url: str, org_id: str) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM tamper_annotations WHERE pce_url = ? AND org_id = ? ORDER BY id",
                        (pce_url, org_id)).fetchall()
