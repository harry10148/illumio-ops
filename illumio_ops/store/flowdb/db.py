"""FlowDb: connections to data/flows.sqlite, its migrations, and the one write lock.

Collectors run on separate scheduler threads; every module that writes this database
holds write_lock for the whole transaction, so a long rollup rebuild never meets
SQLite's busy timeout and a PCE switch never deletes the file mid-write.
"""
from __future__ import annotations

import itertools
import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from illumio_ops.domain.timefmt import store_time
from illumio_ops.store.db import connect, migrate

MIGRATIONS_PACKAGE = "illumio_ops.store.flowdb.migrations"


def db_time(value: datetime) -> str:
    """The one stored timestamp format: fixed-width UTC, so text order is time order."""
    return store_time(value)


_savepoints = itertools.count()


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """A unit of work that nests: the outermost one commits, an inner one is a savepoint.
    Store functions use it so that a collector can wrap a whole cycle's writes in one."""
    name = f"sp{next(_savepoints)}"
    conn.execute(f"SAVEPOINT {name}")
    try:
        yield conn
    except BaseException:
        conn.execute(f"ROLLBACK TO {name}")
        conn.execute(f"RELEASE {name}")
        raise
    conn.execute(f"RELEASE {name}")


def db_day(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%d")


class StaleGeneration(Exception):
    """The flow database was reset for another PCE after this work began: what it read belongs
    to the previous PCE and must not be written."""


class FlowDb:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.write_lock = threading.Lock()
        # Bumped by reset(). Work that reads the PCE notes it first (before the settings it uses)
        # and writes through writing(), so a switch landing mid-cycle drops the old PCE's results.
        self.generation = 0

    @contextmanager
    def writing(self, generation: int) -> Iterator[sqlite3.Connection]:
        """The write lock and a connection for work that began at `generation`."""
        with self.write_lock:
            if self.generation != generation:
                raise StaleGeneration
            with self.connect() as conn:
                yield conn

    def connect(self) -> sqlite3.Connection:
        conn = connect(self.path)
        try:
            migrate(conn, MIGRATIONS_PACKAGE)
        except BaseException:
            conn.close()
            raise
        return conn

    def reset(self, *, also: Callable[[], None] | None = None) -> None:
        """Drop every row by recreating the file (used when the PCE changes). `also` runs in the
        same hold of the write lock, so no writer of the old generation slips in between."""
        with self.write_lock:
            self.generation += 1
            if also is not None:
                also()
            for suffix in ("", "-wal", "-shm"):
                Path(f"{self.path}{suffix}").unlink(missing_ok=True)
            self.connect().close()
