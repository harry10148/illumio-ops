"""SQLite connection setup and schema migrations for the application state database
(data/app.sqlite) and, with another migrations package, the flow database."""
from __future__ import annotations

import re
import sqlite3
import time
from importlib import resources
from pathlib import Path

_MIGRATION_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


BUSY_TIMEOUT_SECONDS = 5.0


def connect(path: Path, *, factory: type[sqlite3.Connection] = sqlite3.Connection) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=BUSY_TIMEOUT_SECONDS, factory=factory)
    conn.row_factory = sqlite3.Row
    try:
        _use_wal(conn)
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(f"PRAGMA busy_timeout={int(BUSY_TIMEOUT_SECONDS * 1000)}")
    except BaseException:
        conn.close()
        raise
    return conn


def _use_wal(conn: sqlite3.Connection) -> None:
    """Switch a new database to WAL (a database switched once stays switched). SQLite refuses the
    switch at once, without the busy timeout, while another connection holds a write lock — job
    threads opening a brand-new store at the same moment — so this waits for it like a busy lock."""
    deadline = time.monotonic() + BUSY_TIMEOUT_SECONDS
    while True:
        try:
            if conn.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal":
                return
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc) or time.monotonic() >= deadline:
                raise
        else:
            raise sqlite3.OperationalError("the database could not be switched to WAL")
        time.sleep(0.05)


APP_MIGRATIONS = "illumio_ops.store.migrations"


def _migrations(package: str = APP_MIGRATIONS) -> list[tuple[int, str]]:
    out = []
    for entry in resources.files(package).iterdir():
        m = _MIGRATION_NAME.match(entry.name)
        if m:
            out.append((int(m.group(1)), entry.read_text(encoding="utf-8")))
    out.sort()
    versions = [v for v, _ in out]
    if versions != list(range(1, len(versions) + 1)):
        raise RuntimeError(f"migration files are not numbered 1..N without gaps: {versions}")
    return out


def migrate(conn: sqlite3.Connection, package: str = APP_MIGRATIONS) -> int:
    """Apply pending migrations, one transaction per file; return the resulting version.

    A database newer than this program is refused rather than used: running an
    older build against a newer schema is how data gets silently mangled.
    """
    migrations = _migrations(package)
    latest = migrations[-1][0] if migrations else 0
    current = _user_version(conn)
    if current > latest:
        raise RuntimeError(f"database schema version {current} is newer than this program ({latest})")
    pending = [(v, sql) for v, sql in migrations if v > current]
    if not pending:
        return current
    # Job threads (and the rescue command) open a new database at the same moment: each step
    # takes the write lock first and re-reads the version under it, so it is applied once.
    legacy = conn.autocommit
    conn.autocommit = True  # executescript must not commit the BEGIN IMMEDIATE below
    try:
        for version, sql in pending:
            conn.execute("BEGIN IMMEDIATE")
            try:
                if _user_version(conn) < version:
                    conn.executescript(f"{sql}\nPRAGMA user_version = {version};")
                conn.execute("COMMIT")
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
    finally:
        conn.autocommit = legacy
    return _user_version(conn)


def pending_migrations(conn: sqlite3.Connection, package: str = APP_MIGRATIONS) -> int:
    """How many migrations migrate() would apply (0 for a database newer than this program)."""
    return max(0, len(_migrations(package)) - _user_version(conn))


def _user_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])
