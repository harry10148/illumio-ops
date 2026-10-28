import sqlite3
import threading

import pytest

from illumio_ops.store.flowdb import db as flowdb
from illumio_ops.store.flowdb.db import FlowDb
from illumio_ops.store.ownership import TABLE_OWNERS

FLOWDB_TABLES = {
    "pce_binding", "ingest_state", "ingest_gaps", "label_sets", "label_set_members", "flows",
    "flow_rollup_daily", "rollup_state", "connection_baseline", "user_baseline", "events", "workloads",
    "workload_snapshot_daily", "ransomware_services", "ransomware_snapshot_daily",
    "org_risk_snapshot_daily", "pce_capabilities", "archive_log",
}


def _tables(conn):
    # sqlite_sequence is SQLite's own (AUTOINCREMENT), not a table of ours
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")} - {"sqlite_sequence"}


def test_flowdb_migrates_on_first_connect(tmp_path):
    fdb = FlowDb(tmp_path / "data" / "flows.sqlite")
    with fdb.connect() as conn:
        assert FLOWDB_TABLES <= _tables(conn)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 8
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_every_flowdb_table_has_a_registered_owner(tmp_path):
    with FlowDb(tmp_path / "flows.sqlite").connect() as conn:
        assert _tables(conn) <= set(TABLE_OWNERS)


def test_flowdb_reset_drops_all_rows_and_keeps_schema(tmp_path):
    fdb = FlowDb(tmp_path / "flows.sqlite")
    with fdb.connect() as conn:
        conn.execute("INSERT INTO pce_binding(id, pce_url, org_id, bound_at) VALUES (1, 'https://a', '1', 'x')")
        conn.commit()
    fdb.reset()
    with fdb.connect() as conn:
        assert conn.execute("SELECT count(*) FROM pce_binding").fetchone()[0] == 0
        assert FLOWDB_TABLES <= _tables(conn)


def test_flowdb_reset_waits_for_write_lock(tmp_path):
    fdb = FlowDb(tmp_path / "flows.sqlite")
    fdb.connect().close()
    order = []
    fdb.write_lock.acquire()
    t = threading.Thread(target=lambda: (fdb.reset(), order.append("reset")))
    t.start()
    t.join(0.2)
    order.append("writer done")
    fdb.write_lock.release()
    t.join(5)
    assert order == ["writer done", "reset"]


def test_flowdb_newer_version_is_refused(tmp_path):
    fdb = FlowDb(tmp_path / "flows.sqlite")
    with fdb.connect() as conn:
        conn.execute("PRAGMA user_version = 999")
    with pytest.raises(RuntimeError, match="999"):
        fdb.connect()


def test_rollup_pk_rejects_null_keys(tmp_path):
    with FlowDb(tmp_path / "flows.sqlite").connect() as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute(
                "INSERT INTO flow_rollup_daily(day, src_key, dst_key, port, proto, policy_decision, "
                "initiator_user, initiator_process, connections, flow_records, bytes_in, bytes_out, "
                "bytes_known_records) VALUES ('2026-10-24', 'a', 'b', 22, 6, 'allowed', NULL, '', 1, 1, 0, 0, 0)")


def test_flow_origin_is_constrained(tmp_path):
    with FlowDb(tmp_path / "flows.sqlite").connect() as conn:
        cols = {r[1]: r for r in conn.execute("PRAGMA table_info(flows)")}
        assert {"initiator_process", "initiator_user", "service_process", "service_user",
                "conn_key", "is_primary", "origin"} <= set(cols)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO flows(record_key, conn_key, is_primary, direction, src_ip, dst_ip, src_key, "
                "dst_key, src_managed, dst_managed, proto, policy_decision, first_detected, last_detected, "
                "num_connections, origin, ingested_at) VALUES ('k','k',1,'outbound','1.1.1.1','2.2.2.2',"
                "'ip:1.1.1.1','ip:2.2.2.2',0,0,6,'allowed','t','t',1,'live','t')")


def _write_pages(fdb, pages):
    with fdb.write_lock, fdb.connect() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS scratch (b BLOB)")
        conn.executemany("INSERT INTO scratch VALUES (randomblob(4000))", [()] * pages)


def test_a_commit_leaves_checkpointing_to_the_background(tmp_path):
    # Measured at 1M rows/day: the automatic checkpoint inside a collection commit wrote ~43k pages
    # back at random positions, 7 of 17 s, under the write lock. Commits now only append to the WAL.
    fdb = FlowDb(tmp_path / "flows.sqlite")
    fdb.connect().close()
    before = fdb.path.stat().st_size
    _write_pages(fdb, 3000)  # three times SQLite's default automatic-checkpoint threshold
    assert fdb.path.stat().st_size - before < 1_000_000  # still in the WAL
    done = fdb.checkpoint()
    assert done >= 3000 and fdb.path.stat().st_size - before > 12_000_000


