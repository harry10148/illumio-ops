import sqlite3
import threading

import pytest

from illumio_ops.store.flowdb.db import FlowDb
from illumio_ops.store.ownership import TABLE_OWNERS

FLOWDB_TABLES = {
    "pce_binding", "ingest_state", "ingest_gaps", "label_sets", "label_set_members", "flows",
    "flow_rollup_daily", "rollup_state", "connection_baseline", "user_baseline", "events", "workloads",
    "workload_snapshot_daily", "ransomware_services", "ransomware_snapshot_daily",
    "org_risk_snapshot_daily", "pce_capabilities", "archive_log",
}


def _tables(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_flowdb_migrates_on_first_connect(tmp_path):
    fdb = FlowDb(tmp_path / "data" / "flows.sqlite")
    with fdb.connect() as conn:
        assert FLOWDB_TABLES <= _tables(conn)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
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
