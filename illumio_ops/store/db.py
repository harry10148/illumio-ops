"""SQLite connection setup and schema migrations for the application state database
(data/app.sqlite) and, with another migrations package, the flow database."""
from __future__ import annotations

import re
import sqlite3
from importlib import resources
from pathlib import Path

_MIGRATION_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


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


def _user_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])