def test_a_stalled_background_checkpoint_still_bounds_the_wal(tmp_path):
    fdb = FlowDb(tmp_path / "flows.sqlite")
    with fdb.connect() as conn:
        assert conn.execute("PRAGMA wal_autocheckpoint").fetchone()[0] == FlowDb.WAL_SAFETY_NET_PAGES
        assert conn.execute("PRAGMA journal_size_limit").fetchone()[0] == FlowDb.WAL_KEEP_BYTES


def test_a_flow_store_commit_does_not_wait_for_the_disk(tmp_path):
    # With synchronous=FULL each commit fsyncs the WAL behind the background checkpoint's writes:
    # retention holds of the lock reached 20.9 s, 11.5 s with NORMAL (P2 re-measure).
    conn = FlowDb(tmp_path / "flows.sqlite").connect()
    assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1  # NORMAL


def test_a_flow_store_connection_is_closed_when_its_block_ends(tmp_path):
    # sqlite3's own `with` only commits; FlowDb must know when no connection to the file is left.
    fdb = FlowDb(tmp_path / "flows.sqlite")
    with fdb.connect() as conn:
        conn.execute("SELECT 1")
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_reset_waits_until_no_connection_to_the_file_is_open(tmp_path):
    # Unlinking the file under an open connection lets that connection, when it closes last on the old
    # file, delete the new file's WAL and shared memory by name (sqlite.org/howtocorrupt.html).
    fdb = FlowDb(tmp_path / "flows.sqlite")
    reader = fdb.connect()
    done = []
    t = threading.Thread(target=lambda: (fdb.reset(), done.append(True)))
    t.start()
    t.join(0.3)
    assert done == [] and fdb.generation == 1  # bumped first, so long readers can notice and stop
    reader.close()
    t.join(5)
    assert done == [True]


def test_reset_gives_up_when_a_connection_stays_open(tmp_path, monkeypatch):
    monkeypatch.setattr(flowdb, "RESET_WAIT_SECONDS", 0.2, raising=False)
    fdb = FlowDb(tmp_path / "flows.sqlite")
    with fdb.connect() as conn:
        conn.execute("INSERT INTO pce_binding(id, pce_url, org_id, bound_at) VALUES (1, 'https://a', '1', 'x')")
        conn.commit()
    reader = fdb.connect()
    with pytest.raises(flowdb.FlowDbBusy):
        fdb.reset()
    reader.close()
    with fdb.connect() as conn:  # nothing was deleted
        assert conn.execute("SELECT count(*) FROM pce_binding").fetchone()[0] == 1


def test_a_connection_asked_for_during_a_reset_gets_the_new_file(tmp_path):
    # Opened while the reset waited, it would sit on the old file when that is deleted.
    fdb = FlowDb(tmp_path / "flows.sqlite")
    with fdb.connect() as conn:
        conn.execute("INSERT INTO pce_binding(id, pce_url, org_id, bound_at) VALUES (1, 'https://a', '1', 'x')")
        conn.commit()
    reader = fdb.connect()
    t = threading.Thread(target=fdb.reset)
    t.start()
    while fdb.generation == 0:
        pass
    seen = []
    late = threading.Thread(target=lambda: seen.append(
        fdb.connect().execute("SELECT count(*) FROM pce_binding").fetchone()[0]))
    late.start()
    late.join(0.3)
    assert seen == []  # it waits for the reset
    reader.close()
    t.join(5)
    late.join(5)
    assert seen == [0]


def test_connections_opened_during_a_long_migration_wait_for_it(tmp_path, monkeypatch):
    # .106 upgrade: one job thread applied flow db 0002 while the others gave up on SQLite's busy
    # timeout ("database is locked") and failed; at 1,000 workloads 0002 runs 820 s.
    from illumio_ops.store import db as storedb

    path = tmp_path / "flows.sqlite"
    FlowDb(path).connect().close()  # the current schema, as an installed store has it
    original = storedb._migrations
    real = original(flowdb.MIGRATIONS_PACKAGE)
    slow = ("CREATE TABLE slow_step AS WITH RECURSIVE c(x) AS "
            "(SELECT 1 UNION ALL SELECT x + 1 FROM c WHERE x < 1500000) SELECT x FROM c;")
    monkeypatch.setattr(storedb, "_migrations", lambda package=storedb.APP_MIGRATIONS:
                        real + [(len(real) + 1, slow)] if package == flowdb.MIGRATIONS_PACKAGE
                        else original(package))
    monkeypatch.setattr(storedb, "BUSY_TIMEOUT_SECONDS", 0.1)
    fdb = FlowDb(path)  # the upgraded program starts
    start = threading.Barrier(4)
    errors, versions = [], []

    def job():
        start.wait()
        try:
            with fdb.connect() as conn:
                versions.append(conn.execute("PRAGMA user_version").fetchone()[0])
        except Exception as exc:  # noqa: BLE001 - the failure under test
            errors.append(exc)

    threads = [threading.Thread(target=job) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert errors == []
    assert versions == [len(real) + 1] * 4
