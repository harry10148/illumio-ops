"""Flow DB 0002: each record keeps its own byte counts (F10), the baseline keeps the newest decision,
and admin-port reads of the baseline use an index."""
import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from importlib import resources
from pathlib import Path

import pytest

from illumio_ops.domain.flows import normalize_flow
from illumio_ops.domain.values import DataOrigin
from illumio_ops.store.flowdb.db import FlowDb
from illumio_ops.store.flowdb.flows import upsert_flows

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "pce" / "flows_sample.json"
NOW = datetime(2026, 10, 24, 7, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def recs():
    return [normalize_flow(r) for r in json.loads(FIXTURE.read_text())]


@pytest.fixture
def conn(tmp_path):
    c = FlowDb(tmp_path / "flows.sqlite").connect()
    yield c
    c.close()


def _rows(conn, sql="SELECT * FROM flows ORDER BY id", *args):
    return [dict(r) for r in conn.execute(sql, args)]


def test_repair_does_not_double_count_bytes(conn, recs):
    inbound, outbound = recs[0], recs[1]  # one connection reported by both VENs
    a = replace(outbound, bytes_in=100, bytes_out=10)
    b = replace(inbound, bytes_in=500, bytes_out=50)
    upsert_flows(conn, [a, b], origin=DataOrigin.INGEST, now=NOW)
    assert [r["bytes_in"] for r in _rows(conn) if r["is_primary"]] == [500]
    # An earlier outbound record of the same tuple arrives late and takes b over (pairing goes in
    # first_detected order); a is left alone and must count only its own bytes again.
    start = min(a.first_detected, b.first_detected) - timedelta(seconds=30)
    a2 = replace(outbound, first_detected=start, last_detected=b.first_detected + timedelta(seconds=30),
                 bytes_in=7, bytes_out=1)
    upsert_flows(conn, [a2], origin=DataOrigin.INGEST, now=NOW)
    primaries = [r for r in _rows(conn) if r["is_primary"]]
    assert len(primaries) == 2
    assert sum(r["bytes_in"] for r in primaries) == 600 and sum(r["bytes_out"] for r in primaries) == 60


def test_record_without_bytes_does_not_take_its_partners_on_repair(conn, recs):
    # Final review #2: a new record's NULL own count (no byte data) was read as "legacy, keep the merged".
    inbound, outbound = recs[0], recs[1]
    a = replace(outbound, bytes_in=None, bytes_out=None)
    b = replace(inbound, bytes_in=500, bytes_out=50)
    upsert_flows(conn, [a, b], origin=DataOrigin.INGEST, now=NOW)
    start = min(a.first_detected, b.first_detected) - timedelta(seconds=30)
    a2 = replace(outbound, first_detected=start, last_detected=b.first_detected + timedelta(seconds=30),
                 bytes_in=None, bytes_out=None)
    upsert_flows(conn, [a2], origin=DataOrigin.INGEST, now=NOW)
    primaries = [r for r in _rows(conn) if r["is_primary"]]
    assert len(primaries) == 2 and sum(r["bytes_in"] or 0 for r in primaries) == 500


def test_refresh_grows_own_bytes(conn, recs):
    a = replace(recs[1], bytes_in=100, bytes_out=None)
    upsert_flows(conn, [a], origin=DataOrigin.INGEST, now=NOW)
    later = a.last_detected + timedelta(minutes=10)
    upsert_flows(conn, [replace(a, bytes_in=150, last_detected=later)], origin=DataOrigin.INGEST, now=NOW)
    upsert_flows(conn, [replace(a, bytes_in=120, last_detected=later + timedelta(minutes=1))],
                 origin=DataOrigin.INGEST, now=NOW)
    upsert_flows(conn, [replace(a, bytes_in=None, last_detected=later + timedelta(minutes=2))],
                 origin=DataOrigin.INGEST, now=NOW)
    [row] = _rows(conn)
    assert (row["own_bytes_in"], row["bytes_in"], row["own_bytes_out"]) == (150, 150, None)


def _v1_db(path):
    sql = (resources.files("illumio_ops.store.flowdb.migrations") / "0001_flows.sql").read_text()
    c = sqlite3.connect(path)
    c.executescript(sql + "\nPRAGMA user_version = 1;")
    return c


def _legacy_row(c, rid, conn_key, direction, primary, bytes_in, *, decision="allowed", last="2026-10-20T10:00:00.000+00:00",
                src="ip:10.0.0.1", dst="ip:10.0.0.2", port=22):
    c.execute(
        "INSERT INTO flows (id, record_key, conn_key, is_primary, direction, src_ip, dst_ip, src_key, dst_key, "
        "src_managed, dst_managed, port, proto, policy_decision, first_detected, last_detected, num_connections, "
        "bytes_in, origin, ingested_at) VALUES (?, ?, ?, ?, ?, '10.0.0.1', '10.0.0.2', ?, ?, 0, 0, ?, 6, ?, ?, ?, 1, ?, "
        "'ingest', ?)",
        (rid, f"r{rid}", conn_key, primary, direction, src, dst, port, decision, last, last, bytes_in, last))


def test_legacy_multi_row_connection_keeps_bytes_after_0002(tmp_path):
    p = tmp_path / "flows.sqlite"
    c = _v1_db(p)
    _legacy_row(c, 1, "k1", "outbound", 1, 500)   # primary already holds the pair's maximum
    _legacy_row(c, 2, "k1", "inbound", 0, 500)
    _legacy_row(c, 3, "k2", "outbound", 1, 42, port=445)   # a lone record: its bytes are its own
    c.commit()
    c.close()
    with FlowDb(p).connect() as conn:
        rows = {r["id"]: r for r in _rows(conn)}
    assert rows[3]["own_bytes_in"] == 42
    # A pair's own counts were not kept before 0002: each row's shown count stands in for it (final
    # review #2 ruling), so a NULL own count after 0002 always means "no byte data".
    assert rows[1]["own_bytes_in"] == 500 and rows[2]["own_bytes_in"] == 500
    assert rows[1]["bytes_in"] == 500


def test_baseline_tracks_newest_decision(conn, recs):
    r = replace(recs[5], policy_decision="potentially_blocked")
    upsert_flows(conn, [r], origin=DataOrigin.INGEST, now=NOW)
    newer = replace(r, policy_decision="allowed", first_detected=r.first_detected + timedelta(days=1),
                    last_detected=r.last_detected + timedelta(days=1))
    upsert_flows(conn, [newer], origin=DataOrigin.INGEST, now=NOW)
    older = replace(r, policy_decision="blocked", first_detected=r.first_detected - timedelta(days=2),
                    last_detected=r.last_detected - timedelta(days=2))
    upsert_flows(conn, [older], origin=DataOrigin.BACKFILL, now=NOW)
    [b] = _rows(conn, "SELECT * FROM connection_baseline")
    assert b["last_decision"] == "allowed"


def test_0002_backfills_last_decision(tmp_path):
    p = tmp_path / "flows.sqlite"
    c = _v1_db(p)
    _legacy_row(c, 1, "k1", "outbound", 1, None, decision="potentially_blocked", last="2026-10-19T10:00:00.000+00:00")
    _legacy_row(c, 2, "k2", "outbound", 1, None, decision="allowed", last="2026-10-20T10:00:00.000+00:00")
    _legacy_row(c, 3, "k3", "outbound", 1, None, decision="blocked", last="2026-10-20T11:00:00.000+00:00", port=445)
    c.execute("INSERT INTO connection_baseline VALUES ('ip:10.0.0.1', 'ip:10.0.0.2', 22, 6, "
              "'2026-10-19T10:00:00.000+00:00', '2026-10-20T10:00:00.000+00:00')")
    c.execute("INSERT INTO connection_baseline VALUES ('ip:10.0.0.1', 'ip:10.0.0.2', 445, 6, "
              "'2026-10-20T11:00:00.000+00:00', '2026-10-20T11:00:00.000+00:00')")
    c.execute("INSERT INTO connection_baseline VALUES ('ip:10.0.0.9', 'ip:10.0.0.2', 22, 6, "
              "'2026-10-01T11:00:00.000+00:00', '2026-10-01T11:00:00.000+00:00')")  # its flows are gone
    c.commit()
    c.close()
    with FlowDb(p).connect() as conn:
        got = {(r["src_key"], r["port"]): r["last_decision"] for r in conn.execute("SELECT * FROM connection_baseline")}
    assert got == {("ip:10.0.0.1", 22): "allowed", ("ip:10.0.0.1", 445): "blocked", ("ip:10.0.0.9", 22): None}


def test_baseline_port_query_uses_index(conn):
    plan = " ".join(str(r[3]) for r in conn.execute(
        "EXPLAIN QUERY PLAN SELECT src_key, dst_key, port, proto, last_seen FROM connection_baseline "
        "WHERE port IN (22, 445)"))
    assert "ix_baseline_port" in plan
