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
