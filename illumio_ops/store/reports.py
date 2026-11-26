"""Report records in data/app.sqlite (owner of reports and report_schedule_state). The services decide what to generate and when; this
module only stores."""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Collection
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
    pce_target: str
    conclusion: str = ""
    attempts: int = 0


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
        email_status=r["email_status"], email_detail=r["email_detail"], pce_target=r["pce_target"],
        conclusion=r["conclusion"], attempts=r["attempts"])


def insert(conn: sqlite3.Connection, *, report_type: str, params_json: str, status: ReportStatus, trigger: str,
           schedule_id: str | None, pce_label: str, period_start: datetime, period_end: datetime,
           created_at: datetime, error_key: str | None = None, error_detail: str | None = None,
           pce_target: str = "") -> int:
    finished = _t(created_at) if status is ReportStatus.FAILED else None
    cur = conn.execute(
        "INSERT INTO reports (report_type, params_json, status, trigger, schedule_id, pce_label, period_start, "
        "period_end, created_at, finished_at, error_key, error_detail, pce_target) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (report_type, params_json, status.value, trigger, schedule_id, pce_label, _t(period_start), _t(period_end),
         _t(created_at), finished, error_key, error_detail, pce_target))
    conn.commit()
    return int(cur.lastrowid or 0)


def claim_next(conn: sqlite3.Connection, *, at: datetime, only: Collection[str] | None = None,
               skip: Collection[str] = ()) -> ReportRow | None:
    """The oldest queued report, now marked running, in one statement (a delete in between cannot be lost).
    `only` / `skip`: the report types this caller makes (a lane of the queue: services.reports.generate.run_queued)."""
    where, args = "status = 'queued'", []
    if only is not None:
        where += f" AND report_type IN ({','.join('?' * len(only))})"
        args += sorted(only)
    if skip:
        where += f" AND report_type NOT IN ({','.join('?' * len(skip))})"
        args += sorted(skip)
    claimed = conn.execute(
        "UPDATE reports SET status = 'running', started_at = ?, attempts = attempts + 1 WHERE id = "
        f"(SELECT id FROM reports WHERE {where} ORDER BY id LIMIT 1) RETURNING *", (_t(at), *args)).fetchone()
    conn.commit()
    return _row(claimed) if claimed is not None else None


def finish(conn: sqlite3.Connection, report_id: int, *, status: ReportStatus, at: datetime, files: list[str],
           kpis: list[dict[str, Any]], error_key: str | None = None, error_detail: str | None = None,
           conclusion: str = "", email_status: str | None = None) -> None:
    """email_status: "sending" for a report about to be emailed, in the same change as "done" — a reader between
    the two (the check on the schedules' reports, a restart) must never see a finished report whose email is
    neither going out nor over."""
    conn.execute("UPDATE reports SET status = ?, finished_at = ?, files_json = ?, kpis_json = ?, error_key = ?, "
                 "error_detail = ?, conclusion = ?, email_status = COALESCE(?, email_status) WHERE id = ?",
                 (status.value, _t(at), json.dumps(files), json.dumps(kpis, default=str), error_key, error_detail,
                  conclusion, email_status, report_id))
    conn.commit()


def set_email(conn: sqlite3.Connection, report_id: int, *, status: str, detail: str | None) -> None:
    conn.execute("UPDATE reports SET email_status = ?, email_detail = ? WHERE id = ?", (status, detail, report_id))
    conn.commit()


MAX_ATTEMPTS = 2  # a report is started at most this many times


