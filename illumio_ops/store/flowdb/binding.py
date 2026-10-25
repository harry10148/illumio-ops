"""Which PCE the flow database belongs to (one row)."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from illumio_ops.store.flowdb.db import db_time, transaction


@dataclass(frozen=True)
class Binding:
    pce_url: str
    org_id: str
    bound_at: datetime


def current(conn: sqlite3.Connection) -> Binding | None:
    row = conn.execute("SELECT pce_url, org_id, bound_at FROM pce_binding WHERE id = 1").fetchone()
    if row is None:
        return None
    return Binding(row["pce_url"], row["org_id"], datetime.fromisoformat(row["bound_at"]))


def bind(conn: sqlite3.Connection, pce_url: str, org_id: str, at: datetime) -> bool:
    """Bind an unbound database; returns False (and changes nothing) if already bound."""
    with transaction(conn):
        cur = conn.execute("INSERT OR IGNORE INTO pce_binding (id, pce_url, org_id, bound_at) VALUES (1, ?, ?, ?)",
                           (pce_url, org_id, db_time(at)))
        return cur.rowcount == 1
