"""flow_increments: how much each connection grew in one write (spec §6.6 F12: the PCE's counts
are daily totals, so a threshold on them must use the growth, as 5.x flow_deltas did)."""
from datetime import timedelta

import pytest

from illumio_ops.domain.flows import normalize_flow
from illumio_ops.domain.values import DataOrigin
from illumio_ops.store.flowdb.db import FlowDb
from illumio_ops.store.flowdb.flows import upsert_flows
from tests_v6.services.collect.conftest import NOW, raw_flow


@pytest.fixture
def conn(tmp_path):
    c = FlowDb(tmp_path / "flows.sqlite").connect()
    yield c
    c.close()


def rec(*, conns=1, bi=None, bo=None, first_ago=30, last_ago=1, direction="outbound", src=1):
    raw = raw_flow(src, NOW - timedelta(minutes=first_ago), NOW - timedelta(minutes=last_ago), direction=direction)
    raw["num_connections"] = conns
    if bi is not None:
        raw["dst_bi"], raw["dst_bo"] = bi, bo
    return normalize_flow(raw)


def increments(conn):
    return [dict(r) for r in conn.execute(
        "SELECT record_key, observed_at, connections, bytes, seconds, late FROM flow_increments ORDER BY id")]


def test_new_record_increment_is_its_counts(conn):
    upsert_flows(conn, [rec(conns=5, bi=100, bo=50)], origin=DataOrigin.INGEST, now=NOW, increments="cycle")
    [i] = increments(conn)
    assert (i["connections"], i["bytes"], i["late"]) == (5, 150, 0)
    assert i["seconds"] == 29 * 60 + 1 and i["observed_at"].startswith("2026-10-24T12:00")


def test_repull_grown_records_only_growth(conn):
    upsert_flows(conn, [rec(conns=5, bi=100, bo=50, last_ago=11)], origin=DataOrigin.INGEST, now=NOW,
                 increments="cycle")
    later = NOW + timedelta(minutes=10)
    upsert_flows(conn, [rec(conns=8, bi=400, bo=50, last_ago=1)], origin=DataOrigin.INGEST, now=later,
                 increments="cycle")
    i = increments(conn)[-1]
    assert (i["connections"], i["bytes"], i["seconds"]) == (3, 300, 600)


def test_smaller_repull_writes_nothing(conn):
    upsert_flows(conn, [rec(conns=5)], origin=DataOrigin.INGEST, now=NOW, increments="cycle")
    upsert_flows(conn, [rec(conns=4)], origin=DataOrigin.INGEST, now=NOW + timedelta(minutes=10), increments="cycle")
    assert len(increments(conn)) == 1


def test_both_sides_reported_counted_once(conn):
    out, inn = rec(conns=5, direction="outbound"), rec(conns=5, direction="inbound")
    upsert_flows(conn, [out, inn], origin=DataOrigin.INGEST, now=NOW, increments="cycle")
    assert [i["connections"] for i in increments(conn)] == [5]


def test_repairing_does_not_double_count(conn):
    # The inbound side arrives first and stands alone; the outbound side pairs with it a cycle later.
    upsert_flows(conn, [rec(conns=5, direction="inbound")], origin=DataOrigin.INGEST, now=NOW, increments="cycle")
    upsert_flows(conn, [rec(conns=5, direction="outbound")], origin=DataOrigin.INGEST,
                 now=NOW + timedelta(minutes=10), increments="cycle")
    assert [i["connections"] for i in increments(conn)] == [5]  # the pairing added no connection


def test_backfill_writes_no_increment(conn):
    upsert_flows(conn, [rec(conns=5)], origin=DataOrigin.BACKFILL, now=NOW)
    assert increments(conn) == []


def test_reread_increment_marked_late(conn):
    upsert_flows(conn, [rec(conns=5)], origin=DataOrigin.INGEST, now=NOW, increments="late")
    assert increments(conn)[0]["late"] == 1


def test_increments_older_than_26h_deleted(conn):
    upsert_flows(conn, [rec(conns=5)], origin=DataOrigin.INGEST, now=NOW, increments="cycle")
    upsert_flows(conn, [rec(conns=1, src=7)], origin=DataOrigin.INGEST, now=NOW + timedelta(hours=26, seconds=1),
                 increments="cycle")
    assert [i["connections"] for i in increments(conn)] == [1]


def test_no_byte_data_is_null_not_zero(conn):
    upsert_flows(conn, [rec(conns=2)], origin=DataOrigin.INGEST, now=NOW, increments="cycle")
    assert increments(conn)[0]["bytes"] is None


def test_increment_names_the_connections_primary_record(conn):
    upsert_flows(conn, [rec(conns=2)], origin=DataOrigin.INGEST, now=NOW, increments="cycle")
    [i] = increments(conn)
    primary = conn.execute("SELECT record_key FROM flows WHERE is_primary = 1").fetchone()[0]
    assert i["record_key"] == primary


def test_backfilled_counts_are_not_growth_later(conn):
    """A backfill records no increment, but its counts are recorded: a later cycle adds only what grew."""
    upsert_flows(conn, [rec(conns=5)], origin=DataOrigin.BACKFILL, now=NOW)
    upsert_flows(conn, [rec(conns=7)], origin=DataOrigin.INGEST, now=NOW + timedelta(minutes=10), increments="cycle")
    assert [i["connections"] for i in increments(conn)] == [2]


def test_row_written_before_0005_counts_as_recorded(conn):
    upsert_flows(conn, [rec(conns=5)], origin=DataOrigin.BACKFILL, now=NOW)
    conn.execute("UPDATE flows SET counted_connections = NULL, counted_bytes = NULL")
    conn.commit()
    upsert_flows(conn, [rec(conns=6)], origin=DataOrigin.INGEST, now=NOW + timedelta(minutes=10), increments="cycle")
    assert [i["connections"] for i in increments(conn)] == [1]
