"""Rule schedules and their run log (owner of rule_schedules and rule_schedule_runs, in data/app.sqlite)."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Literal

Action = Literal["enable", "disable", "expire", "skip_draft", "not_found", "error", "note", "note_cleared"]
Result = Literal["ok", "failed", "skipped"]
DETAIL_MAX = 300


def create(conn: sqlite3.Connection, *, pce_url: str, org_id: str, href: str, is_ruleset: bool, name: str,
           ruleset_name: str, summary: str, plan_json: str, paused: bool, pce_status: str, by: str,
           at: datetime) -> int:
    cur = conn.execute(
        "INSERT INTO rule_schedules (pce_url, org_id, href, is_ruleset, name, ruleset_name, summary, plan_json, paused, "
        "pce_status, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (pce_url, org_id, href, int(is_ruleset), name, ruleset_name, summary, plan_json, int(paused), pce_status, by,
         at.isoformat(), at.isoformat()))
    return int(cur.lastrowid or 0)


def get(conn: sqlite3.Connection, schedule_id: int) -> sqlite3.Row | None:
    row: sqlite3.Row | None = conn.execute("SELECT * FROM rule_schedules WHERE id = ?", (schedule_id,)).fetchone()
    return row


def by_href(conn: sqlite3.Connection, *, pce_url: str, org_id: str, href: str) -> sqlite3.Row | None:
    row: sqlite3.Row | None = conn.execute(
        "SELECT * FROM rule_schedules WHERE pce_url = ? AND org_id = ? AND href = ?", (pce_url, org_id, href)).fetchone()
    return row


def list_for(conn: sqlite3.Connection, *, pce_url: str, org_id: str) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM rule_schedules WHERE pce_url = ? AND org_id = ? ORDER BY ruleset_name, name, id",
                        (pce_url, org_id)).fetchall()


def update_plan(conn: sqlite3.Connection, schedule_id: int, plan_json: str, at: datetime) -> None:
    conn.execute("UPDATE rule_schedules SET plan_json = ?, updated_at = ? WHERE id = ?",
                 (plan_json, at.isoformat(), schedule_id))


def set_paused(conn: sqlite3.Connection, schedule_id: int, paused: bool, at: datetime) -> bool:
    return conn.execute("UPDATE rule_schedules SET paused = ?, updated_at = ? WHERE id = ?",
                        (int(paused), at.isoformat(), schedule_id)).rowcount > 0


def set_checked(conn: sqlite3.Connection, schedule_id: int, *, pce_status: str, live: str, at: datetime) -> None:
    conn.execute("UPDATE rule_schedules SET pce_status = ?, live = ?, last_checked_at = ? WHERE id = ?",
                 (pce_status, live, at.isoformat(), schedule_id))


def delete(conn: sqlite3.Connection, schedule_id: int) -> bool:
    return conn.execute("DELETE FROM rule_schedules WHERE id = ?", (schedule_id,)).rowcount > 0


def add_run(conn: sqlite3.Connection, *, pce_url: str, org_id: str, schedule_id: int | None, href: str, name: str,
            at: datetime, action: Action, result: Result, status: int | None = None,
            detail: str | None = None) -> None:
    conn.execute(
        "INSERT INTO rule_schedule_runs (pce_url, org_id, schedule_id, href, name, at, action, result, status, detail) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (pce_url, org_id, schedule_id, href, name, at.isoformat(), action, result, status,
         detail[:DETAIL_MAX] if detail else None))


def runs(conn: sqlite3.Connection, *, pce_url: str, org_id: str, limit: int,
         schedule_id: int | None = None) -> list[sqlite3.Row]:
    sql = "SELECT * FROM rule_schedule_runs WHERE pce_url = ? AND org_id = ?"
    args: list[object] = [pce_url, org_id]
    if schedule_id is not None:
        sql += " AND schedule_id = ?"
        args.append(schedule_id)
    return conn.execute(sql + " ORDER BY at DESC, id DESC LIMIT ?", [*args, limit]).fetchall()


def last_run(conn: sqlite3.Connection, schedule_id: int) -> sqlite3.Row | None:
    row: sqlite3.Row | None = conn.execute(
        "SELECT * FROM rule_schedule_runs WHERE schedule_id = ? ORDER BY at DESC, id DESC LIMIT 1",
        (schedule_id,)).fetchone()
    return row


def prune_runs(conn: sqlite3.Connection, before: datetime) -> int:
    return conn.execute("DELETE FROM rule_schedule_runs WHERE at < ?", (before.isoformat(),)).rowcount


def move_pce(conn: sqlite3.Connection, *, old_url: str, new_url: str, org_id: str) -> int:
    """The same PCE moved to a new address (System › PCE connection, decision D3): its rows follow it."""
    # OR IGNORE: a target already scheduled under the new address (the operator was there before) keeps that one.
    n = conn.execute("UPDATE OR IGNORE rule_schedules SET pce_url = ? WHERE pce_url = ? AND org_id = ?",
                     (new_url, old_url, org_id)).rowcount
    conn.execute("UPDATE rule_schedule_runs SET pce_url = ? WHERE pce_url = ? AND org_id = ?", (new_url, old_url, org_id))
    return int(n)
