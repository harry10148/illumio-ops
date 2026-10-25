"""Lateral-movement analysis results (owner of detections, analysis_runs, analysis_results,
lateral_snapshot_daily and focus_items). The services serialise; this module only stores."""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from illumio_ops.domain.values import SEVERITY_ORDER, Severity
from illumio_ops.store.flowdb.db import db_time, transaction


@dataclass(frozen=True)
class DetectionWrite:
    detector: str
    fingerprint: str
    subject_key: str
    severity: str
    first_seen: datetime
    last_seen: datetime
    critical_asset: bool
    summary_json: str
    segment_json: str
    confidence_json: str


@dataclass(frozen=True)
class FocusWrite:
    fingerprint: str
    kind: str
    score: float
    item_json: str


def _higher(a: str, b: str) -> str:
    return a if SEVERITY_ORDER.index(Severity(a)) >= SEVERITY_ORDER.index(Severity(b)) else b


def upsert_detections(conn: sqlite3.Connection, rows: Sequence[DetectionWrite], *, dedup: Mapping[str, timedelta],
                      late: bool, at: datetime) -> tuple[int, int]:
    """(new rows, updated rows). A detection that starts within its detector's dedup window of the
    fingerprint's latest row extends that row; the severity never goes down."""
    new = updated = 0
    stamp = db_time(at)
    with transaction(conn):
        for d in rows:
            old = conn.execute(
                "SELECT id, last_seen, severity FROM detections WHERE detector = ? AND fingerprint = ? "
                "ORDER BY last_seen DESC LIMIT 1", (d.detector, d.fingerprint)).fetchone()
            if old is not None and d.first_seen - datetime.fromisoformat(old["last_seen"]) <= dedup[d.detector]:
                conn.execute(
                    "UPDATE detections SET first_seen = MIN(first_seen, ?), last_seen = MAX(last_seen, ?), "
                    "occurrences = occurrences + 1, severity = ?, critical_asset = MAX(critical_asset, ?), "
                    "summary_json = ?, segment_json = ?, confidence_json = ?, updated_at = ? WHERE id = ?",
                    (db_time(d.first_seen), db_time(d.last_seen), _higher(old["severity"], d.severity),
                     int(d.critical_asset), d.summary_json, d.segment_json, d.confidence_json, stamp, old["id"]))
                updated += 1
            else:
                conn.execute(
                    "INSERT INTO detections (detector, fingerprint, subject_key, severity, first_seen, last_seen, "
                    "occurrences, late, critical_asset, summary_json, segment_json, confidence_json, created_at, "
                    "updated_at) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)",
                    (d.detector, d.fingerprint, d.subject_key, d.severity, db_time(d.first_seen),
                     db_time(d.last_seen), int(late), int(d.critical_asset), d.summary_json, d.segment_json,
                     d.confidence_json, stamp, stamp))
                new += 1
    return new, updated


def detections_since(conn: sqlite3.Connection, since: datetime, *, detectors: Collection[str] = (),
                     limit: int) -> list[sqlite3.Row]:
    sql = "SELECT * FROM detections WHERE last_seen >= ?"
    params: list[Any] = [db_time(since)]
    if detectors:
        sql += f" AND detector IN ({','.join('?' * len(detectors))})"
        params.extend(detectors)
    return conn.execute(sql + " ORDER BY last_seen DESC, id DESC LIMIT ?", [*params, limit]).fetchall()


def get_run(conn: sqlite3.Connection, kind: str) -> sqlite3.Row | None:
    row: sqlite3.Row | None = conn.execute("SELECT * FROM analysis_runs WHERE kind = ?", (kind,)).fetchone()
    return row


