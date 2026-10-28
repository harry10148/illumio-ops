"""The managed-workload inventory and its daily snapshot."""
from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import astuple, dataclass, fields

from illumio_ops.store.flowdb.db import transaction


@dataclass(frozen=True)
class WorkloadRow:
    href: str
    hostname: str | None
    name: str | None
    managed: int
    enforcement_mode: str | None
    visibility_level: str | None
    os_id: str | None
    ven_version: str | None
    ven_href: str | None
    label_set: int | None
    online: int | None
    risk_exposure: str | None
    risk_percent: float | None
    risk_updated_at: str | None
    fetched_at: str
    # agent.status (0008); None: not reported, or the row predates the columns
    agent_status: str | None = None
    last_heartbeat_at: str | None = None
    policy_sync_state: str | None = None
    policy_received_at: str | None = None
    policy_applied_at: str | None = None
    managed_since: str | None = None
    fw_config_current: int | None = None
    agent_health_json: str | None = None  # agent.status.agent_health as the PCE sent it


_COLUMNS = ", ".join(f.name for f in fields(WorkloadRow))
_MARKS = ", ".join("?" for _ in fields(WorkloadRow))


def replace_inventory(conn: sqlite3.Connection, rows: Sequence[WorkloadRow]) -> None:
    """The PCE's current list replaces the stored one (callers pass only complete lists)."""
    with transaction(conn):
        conn.execute("DELETE FROM workloads")
        conn.executemany(f"INSERT INTO workloads ({_COLUMNS}) VALUES ({_MARKS})", [astuple(r) for r in rows])


def all_workloads(conn: sqlite3.Connection) -> list[WorkloadRow]:
    return [WorkloadRow(*r) for r in conn.execute(f"SELECT {_COLUMNS} FROM workloads ORDER BY href")]


def snapshot_day(conn: sqlite3.Connection, day: str) -> int:
    """The day's snapshot is the inventory at its latest run: replaced whole, never merged."""
    with transaction(conn):
        conn.execute("DELETE FROM workload_snapshot_daily WHERE day = ?", (day,))
        return conn.execute(
            "INSERT INTO workload_snapshot_daily (day, href, enforcement_mode, visibility_level, "
            "risk_exposure, risk_percent) SELECT ?, href, enforcement_mode, visibility_level, risk_exposure, "
            "risk_percent FROM workloads", (day,)).rowcount



def delete_snapshots_before(conn: sqlite3.Connection, day: str) -> int:
    with transaction(conn):
        return conn.execute("DELETE FROM workload_snapshot_daily WHERE day < ?", (day,)).rowcount


def copy_from(conn: sqlite3.Connection, schema: str) -> None:
    """Copy the inventory from an attached store (an on-demand store starts from the install's, ondemand.py)."""
    conn.execute(f"INSERT INTO workloads SELECT * FROM {schema}.workloads")
    conn.execute(f"INSERT INTO workload_snapshot_daily SELECT * FROM {schema}.workload_snapshot_daily")
