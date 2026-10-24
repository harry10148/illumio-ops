"""FlowDb: connections to data/flows.sqlite, its migrations, and the one write lock.

Collectors run on separate scheduler threads; every module that writes this database
holds write_lock for the whole transaction, so a long rollup rebuild never meets
SQLite's busy timeout and a PCE switch never deletes the file mid-write.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

from illumio_ops.domain.timefmt import store_time
from illumio_ops.store.db import connect, migrate

MIGRATIONS_PACKAGE = "illumio_ops.store.flowdb.migrations"


def db_time(value: datetime) -> str:
    """The one stored timestamp format: fixed-width UTC, so text order is time order."""
    return store_time(value)


def db_day(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%d")


class FlowDb:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.write_lock = threading.Lock()

    def connect(self) -> sqlite3.Connection:
        conn = connect(self.path)
        try:
            migrate(conn, MIGRATIONS_PACKAGE)
        except BaseException:
            conn.close()
            raise
        return conn

    def reset(self) -> None:
        """Drop every row by recreating the file (used when the PCE changes)."""
        with self.write_lock:
            for suffix in ("", "-wal", "-shm"):
                Path(f"{self.path}{suffix}").unlink(missing_ok=True)
            self.connect().close()
