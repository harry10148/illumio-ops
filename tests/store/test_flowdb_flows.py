"""Flow store writes: idempotent upsert, dual-report pairing, baselines and the daily rollup."""
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from illumio_ops.domain.flows import normalize_flow
from illumio_ops.domain.values import DataOrigin
from illumio_ops.store.flowdb.db import FlowDb
from illumio_ops.store.flowdb.flows import rebuild_rollup, upsert_flows

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


def test_upsert_is_idempotent(conn, recs):
    first = upsert_flows(conn, recs, origin=DataOrigin.INGEST, now=NOW)
    again = upsert_flows(conn, recs, origin=DataOrigin.INGEST, now=NOW)
    assert first.inserted == len(recs) and again.inserted == 0 and again.unchanged == len(recs)
    assert conn.execute("SELECT count(*) FROM flows").fetchone()[0] == len(recs)


def test_identical_repull_writes_nothing(conn, recs):
    # Collection re-reads an overlap every cycle (late records): a record that comes back the same
    # costs a lookup, not a rewrite, a re-pairing, a rollup rebuild or a re-archive of its day.
    upsert_flows(conn, recs, origin=DataOrigin.INGEST, now=NOW)
    before = conn.total_changes
    again = upsert_flows(conn, recs, origin=DataOrigin.INGEST, now=NOW + timedelta(minutes=10))
    assert conn.total_changes == before
    assert again.refreshed == 0 and again.days_touched == frozenset()


def test_repull_that_adds_a_process_is_written(conn, recs):
    r = next(x for x in recs if x.own_process is None)
    upsert_flows(conn, [r], origin=DataOrigin.INGEST, now=NOW)
    stats = upsert_flows(conn, [replace(r, own_process="sshd")], origin=DataOrigin.INGEST, now=NOW)
    column = "initiator_process" if r.direction.value == "outbound" else "service_process"
    assert stats.refreshed == 1 and _rows(conn)[0][column] == "sshd"


