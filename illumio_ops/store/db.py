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
    current = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if current > latest:
        raise RuntimeError(f"database schema version {current} is newer than this program ({latest})")
    for version, sql in migrations:
        if version <= current:
            continue
        try:
            conn.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {version};\nCOMMIT;")
        except sqlite3.Error:
            if conn.in_transaction:
                conn.rollback()
            raise
        current = version
    return current
