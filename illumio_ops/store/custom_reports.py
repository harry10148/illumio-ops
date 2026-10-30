"""Custom reports (owner of custom_reports, in data/app.sqlite)."""
from __future__ import annotations

import sqlite3
from datetime import datetime


def insert(conn: sqlite3.Connection, *, name: str, sections_json: str, by: str, at: datetime) -> int:
    cur = conn.execute("INSERT INTO custom_reports (name, sections_json, created_by, created_at, updated_at) "
                       "VALUES (?, ?, ?, ?, ?)", (name, sections_json, by, at.isoformat(), at.isoformat()))
    return int(cur.lastrowid or 0)


def update(conn: sqlite3.Connection, report_id: int, *, name: str, sections_json: str, at: datetime) -> bool:
    return conn.execute("UPDATE custom_reports SET name = ?, sections_json = ?, updated_at = ? WHERE id = ?",
                        (name, sections_json, at.isoformat(), report_id)).rowcount > 0


def get(conn: sqlite3.Connection, report_id: int) -> sqlite3.Row | None:
    row: sqlite3.Row | None = conn.execute("SELECT * FROM custom_reports WHERE id = ?", (report_id,)).fetchone()
    return row


def all_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM custom_reports ORDER BY name, id").fetchall()


def delete(conn: sqlite3.Connection, report_id: int) -> bool:
    return conn.execute("DELETE FROM custom_reports WHERE id = ?", (report_id,)).rowcount > 0