def test_repull_refreshes_volatile_columns_with_max(conn, recs):
    r = recs[0]
    upsert_flows(conn, [r], origin=DataOrigin.INGEST, now=NOW)
    later = replace(r, last_detected=r.last_detected + timedelta(minutes=10),
                    num_connections=r.num_connections + 5, bytes_in=r.bytes_in + 100, state="closed")
    upsert_flows(conn, [later], origin=DataOrigin.INGEST, now=NOW)
    older = replace(r, num_connections=1, bytes_in=1)  # an out-of-order re-pull never shrinks counters
    upsert_flows(conn, [older], origin=DataOrigin.INGEST, now=NOW)
    [row] = _rows(conn)
    assert row["num_connections"] == r.num_connections + 5 and row["bytes_in"] == r.bytes_in + 100
    assert row["last_detected"].startswith((r.last_detected + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M"))
    assert row["state"] == "closed"


def test_bytes_null_never_overwrites_known(conn, recs):
    r = recs[0]
    upsert_flows(conn, [r], origin=DataOrigin.INGEST, now=NOW)
    upsert_flows(conn, [replace(r, bytes_in=None, bytes_out=None)], origin=DataOrigin.INGEST, now=NOW)
    assert _rows(conn)[0]["bytes_in"] == r.bytes_in


def test_backfill_does_not_downgrade_ingest_origin(conn, recs):
    upsert_flows(conn, [recs[2]], origin=DataOrigin.INGEST, now=NOW)
    upsert_flows(conn, [recs[2]], origin=DataOrigin.BACKFILL, now=NOW)
    assert _rows(conn)[0]["origin"] == "ingest"
    upsert_flows(conn, [recs[3]], origin=DataOrigin.BACKFILL, now=NOW)
    upsert_flows(conn, [recs[3]], origin=DataOrigin.INGEST, now=NOW)
    assert _rows(conn)[1]["origin"] == "ingest"  # seen live again: now current data


def test_two_sided_report_counts_once(conn, recs):
    inbound, outbound = recs[0], recs[1]  # one connection, reported by both VENs
    stats = upsert_flows(conn, [inbound, outbound], origin=DataOrigin.INGEST, now=NOW)
    assert stats.paired == 1
    rows = _rows(conn)
    assert len({r["conn_key"] for r in rows}) == 1
    assert sum(r["is_primary"] for r in rows) == 1
    primary = next(r for r in rows if r["is_primary"])
    assert primary["direction"] == "outbound"
    assert primary["bytes_in"] == inbound.bytes_in  # the primary shows the inbound half's bytes


def test_pair_attributes_are_complemented(conn, recs):
    out = replace(recs[1], own_process="mstsc.exe", own_user="LAB\\user-09")
    inn = replace(recs[0], own_process="svchost.exe", own_user="NT AUTHORITY\\NETWORK SERVICE")
    upsert_flows(conn, [out, inn], origin=DataOrigin.INGEST, now=NOW)
    for row in _rows(conn):
        assert (row["initiator_process"], row["initiator_user"]) == ("mstsc.exe", "LAB\\user-09")
        assert (row["service_process"], row["service_user"]) == ("svchost.exe", "NT AUTHORITY\\NETWORK SERVICE")


def test_inbound_first_then_outbound_switches_primary(conn, recs):
    upsert_flows(conn, [recs[0]], origin=DataOrigin.INGEST, now=NOW)
    assert _rows(conn)[0]["is_primary"] == 1
    upsert_flows(conn, [recs[1]], origin=DataOrigin.INGEST, now=NOW)
    rows = _rows(conn)
    assert [r["is_primary"] for r in rows] == [0, 1]


def test_pairing_rejects_far_apart_records(conn, recs):
    far = replace(recs[1], first_detected=recs[0].last_detected + timedelta(hours=2),
                  last_detected=recs[0].last_detected + timedelta(hours=3))
    upsert_flows(conn, [recs[0], far], origin=DataOrigin.INGEST, now=NOW)
    assert sum(r["is_primary"] for r in _rows(conn)) == 2


def test_baseline_tracks_min_first_and_max_last(conn, recs):
    r = recs[5]
    upsert_flows(conn, [r], origin=DataOrigin.BACKFILL, now=NOW)
    later = replace(r, first_detected=r.first_detected + timedelta(days=1),
                    last_detected=r.last_detected + timedelta(days=1))
    upsert_flows(conn, [later], origin=DataOrigin.INGEST, now=NOW)
    [b] = _rows(conn, "SELECT * FROM connection_baseline")
    assert b["first_seen"].startswith(r.first_detected.strftime("%Y-%m-%dT%H:%M"))
    assert b["last_seen"].startswith(later.last_detected.strftime("%Y-%m-%dT%H:%M"))
    assert (b["port"], b["proto"]) == (3306, 6)


def test_user_baseline_skips_empty_user(conn, recs):
    with_user = recs[6]   # outbound, user-03
    without = recs[17]    # outbound, no user
    upsert_flows(conn, [with_user, without], origin=DataOrigin.INGEST, now=NOW)
    rows = _rows(conn, "SELECT * FROM user_baseline")
    assert [r["initiator_user"] for r in rows] == ["user-03"]


def test_rollup_counts_primary_rows_only(conn, recs):
    upsert_flows(conn, [recs[0], recs[1]], origin=DataOrigin.INGEST, now=NOW)
    day = recs[1].last_detected.strftime("%Y-%m-%d")
    assert rebuild_rollup(conn, day) == 1
    [roll] = _rows(conn, "SELECT * FROM flow_rollup_daily")
    assert roll["flow_records"] == 1 and roll["connections"] == recs[1].num_connections
    assert roll["bytes_known_records"] == 1


def test_rollup_null_keys_coalesced(conn, recs):
    no_port = replace(recs[17], port=None, own_user=None, own_process=None)
    upsert_flows(conn, [no_port], origin=DataOrigin.INGEST, now=NOW)
    rebuild_rollup(conn, no_port.last_detected.strftime("%Y-%m-%d"))
    [roll] = _rows(conn, "SELECT * FROM flow_rollup_daily")
    assert (roll["port"], roll["initiator_user"], roll["initiator_process"]) == (-1, "", "")


def test_days_touched_includes_the_day_a_flow_left(conn, recs):
    r = recs[2]
    upsert_flows(conn, [r], origin=DataOrigin.INGEST, now=NOW)
    moved = replace(r, last_detected=r.last_detected + timedelta(days=1))
    stats = upsert_flows(conn, [moved], origin=DataOrigin.INGEST, now=NOW)
    assert stats.days_touched == {r.last_detected.strftime("%Y-%m-%d"), moved.last_detected.strftime("%Y-%m-%d")}


def test_labels_become_shared_sets(conn, recs):
    upsert_flows(conn, recs, origin=DataOrigin.INGEST, now=NOW)
    n_sets = conn.execute("SELECT count(*) FROM label_sets").fetchone()[0]
    distinct = {r.src_labels for r in recs if r.src_labels} | {r.dst_labels for r in recs if r.dst_labels}
    assert n_sets == len(distinct)


@pytest.mark.parametrize("field", ["num_connections", "bytes_in", "bytes_out"])
def test_repull_with_larger_counters_at_the_same_time_is_written(conn, recs, field):
    r = recs[0]
    upsert_flows(conn, [r], origin=DataOrigin.INGEST, now=NOW)
    larger = (getattr(r, field) or 0) + 1000
    stats = upsert_flows(conn, [replace(r, **{field: larger})], origin=DataOrigin.INGEST, now=NOW)
    assert stats.refreshed == 1 and _rows(conn)[0][field] == larger
