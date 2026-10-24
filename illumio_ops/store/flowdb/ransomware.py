"""Ransomware protection as the PCE judges it: per-workload risky services, daily snapshots,
and the organisation summary."""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any

from illumio_ops.store.flowdb.db import db_time


def _int(value: Any, default: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def upsert_services(conn: sqlite3.Connection, workload_href: str, services: Sequence[Mapping[str, Any]], *,
                    source_updated_at: str | None, at: datetime) -> int:
    """Replace one workload's risky-service list with what the PCE reported."""
    rows = [(workload_href, str(s.get("name") or ""), _int(s.get("port"), -1), _int(s.get("proto"), 0),
             s.get("severity"), s.get("category"), s.get("protection_state"), s.get("port_status"),
             s.get("active_policy"), s.get("draft_policy"), s.get("recommendation") or None,
             source_updated_at, db_time(at)) for s in services if isinstance(s, Mapping)]
    with conn:
        conn.execute("DELETE FROM ransomware_services WHERE workload_href = ?", (workload_href,))
        conn.executemany(
            "INSERT OR REPLACE INTO ransomware_services (workload_href, name, port, proto, severity, category, "
            "protection_state, port_status, active_policy, draft_policy, recommendation, source_updated_at, "
            "fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    return len(rows)


def source_updated(conn: sqlite3.Connection) -> dict[str, str | None]:
    """workload href -> the PCE's last_updated_at of the details we hold."""
    return {r[0]: r[1] for r in conn.execute(
        "SELECT workload_href, MAX(source_updated_at) FROM ransomware_services GROUP BY workload_href")}


def prune_missing(conn: sqlite3.Connection, keep: Iterable[str]) -> int:
    keep_set = set(keep)
    gone = [h for h in source_updated(conn) if h not in keep_set]
    with conn:
        conn.executemany("DELETE FROM ransomware_services WHERE workload_href = ?", [(h,) for h in gone])
    return len(gone)


def snapshot_day(conn: sqlite3.Connection, day: str) -> int:
    with conn:
        return conn.execute(
            "INSERT OR IGNORE INTO ransomware_snapshot_daily (day, workload_href, name, port, proto, severity, "
            "protection_state, port_status) SELECT ?, workload_href, name, port, proto, severity, "
            "protection_state, port_status FROM ransomware_services", (day,)).rowcount


def write_org_summary(conn: sqlite3.Connection, day: str, summary: Mapping[str, Any]) -> None:
    with conn:
        conn.execute("INSERT OR REPLACE INTO org_risk_snapshot_daily (day, summary_json) VALUES (?, ?)",
                     (day, json.dumps(summary, separators=(",", ":"))))


def delete_snapshots_before(conn: sqlite3.Connection, day: str) -> int:
    with conn:
        n = conn.execute("DELETE FROM ransomware_snapshot_daily WHERE day < ?", (day,)).rowcount
        return n + conn.execute("DELETE FROM org_risk_snapshot_daily WHERE day < ?", (day,)).rowcount
