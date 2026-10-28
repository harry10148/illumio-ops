"""What the connected PCE / VEN version offers, as last detected by the collectors."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from illumio_ops.domain.values import CapabilityState
from illumio_ops.store.flowdb.db import db_time, transaction


@dataclass(frozen=True)
class CapabilityRow:
    name: str
    state: str
    detail: str | None
    checked_at: datetime


def record(conn: sqlite3.Connection, name: str, state: CapabilityState, detail: str | None, at: datetime) -> None:
    with transaction(conn):
        conn.execute("INSERT INTO pce_capabilities (name, state, detail, checked_at) VALUES (?, ?, ?, ?) "
                     "ON CONFLICT(name) DO UPDATE SET state = excluded.state, detail = excluded.detail, "
                     "checked_at = excluded.checked_at", (name, state.value, detail, db_time(at)))


def all(conn: sqlite3.Connection) -> dict[str, CapabilityRow]:
    return {r["name"]: CapabilityRow(r["name"], r["state"], r["detail"], datetime.fromisoformat(r["checked_at"]))
            for r in conn.execute("SELECT * FROM pce_capabilities").fetchall()}


def copy_from(conn: sqlite3.Connection, schema: str) -> None:
    """Copy what the PCE was found to support from an attached store (an on-demand store starts from the install's)."""
    conn.execute(f"INSERT INTO pce_capabilities SELECT * FROM {schema}.pce_capabilities")