def recover(conn: sqlite3.Connection, *, at: datetime, error_key: str) -> tuple[int, int, int]:
    """What a stopped service left half done, put right once at start-up: (reports queued again, reports failed,
    emails marked interrupted). A report left running starts again from the start — unless it was already started
    MAX_ATTEMPTS times, when it is failed with `error_key` (it may be what stopped the service). An email left
    "sending" is marked interrupted: whether it went out is not known, and the rendered report is not kept to send
    again."""
    failed = conn.execute(
        "UPDATE reports SET status = 'failed', finished_at = ?, error_key = ?, error_detail = NULL "
        "WHERE status = 'running' AND attempts >= ?", (_t(at), error_key, MAX_ATTEMPTS)).rowcount
    queued = conn.execute("UPDATE reports SET status = 'queued', started_at = NULL WHERE status = 'running'").rowcount
    mails = conn.execute("UPDATE reports SET email_status = 'interrupted', email_detail = NULL "
                         "WHERE email_status = 'sending'").rowcount
    conn.commit()
    return queued, failed, mails


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


def delete(conn: sqlite3.Connection, report_ids: list[int]) -> list[int]:
    """Delete the rows that are not running; returns the ids actually deleted (only their files may go)."""
    gone = []
    for i in report_ids:
        if conn.execute("DELETE FROM reports WHERE id = ? AND status != 'running' RETURNING id", (i,)).fetchone():
            gone.append(i)
    conn.commit()
    return gone


def schedule_last_due(conn: sqlite3.Connection) -> dict[str, datetime]:
    return {r[0]: datetime.fromisoformat(r[1]) for r in conn.execute(
        "SELECT schedule_id, last_due FROM report_schedule_state")}


def set_schedule_last_due(conn: sqlite3.Connection, schedule_id: str, last_due: datetime) -> None:
    conn.execute("INSERT INTO report_schedule_state (schedule_id, last_due) VALUES (?, ?) "
                 "ON CONFLICT(schedule_id) DO UPDATE SET last_due = excluded.last_due", (schedule_id, _t(last_due)))
    conn.commit()


def forget_schedules_except(conn: sqlite3.Connection, keep: list[str]) -> None:
    conn.execute(f"DELETE FROM report_schedule_state WHERE schedule_id NOT IN ({','.join('?' * len(keep))})", keep)
    conn.commit()


def schedule_reports(conn: sqlite3.Connection, schedule_id: str, *, limit: int) -> list[ReportRow]:
    """The schedule's newest reports, newest first."""
    rows = conn.execute("SELECT * FROM reports WHERE schedule_id = ? ORDER BY id DESC LIMIT ?",
                        (schedule_id, limit)).fetchall()
    return [_row(r) for r in rows]


def ids_beyond_keep(conn: sqlite3.Connection, schedule_id: str, keep: int) -> list[int]:
    return [r[0] for r in conn.execute(
        "SELECT id FROM reports WHERE schedule_id = ? AND status IN ('done', 'failed') ORDER BY id DESC "
        "LIMIT -1 OFFSET ?", (schedule_id, keep))]


def done_ending_at(conn: sqlite3.Connection, report_type: str, period_end: datetime, pce_target: str) -> list[ReportRow]:
    """Finished reports of a type whose period ended at `period_end`, for one PCE, newest first: the previous
    period of a report starting there."""
    return [_row(r) for r in conn.execute(
        "SELECT * FROM reports WHERE report_type = ? AND status = 'done' AND period_end = ? AND pce_target = ? "
        "ORDER BY id DESC", (report_type, _t(period_end), pce_target))]


