"""Report records in data/app.sqlite (owner of reports). The services decide what to generate and when; this
module only stores."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from illumio_ops.domain.values import ReportStatus


def _t(value: datetime) -> str:
    return value.isoformat()


@dataclass(frozen=True)
class ReportRow:
    id: int
    report_type: str
    params: dict[str, Any]
    status: ReportStatus
    trigger: str
    schedule_id: str | None
    pce_label: str
    period_start: datetime
    period_end: datetime
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error_key: str | None
    error_detail: str | None
    files: list[str]
    kpis: list[dict[str, Any]]
    email_status: str | None
    email_detail: str | None


def _opt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _row(r: sqlite3.Row) -> ReportRow:
    return ReportRow(
        id=r["id"], report_type=r["report_type"], params=json.loads(r["params_json"]),
        status=ReportStatus(r["status"]), trigger=r["trigger"], schedule_id=r["schedule_id"],
        pce_label=r["pce_label"], period_start=datetime.fromisoformat(r["period_start"]),
        period_end=datetime.fromisoformat(r["period_end"]), created_at=datetime.fromisoformat(r["created_at"]),
        started_at=_opt(r["started_at"]), finished_at=_opt(r["finished_at"]), error_key=r["error_key"],
        error_detail=r["error_detail"], files=json.loads(r["files_json"]), kpis=json.loads(r["kpis_json"]),
        email_status=r["email_status"], email_detail=r["email_detail"])


def insert(conn: sqlite3.Connection, *, report_type: str, params_json: str, status: ReportStatus, trigger: str,
           schedule_id: str | None, pce_label: str, period_start: datetime, period_end: datetime,
           created_at: datetime, error_key: str | None = None, error_detail: str | None = None) -> int:
    finished = _t(created_at) if status is ReportStatus.FAILED else None
    cur = conn.execute(
        "INSERT INTO reports (report_type, params_json, status, trigger, schedule_id, pce_label, period_start, "
        "period_end, created_at, finished_at, error_key, error_detail) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (report_type, params_json, status.value, trigger, schedule_id, pce_label, _t(period_start), _t(period_end),
         _t(created_at), finished, error_key, error_detail))
    conn.commit()
    return int(cur.lastrowid or 0)


def claim_next(conn: sqlite3.Connection, *, at: datetime) -> ReportRow | None:
    """The oldest queued report, now marked running (one writer: the reports job)."""
    row = conn.execute("SELECT id FROM reports WHERE status = 'queued' ORDER BY id LIMIT 1").fetchone()
    if row is None:
        return None
    conn.execute("UPDATE reports SET status = 'running', started_at = ? WHERE id = ? AND status = 'queued'",
                 (_t(at), row["id"]))
    conn.commit()
    return get(conn, row["id"])


def finish(conn: sqlite3.Connection, report_id: int, *, status: ReportStatus, at: datetime, files: list[str],
           kpis: list[dict[str, Any]], error_key: str | None = None, error_detail: str | None = None) -> None:
    conn.execute("UPDATE reports SET status = ?, finished_at = ?, files_json = ?, kpis_json = ?, error_key = ?, "
                 "error_detail = ? WHERE id = ?",
                 (status.value, _t(at), json.dumps(files), json.dumps(kpis, default=str), error_key, error_detail,
                  report_id))
    conn.commit()


def set_email(conn: sqlite3.Connection, report_id: int, *, status: str, detail: str | None) -> None:
    conn.execute("UPDATE reports SET email_status = ?, email_detail = ? WHERE id = ?", (status, detail, report_id))
    conn.commit()


def requeue_running(conn: sqlite3.Connection) -> int:
    """Reports left running by a stopped service run again from the start."""
    cur = conn.execute("UPDATE reports SET status = 'queued', started_at = NULL WHERE status = 'running'")
    conn.commit()
    return cur.rowcount


def get(conn: sqlite3.Connection, report_id: int) -> ReportRow | None:
    r = conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
    return _row(r) if r else None


def list_reports(conn: sqlite3.Connection, *, limit: int, offset: int) -> tuple[list[ReportRow], int]:
    total = conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
    rows = conn.execute("SELECT * FROM reports ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
    return [_row(r) for r in rows], int(total)


def ids_created_before(conn: sqlite3.Connection, before: datetime) -> list[int]:
    return [r[0] for r in conn.execute(
        "SELECT id FROM reports WHERE created_at < ? AND status != 'running' ORDER BY id", (_t(before),))]


def delete(conn: sqlite3.Connection, report_ids: list[int]) -> None:
    conn.executemany("DELETE FROM reports WHERE id = ? AND status != 'running'", [(i,) for i in report_ids])
    conn.commit()
