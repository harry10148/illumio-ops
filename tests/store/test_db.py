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
    monkeypatch.setattr(db, "_migrations", lambda package=None: [*good, bad])
    with pytest.raises(sqlite3.Error):
        migrate(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == len(good)
    assert conn.execute("SELECT count(*) FROM sqlite_master WHERE name='half_done'").fetchone()[0] == 0


def test_pce_probe_is_single_row(tmp_path):
    conn = connect(tmp_path / "app.sqlite")
    migrate(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO pce_probe(id, checked_at, results_json) VALUES (2, 'x', '[]')")


class _MigratedByAnotherAfterRead(sqlite3.Connection):
    """Another connection migrates the file right after this one first reads the version: the
    window two job threads opening a new database at once fall into."""
    other_path = None

    def execute(self, sql, *args):
        cur = super().execute(sql, *args)
        if sql == "PRAGMA user_version" and type(self).other_path is not None:
            path, type(self).other_path = type(self).other_path, None
            other = connect(path)
            migrate(other)
            other.close()
        return cur


def test_migration_applied_by_another_connection_meanwhile_is_not_reapplied(tmp_path):
    path = tmp_path / "app.sqlite"
    connect(path).close()
    _MigratedByAnotherAfterRead.other_path = path
    conn = sqlite3.connect(path, factory=_MigratedByAnotherAfterRead)
    latest = db._migrations()[-1][0]
    assert migrate(conn) == latest
    assert conn.execute("PRAGMA user_version").fetchone()[0] == latest


def test_threads_opening_a_new_flow_store_at_once_all_succeed(tmp_path):
    import threading

    from illumio_ops.store.flowdb.db import FlowDb

    fdb = FlowDb(tmp_path / "flows.sqlite")
    start, errors = threading.Barrier(8), []

    def open_it():
        start.wait()
        try:
            fdb.connect().close()
        except Exception as e:  # noqa: BLE001 - the test collects every failure
            errors.append(e)

    threads = [threading.Thread(target=open_it) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []


def test_switching_a_new_database_to_wal_waits_for_a_writer(tmp_path):
    # SQLite answers "database is locked" at once, without the busy timeout, when another connection
    # holds a write lock while this one changes the journal mode — what job threads opening a brand-new
    # store at the same moment run into (1 in ~25 rounds of the threads test above).
    import threading
    path = tmp_path / "app.sqlite"
    holder = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    holder.execute("CREATE TABLE t (x)")
    holder.execute("BEGIN IMMEDIATE")
    threading.Timer(0.3, lambda: holder.execute("COMMIT")).start()
    conn = connect(path)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