def set_run(conn: sqlite3.Connection, kind: str, *, started_at: datetime | None = None, ok_at: datetime | None = None,
            watermark: datetime | None = None, error: str | None = None,
            status: Mapping[str, Any] | None = None) -> None:
    """Set the given fields, keep the others. A success clears the last error."""
    values: dict[str, Any] = {}
    if started_at is not None:
        values["last_started_at"] = db_time(started_at)
    if ok_at is not None:
        values["last_ok_at"] = db_time(ok_at)
        values["last_error"] = None
    if watermark is not None:
        values["watermark"] = db_time(watermark)
    if error is not None:
        values["last_error"] = error
    if status is not None:
        values["status_json"] = json.dumps(status, default=str)
    with transaction(conn):
        conn.execute("INSERT INTO analysis_runs (kind) VALUES (?) ON CONFLICT(kind) DO NOTHING", (kind,))
        if values:
            conn.execute(f"UPDATE analysis_runs SET {', '.join(f'{k} = ?' for k in values)} WHERE kind = ?",
                         [*values.values(), kind])


def write_result(conn: sqlite3.Connection, kind: str, *, params: Mapping[str, Any], result: Mapping[str, Any],
                 at: datetime) -> None:
    conn.execute("INSERT INTO analysis_results (kind, computed_at, params_json, result_json) VALUES (?, ?, ?, ?) "
                 "ON CONFLICT(kind) DO UPDATE SET computed_at = excluded.computed_at, "
                 "params_json = excluded.params_json, result_json = excluded.result_json",
                 (kind, db_time(at), json.dumps(params, default=str), json.dumps(result, default=str)))


def read_result(conn: sqlite3.Connection, kind: str) -> sqlite3.Row | None:
    row: sqlite3.Row | None = conn.execute("SELECT * FROM analysis_results WHERE kind = ?", (kind,)).fetchone()
    return row


def write_lateral_snapshot(conn: sqlite3.Connection, day: str, metrics: Mapping[str, Any]) -> None:
    conn.execute("INSERT INTO lateral_snapshot_daily (day, metrics_json) VALUES (?, ?) "
                 "ON CONFLICT(day) DO UPDATE SET metrics_json = excluded.metrics_json",
                 (day, json.dumps(metrics, default=str)))


def upsert_focus(conn: sqlite3.Connection, items: Sequence[FocusWrite], *, at: datetime) -> dict[str, datetime]:
    """Record the current items (first_seen kept across runs, also after an item was inactive) and mark
    every other item inactive. Returns each given item's first_seen."""
    stamp = db_time(at)
    with transaction(conn):
        for it in items:
            conn.execute(
                "INSERT INTO focus_items (fingerprint, kind, first_seen, last_seen, active, score, item_json) "
                "VALUES (?, ?, ?, ?, 1, ?, ?) ON CONFLICT(fingerprint) DO UPDATE SET kind = excluded.kind, "
                "last_seen = excluded.last_seen, active = 1, score = excluded.score, item_json = excluded.item_json",
                (it.fingerprint, it.kind, stamp, stamp, it.score, it.item_json))
        keep = [it.fingerprint for it in items]
        conn.execute(f"UPDATE focus_items SET active = 0 WHERE fingerprint NOT IN ({','.join('?' * len(keep))})",
                     keep)
        if not keep:
            return {}
        return {fp: datetime.fromisoformat(first) for fp, first in conn.execute(
            f"SELECT fingerprint, first_seen FROM focus_items WHERE fingerprint IN ({','.join('?' * len(keep))})",
            keep)}


def delete_expired(conn: sqlite3.Connection, *, detections_before: datetime, focus_before: datetime,
                   snapshot_day_before: str) -> int:
    with transaction(conn):
        n = conn.execute("DELETE FROM detections WHERE last_seen < ?", (db_time(detections_before),)).rowcount
        n += conn.execute("DELETE FROM focus_items WHERE active = 0 AND last_seen < ?",
                          (db_time(focus_before),)).rowcount
        n += conn.execute("DELETE FROM lateral_snapshot_daily WHERE day < ?", (snapshot_day_before,)).rowcount
    return n
