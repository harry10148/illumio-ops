"""Background job health (owner of table job_health): when each job last ran and how it went."""
from __future__ import annotations

import sqlite3
from datetime import datetime

from pydantic import BaseModel


class JobHealth(BaseModel):
    job_id: str
    last_started_at: datetime
    last_finished_at: datetime | None
    last_ok: bool | None
    last_error: str | None
    runs: int
    failures: int


def record_start(conn: sqlite3.Connection, job_id: str, at: datetime) -> None:
    with conn:
        conn.execute(
            "INSERT INTO job_health (job_id, last_started_at) VALUES (?, ?) "
            "ON CONFLICT(job_id) DO UPDATE SET last_started_at = excluded.last_started_at",
            (job_id, at.isoformat()),
        )


def record_finish(conn: sqlite3.Connection, job_id: str, at: datetime, error: str | None) -> None:
    with conn:
        conn.execute(
            "UPDATE job_health SET last_finished_at = ?, last_ok = ?, last_error = ?, "
            "runs = runs + 1, failures = failures + ? WHERE job_id = ?",
            (at.isoformat(), error is None, error, 0 if error is None else 1, job_id),
        )


def list_health(conn: sqlite3.Connection) -> list[JobHealth]:
    rows = conn.execute(
        "SELECT job_id, last_started_at, last_finished_at, last_ok, last_error, runs, failures "
        "FROM job_health ORDER BY job_id"
    ).fetchall()
    return [JobHealth(
        job_id=r["job_id"],
        last_started_at=datetime.fromisoformat(r["last_started_at"]),
        last_finished_at=datetime.fromisoformat(r["last_finished_at"]) if r["last_finished_at"] else None,
        last_ok=None if r["last_ok"] is None else bool(r["last_ok"]),
        last_error=r["last_error"],
        runs=r["runs"],
        failures=r["failures"],
    ) for r in rows]
