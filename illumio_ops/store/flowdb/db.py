"""FlowDb: connections to data/flows.sqlite, its migrations, and the one write lock.

Collectors run on separate scheduler threads; every module that writes this database
holds write_lock for the whole transaction, so a long rollup rebuild never meets
SQLite's busy timeout and a PCE switch never deletes the file mid-write.

A connection is closed when its `with` block ends, and a PCE switch (reset) deletes the file only
once no connection to it is open. So never hold a FlowDb connection while waiting for write_lock,
and let long lock-free reads stop when `generation` moves (StaleGeneration).
"""
from __future__ import annotations

import gc
import itertools
import sqlite3
import threading
import time
import weakref
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Literal

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


# How long a PCE switch waits for open connections (lock-free reads: a checkpoint took 26 s and a
# one-day facet scan 20-28 s at 1,000 workloads, P2 re-measure) before it gives up for this time.
RESET_WAIT_SECONDS = 120.0


class FlowDbBusy(Exception):
    """A reset gave up: connections to the flow database stayed open; nothing was deleted."""


class FlowConnection(sqlite3.Connection):
    """A flow-store connection that is closed when its `with` block ends (sqlite3's own only commits)."""

    closed = False

    def close(self) -> None:
        self.closed = True
        super().close()

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None,
                 tb: TracebackType | None) -> Literal[False]:
        try:
            super().__exit__(exc_type, exc, tb)
        finally:
            self.close()
        return False


class StaleGeneration(Exception):
    """The flow database was reset for another PCE after this work began: what it read belongs
    to the previous PCE and must not be written."""


class FlowDb:
    # Checkpointing is the flows_checkpoint job's, outside the write lock: inside a collection commit
    # it wrote ~43k pages back at random positions, 7 of 17 s at 1M rows/day (P2 re-measure). The
    # automatic checkpoint stays as a safety net far above one cycle's pages, so a stalled job cannot
    # let the WAL grow without bound; a checkpointed WAL file is cut back to WAL_KEEP_BYTES.
    WAL_SAFETY_NET_PAGES = 250_000  # about 1 GB of WAL
    WAL_KEEP_BYTES = 64 * 1024 * 1024

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.write_lock = threading.Lock()
        # Bumped by reset(). Work that reads the PCE notes it first (before the settings it uses)
        # and writes through writing(), so a switch landing mid-cycle drops the old PCE's results.
        self.generation = 0
        self._open: weakref.WeakSet[FlowConnection] = weakref.WeakSet()
        self._open_lock = threading.Lock()
        # While a reset runs, connect() waits: a connection opened then would sit on the file it deletes.
        self._gate = threading.Condition(self._open_lock)
        self._resetting = False
        self._opening = 0
        # One idle connection kept open, so the connection a writer closes is never the file's last:
        # SQLite checkpoints the whole WAL when the last connection closes, which inside a write would
        # bring back the checkpoint under the lock (see WAL_SAFETY_NET_PAGES). Not counted by reset.
        self._anchor: sqlite3.Connection | None = None

    @contextmanager
    def writing(self, generation: int) -> Iterator[sqlite3.Connection]:
        """The write lock and a connection for work that began at `generation`."""
        with self.write_lock:
            if self.generation != generation:
                raise StaleGeneration
            with self.connect() as conn:
                yield conn

    def connect(self) -> sqlite3.Connection:
        with self._gate:
            while self._resetting:
                self._gate.wait()
            self._opening += 1
        try:
            conn = connect(self.path, factory=FlowConnection)
        except BaseException:
            self._opened(None)
            raise
        try:
            conn.execute(f"PRAGMA wal_autocheckpoint={self.WAL_SAFETY_NET_PAGES}")
            conn.execute(f"PRAGMA journal_size_limit={self.WAL_KEEP_BYTES}")
            # A commit does not fsync (it queued behind the checkpoint's writes: 20.9 s holds of the
            # lock, P2 re-measure). With WAL the file cannot be corrupted; a power cut can lose the last
            # commits, and the collection watermarks in this same file roll back with them, so that
            # range is pulled again.
            conn.execute("PRAGMA synchronous=NORMAL")
            migrate(conn, MIGRATIONS_PACKAGE)
        except BaseException:
            conn.close()
            self._opened(None)
            raise
        self._opened(conn)
        return conn

    def _opened(self, conn: sqlite3.Connection | None) -> None:
        with self._gate:
            self._opening -= 1
            if conn is not None:
                self._open.add(conn)  # type: ignore[arg-type]
                if self._anchor is None:
                    self._anchor = sqlite3.connect(self.path, check_same_thread=False)
                    # A read attaches it to the WAL (it holds the shared lock that marks it open from then
                    # on); autocommit, so it keeps no snapshot and never holds a checkpoint back.
                    self._anchor.execute("SELECT count(*) FROM sqlite_master").fetchone()
            self._gate.notify_all()

    def _drop_anchor(self) -> None:
        with self._open_lock:
            anchor, self._anchor = self._anchor, None
        if anchor is not None:
            anchor.setconfig(sqlite3.SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE, True)  # the file is about to go
            anchor.close()

    def _wait_for_connections(self, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        collected = False
        while True:
            with self._gate:
                still = self._opening + sum(1 for c in self._open if not c.closed)
                if still and collected and time.monotonic() < deadline:
                    self._gate.wait(0.05)
                    continue
            if not still:
                return
            if not collected:  # one held only by a reference cycle (a traceback) goes with a collection
                gc.collect()
                collected = True
                continue
            raise FlowDbBusy(f"{still} connection(s) to the flow database stayed open")

    def checkpoint(self) -> int:
        """Copy committed WAL pages into the database file without waiting for readers or writers
        (no write lock); returns the pages checkpointed."""
        conn = self.connect()
        try:
            _busy, _log, done = conn.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
        finally:
            conn.close()
        return int(done)

    def reset(self, *, also: Callable[[], None] | None = None) -> None:
        """Drop every row by recreating the file (used when the PCE changes). `also` runs in the
        same hold of the write lock, so no writer of the old generation slips in between. The file is
        deleted only once no connection to it is open: a connection still open on the deleted file
        would, closing last on it, delete the new file's WAL and shared memory by name. Raises
        FlowDbBusy, deleting nothing, if connections stay open for RESET_WAIT_SECONDS."""
        with self.write_lock:
            # First, so long lock-free reads notice it and stop. It stays moved if the reset gives up:
            # work begun for the old PCE is dropped either way, and the settings already name the new one,
            # so collectors refuse to write until the next run finishes the switch (finish_pending_switch).
            self.generation += 1
            with self._gate:
                self._resetting = True
            try:
                self._wait_for_connections(RESET_WAIT_SECONDS)
                self._drop_anchor()
                if also is not None:
                    also()
                for suffix in ("", "-wal", "-shm"):
                    Path(f"{self.path}{suffix}").unlink(missing_ok=True)
            finally:
                with self._gate:
                    self._resetting = False
                    self._gate.notify_all()
            self.connect().close()