def done_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Finished reports kept, per type (the reports page's copies)."""
    return {r[0]: int(r[1]) for r in conn.execute(
        "SELECT report_type, COUNT(*) FROM reports WHERE status = 'done' GROUP BY report_type")}


def move_pce(conn: sqlite3.Connection, *, old_target: str, new_target: str) -> int:
    """The same PCE moved to a new address (System › PCE connection, decision D3): its reports stay its own, so the
    next report still compares with them. Targets are services.reports.generate.pce_target values."""
    # a period both addresses have numbers for keeps the new address's
    conn.execute("UPDATE OR IGNORE report_kpi_history SET pce_target = ? WHERE pce_target = ?", (new_target, old_target))
    conn.execute("DELETE FROM report_kpi_history WHERE pce_target = ?", (old_target,))
    return int(conn.execute("UPDATE reports SET pce_target = ? WHERE pce_target = ?", (new_target, old_target)).rowcount)


# ── key numbers kept apart from the reports ──────────────────────────────────

@dataclass(frozen=True)
class KpiRecord:
    period_start: datetime
    period_end: datetime
    kpis: list[dict[str, Any]]
    recorded_at: datetime
    complete: bool | None  # the report read its whole period; None: not known


def record_kpis(conn: sqlite3.Connection, *, report_type: str, pce_target: str, match_json: str,
                period_start: datetime, period_end: datetime, kpis: list[dict[str, Any]], at: datetime,
                complete: bool | None, replace: bool = True) -> None:
    """One finished report's key numbers. A later report of the same period replaces them (replace False: only
    when there are none yet — filling in from the reports kept, at start-up)."""
    verb = "INSERT OR REPLACE" if replace else "INSERT OR IGNORE"
    conn.execute(f"{verb} INTO report_kpi_history (report_type, pce_target, match_json, period_start, period_end, "
                 "kpis_json, recorded_at, complete) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                 (report_type, pce_target, match_json, _t(period_start), _t(period_end),
                  json.dumps(kpis, default=str), _t(at), None if complete is None else int(complete)))
    conn.commit()


def kpis_ending_at(conn: sqlite3.Connection, *, report_type: str, pce_target: str, match_json: str,
                   period_end: datetime) -> list[KpiRecord]:
    """The key numbers recorded for periods ending at `period_end`, the longest period first."""
    return [KpiRecord(datetime.fromisoformat(r[0]), datetime.fromisoformat(r[1]), json.loads(r[2]),
                      datetime.fromisoformat(r[3]), None if r[4] is None else bool(r[4]))
            for r in conn.execute(
                "SELECT period_start, period_end, kpis_json, recorded_at, complete FROM report_kpi_history "
                "WHERE report_type = ? "
                "AND pce_target = ? AND match_json = ? AND period_end = ? ORDER BY period_start",
                (report_type, pce_target, match_json, _t(period_end)))]


def done_reports(conn: sqlite3.Connection) -> list[ReportRow]:
    return [_row(r) for r in conn.execute("SELECT * FROM reports WHERE status = 'done' ORDER BY id")]


def forget_kpis_before(conn: sqlite3.Connection, before: datetime) -> int:
    n = conn.execute("DELETE FROM report_kpi_history WHERE period_end < ?", (_t(before),)).rowcount
    conn.commit()
    return int(n)


def unchecked_schedule_reports(conn: sqlite3.Connection) -> list[ReportRow]:
    """The schedules' reports the report check has not looked at and that are over: made or failed, and their email
    sent or not (one queued, being made or being emailed is looked at once it is over)."""
    return [_row(r) for r in conn.execute(
        "SELECT * FROM reports WHERE schedule_id IS NOT NULL AND alert_checked = 0 AND status IN ('done', 'failed') "
        "AND COALESCE(email_status, '') != 'sending' ORDER BY id")]


def mark_checked(conn: sqlite3.Connection, report_ids: list[int]) -> None:
    conn.executemany("UPDATE reports SET alert_checked = 1 WHERE id = ?", [(i,) for i in report_ids])
    conn.commit()


def last_durations(conn: sqlite3.Connection) -> dict[str, tuple[datetime, datetime, datetime, datetime]]:
    """Per type, the newest finished report's (period_start, period_end, started_at, finished_at)."""
    return {r[0]: tuple(datetime.fromisoformat(x) for x in r[1:5]) for r in conn.execute(  # type: ignore[misc]
        "SELECT report_type, period_start, period_end, started_at, finished_at FROM reports WHERE id IN "
        "(SELECT MAX(id) FROM reports WHERE status = 'done' AND started_at IS NOT NULL GROUP BY report_type)")}
