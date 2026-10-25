import sqlite3

import pytest

from illumio_ops.store import db
from illumio_ops.store.db import connect, migrate


def test_connect_creates_parent_and_sets_pragmas(tmp_path):
    conn = connect(tmp_path / "sub" / "app.sqlite")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    assert conn.row_factory is sqlite3.Row


def test_migrate_sets_user_version(tmp_path):
    conn = connect(tmp_path / "app.sqlite")
    v = migrate(conn)
    assert v == conn.execute("PRAGMA user_version").fetchone()[0] >= 1
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"job_health", "pce_probe"} <= tables


def test_migrate_is_idempotent(tmp_path):
    conn = connect(tmp_path / "app.sqlite")
    v1 = migrate(conn)
    assert migrate(conn) == v1


def test_newer_db_version_is_refused(tmp_path):
    conn = connect(tmp_path / "app.sqlite")
    migrate(conn)
    conn.execute("PRAGMA user_version = 999")
    with pytest.raises(RuntimeError, match="999"):
        migrate(conn)


def test_failed_migration_rolls_back_whole_file(tmp_path, monkeypatch):
    conn = connect(tmp_path / "app.sqlite")
    good = db._migrations()
    bad = (len(good) + 1, "CREATE TABLE half_done(x INTEGER);\nTHIS IS NOT SQL;")
    monkeypatch.setattr(db, "_migrations", lambda: [*good, bad])
    with pytest.raises(sqlite3.Error):
        migrate(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == len(good)
    assert conn.execute("SELECT count(*) FROM sqlite_master WHERE name='half_done'").fetchone()[0] == 0


def test_pce_probe_is_single_row(tmp_path):
    conn = connect(tmp_path / "app.sqlite")
    migrate(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO pce_probe(id, checked_at, results_json) VALUES (2, 'x', '[]')")
