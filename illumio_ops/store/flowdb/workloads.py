"""The managed-workload inventory and its daily snapshot."""
from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import astuple, dataclass, fields


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
    with conn:
        conn.execute("DELETE FROM workloads")
        conn.executemany(f"INSERT INTO workloads ({_COLUMNS}) VALUES ({_MARKS})", [astuple(r) for r in rows])


def snapshot_day(conn: sqlite3.Connection, day: str) -> int:
    """First snapshot of the day wins; later runs that day change nothing."""
    with conn:
        return conn.execute(
            "INSERT OR IGNORE INTO workload_snapshot_daily (day, href, enforcement_mode, visibility_level, "
            "risk_exposure, risk_percent) SELECT ?, href, enforcement_mode, visibility_level, risk_exposure, "
            "risk_percent FROM workloads", (day,)).rowcount

