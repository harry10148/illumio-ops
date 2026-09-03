"""Persisted alert records — the inbox behind the v3 alert → flow → rule journey.

One small SQLite file (`logs/alerts.sqlite`, next to `state.json`) that the
Reporter writes to right after a dispatch and the GUI reads for the inbox.
It is deliberately separate from `state.json` (a single JSON document that
must not grow without bound) and from the pce_cache DB (which carries its own
`user_version` upgrade path). This module is the only code that touches it.

Rows are keyed on the rule's stable `id` (a uuid, or an integer on older
configs — always stored as text, matching `_check_cooldown`'s key), never on
the rule's position in the list, which is computed at read time.
"""
from __future__ import annotations

import datetime
import json
import os
import sqlite3
from typing import Any, Optional

from src.config import ROOT_DIR

ALERT_TYPES = ("event", "traffic", "bandwidth", "system")
ALERT_STATUSES = ("new", "ack", "done")

_SCHEMA_VERSION = 1
_SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  fired_at TEXT NOT NULL,
  type TEXT NOT NULL CHECK (type IN ('event','traffic','bandwidth','system')),
  rule_id TEXT,
  rule_name TEXT NOT NULL,
  severity TEXT NOT NULL,
  summary TEXT NOT NULL,
  criteria TEXT NOT NULL DEFAULT '',
  payload_json TEXT NOT NULL,
  dispatch_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new','ack','done')),
  status_by TEXT,
  status_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_alerts_status_fired ON alerts(status, fired_at DESC);
CREATE INDEX IF NOT EXISTS ix_alerts_type_fired ON alerts(type, fired_at DESC);
"""

_LIST_COLUMNS = ("id", "fired_at", "type", "rule_id", "rule_name", "severity", "summary",
                 "criteria", "status", "status_by", "status_at")


def default_alerts_db_path() -> str:
    return os.path.join(ROOT_DIR, "logs", "alerts.sqlite")


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class AlertStore:
    """Thin sqlite3 wrapper. One connection per instance; instances are cheap
    and short-lived (a dispatch, a request). WAL + a bounded lock wait so the
    CLI (a separate process) and monitor+GUI never deadlock on each other."""

    def __init__(self, path: Optional[str] = None):
        self.path = path or default_alerts_db_path()
        existed = os.path.exists(self.path)
        self._conn = sqlite3.connect(self.path, timeout=5.0)
        self._conn.row_factory = sqlite3.Row
        if not existed:
            # Owner-only before any row lands: the file carries alert payloads
            # (flow tuples, event actors) that must not be world-readable.
            os.chmod(self.path, 0o600)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        if self._conn.execute("PRAGMA user_version").fetchone()[0] < _SCHEMA_VERSION:
            self._conn.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ── writes ──────────────────────────────────────────────────────────

    def insert(self, *, fired_at: str, type: str, rule_id: Optional[str], rule_name: str,
               severity: str, summary: str, criteria: str, payload: dict,
               dispatch: list[dict]) -> int:
        if type not in ALERT_TYPES:
            raise ValueError(f"unknown alert type {type!r}")
        cur = self._conn.execute(
            "INSERT INTO alerts (fired_at, type, rule_id, rule_name, severity, summary, criteria,"
            " payload_json, dispatch_json) VALUES (?,?,?,?,?,?,?,?,?)",
            (fired_at, type, None if rule_id is None else str(rule_id), rule_name, severity,
             summary, criteria or "", json.dumps(payload, ensure_ascii=False, default=str),
             json.dumps(dispatch, ensure_ascii=False, default=str)),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def update_dispatch(self, alert_id: int, dispatch: list[dict]) -> None:
        self._conn.execute("UPDATE alerts SET dispatch_json=? WHERE id=?",
                           (json.dumps(dispatch, ensure_ascii=False, default=str), alert_id))
        self._conn.commit()

    def set_status(self, alert_id: int, status: str, by: str) -> bool:
        if status not in ALERT_STATUSES:
            raise ValueError(f"unknown alert status {status!r}")
        cur = self._conn.execute(
            "UPDATE alerts SET status=?, status_by=?, status_at=? WHERE id=?",
            (status, by, _utc_now(), alert_id))
        self._conn.commit()
        return cur.rowcount == 1

    def prune(self, *, days: int) -> int:
        cutoff = (datetime.datetime.now(datetime.timezone.utc)
                  - datetime.timedelta(days=int(days))).strftime("%Y-%m-%dT%H:%M:%SZ")
        cur = self._conn.execute("DELETE FROM alerts WHERE fired_at < ?", (cutoff,))
        self._conn.commit()
        return cur.rowcount

    # ── reads ───────────────────────────────────────────────────────────

    def get(self, alert_id: int) -> Optional[dict]:
        row = self._conn.execute("SELECT * FROM alerts WHERE id=?", (alert_id,)).fetchone()
        if row is None:
            return None
        out = {k: row[k] for k in _LIST_COLUMNS}
        out["payload"] = json.loads(row["payload_json"])
        out["dispatch"] = json.loads(row["dispatch_json"])
        return out

    def list(self, *, status: Optional[str] = None, type: Optional[str] = None,
             since: Optional[str] = None, page: int = 1, page_size: int = 50) -> dict:
        where, args = [], []
        if status:
            where.append("status=?"); args.append(status)
        if type:
            where.append("type=?"); args.append(type)
        if since:
            where.append("fired_at>=?"); args.append(since)
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        page = max(1, int(page)); page_size = max(1, int(page_size))
        total = self._conn.execute(f"SELECT COUNT(*) FROM alerts{clause}", args).fetchone()[0]
        rows = self._conn.execute(
            f"SELECT {', '.join(_LIST_COLUMNS)} FROM alerts{clause}"
            " ORDER BY fired_at DESC, id DESC LIMIT ? OFFSET ?",
            [*args, page_size, (page - 1) * page_size]).fetchall()
        return {"items": [dict(r) for r in rows], "total": int(total),
                "page": page, "page_size": page_size}

    def count(self, *, status: str = "new") -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM alerts WHERE status=?",
                                      (status,)).fetchone()[0])

    def counts(self) -> dict[str, int]:
        out = {s: 0 for s in ALERT_STATUSES}
        for status, n in self._conn.execute("SELECT status, COUNT(*) FROM alerts GROUP BY status"):
            out[status] = int(n)
        return out
