"""VEN fleet writes (owner of fleet_actions, in data/app.sqlite): enforcement-mode changes and traffic update rate
increases, one row per host and attempt."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any


def add(conn: sqlite3.Connection, *, pce_url: str, org_id: str, batch_id: str, at: datetime, by: str, action: str,
        workload_href: str, hostname: str | None, previous_mode: str | None, target_mode: str | None, result: str,
        detail: str | None) -> int:
    cur = conn.execute(
        "INSERT INTO fleet_actions (pce_url, org_id, batch_id, at, by_user, action, workload_href, hostname, "
        "previous_mode, target_mode, result, detail) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (pce_url, org_id, batch_id, at.isoformat(), by, action, workload_href, hostname, previous_mode, target_mode,
         result, detail))
    return int(cur.lastrowid or 0)


def finish(conn: sqlite3.Connection, action_id: int, *, result: str, detail: str | None,
           previous_mode: str | None = None) -> None:
    conn.execute("UPDATE fleet_actions SET result = ?, detail = ?, previous_mode = COALESCE(?, previous_mode) "
                 "WHERE id = ?", (result, detail, previous_mode, action_id))


def recent(conn: sqlite3.Connection, *, pce_url: str, org_id: str, limit: int) -> list[sqlite3.Row]:
    params: list[Any] = [pce_url, org_id, limit]
    return conn.execute("SELECT * FROM fleet_actions WHERE pce_url = ? AND org_id = ? ORDER BY id DESC LIMIT ?",
                        params).fetchall()
