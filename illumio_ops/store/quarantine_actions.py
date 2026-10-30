"""Quarantine actions (owner of quarantine_actions, in data/app.sqlite)."""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from datetime import datetime
from typing import Any


def add(conn: sqlite3.Connection, *, pce_url: str, org_id: str, at: datetime, by: str, action: str,
        workload_href: str, hostname: str | None, level: str | None, previous_level: str | None,
        original_labels: Sequence[dict[str, Any]], result: str, detail: str | None) -> int:
    cur = conn.execute(
        "INSERT INTO quarantine_actions (pce_url, org_id, at, by_user, action, workload_href, hostname, level, "
        "previous_level, original_labels_json, result, detail) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (pce_url, org_id, at.isoformat(), by, action, workload_href, hostname, level, previous_level,
         json.dumps(list(original_labels)), result, detail))
    return int(cur.lastrowid or 0)


def recent(conn: sqlite3.Connection, *, pce_url: str, org_id: str, workload_href: str | None,
           limit: int) -> list[sqlite3.Row]:
    sql = "SELECT * FROM quarantine_actions WHERE pce_url = ? AND org_id = ?"
    params: list[Any] = [pce_url, org_id]
    if workload_href is not None:
        sql += " AND workload_href = ?"
        params.append(workload_href)
    return conn.execute(sql + " ORDER BY id DESC LIMIT ?", [*params, limit]).fetchall()
