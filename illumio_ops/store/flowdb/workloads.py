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
    addresses_json: str | None = None     # the interfaces' addresses, a JSON list (0017); None: not read yet


_COLUMNS = ", ".join(f.name for f in fields(WorkloadRow))
_MARKS = ", ".join("?" for _ in fields(WorkloadRow))


def replace_inventory(conn: sqlite3.Connection, rows: Sequence[WorkloadRow]) -> None:
    """The PCE's current list replaces the stored one (callers pass only complete lists)."""
    with transaction(conn):
        conn.execute("DELETE FROM workloads")
        conn.executemany(f"INSERT INTO workloads ({_COLUMNS}) VALUES ({_MARKS})", [astuple(r) for r in rows])


def set_enforcement_mode(conn: sqlite3.Connection, href: str, mode: str) -> None:
    """One workload's mode after the PCE accepted a change to it (services.fleet_write), until the next inventory read
    replaces the whole list."""
    with transaction(conn):
        conn.execute("UPDATE workloads SET enforcement_mode = ? WHERE href = ?", (mode, href))


def all_workloads(conn: sqlite3.Connection) -> list[WorkloadRow]:
    return [WorkloadRow(*r) for r in conn.execute(f"SELECT {_COLUMNS} FROM workloads ORDER BY href")]


def snapshot_day(conn: sqlite3.Connection, day: str) -> int:
    """The day's snapshot is the inventory at its latest run: replaced whole, never merged. `day` is the
    collector's: a UTC day (db_day)."""
    with transaction(conn):
        conn.execute("DELETE FROM workload_snapshot_daily WHERE day = ?", (day,))
        return conn.execute(
            "INSERT INTO workload_snapshot_daily (day, href, enforcement_mode, visibility_level, "
            "risk_exposure, risk_percent, managed) SELECT ?, href, enforcement_mode, visibility_level, "
            "risk_exposure, risk_percent, managed FROM workloads", (day,)).rowcount


@dataclass(frozen=True)
class ModeCounts:
    """The managed hosts of one day's snapshot."""
    hosts: int             # every managed host, the ones the PCE gave no mode for among them
    modes: dict[str, int]  # enforcement mode -> hosts in it


def mode_counts_on(conn: sqlite3.Connection, day: str) -> ModeCounts | None:
    """The managed hosts of `day`'s snapshot (a UTC day), by enforcement mode. None when the day cannot be compared
    with: it has no snapshot, or a row of it was written before the snapshot said which hosts were managed
    (migration 0018) — counting the rest would count another set of hosts than the day's."""
    total, unknown = conn.execute("SELECT COUNT(*), COALESCE(SUM(managed IS NULL), 0) FROM workload_snapshot_daily "
                                  "WHERE day = ?", (day,)).fetchone()
    if not total or unknown:
        return None
    rows = conn.execute("SELECT enforcement_mode, COUNT(*) FROM workload_snapshot_daily "
                        "WHERE day = ? AND managed = 1 GROUP BY enforcement_mode", (day,)).fetchall()
    return ModeCounts(hosts=sum(n for _, n in rows), modes={mode: n for mode, n in rows if mode is not None})



def delete_snapshots_before(conn: sqlite3.Connection, day: str) -> int:
    with transaction(conn):
        return conn.execute("DELETE FROM workload_snapshot_daily WHERE day < ?", (day,)).rowcount


def copy_from(conn: sqlite3.Connection, schema: str) -> None:
    """Copy the inventory and its snapshots from an attached store (an on-demand store starts from the install's,
    ondemand.py). Every column goes along, the snapshot's `managed` among them: both stores are made by the same
    migrations."""
    conn.execute(f"INSERT INTO workloads SELECT * FROM {schema}.workloads")
    conn.execute(f"INSERT INTO workload_snapshot_daily SELECT * FROM {schema}.workload_snapshot_daily")
