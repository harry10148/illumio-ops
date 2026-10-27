"""The anomaly detectors' reads of the baselines and the hourly activity (P4.5, spec §6.5.8)."""
from datetime import timedelta

import pytest

from illumio_ops.domain.flows import normalize_flow
from illumio_ops.domain.values import DataOrigin
from illumio_ops.services import flowsource_anomaly as fa
from illumio_ops.store.flowdb.db import StaleGeneration
from illumio_ops.store.flowdb.flows import upsert_flows
from tests_v6.services.collect.conftest import NOW, configured_ctx, raw_flow

SRC = "/orgs/1/workloads/src-{}"
DST = "/orgs/1/workloads/dst"


def rec(i, *, minutes_ago=1, port=445, user=None, process=None, conns=1, dst_ip=None, dst_href=None):
    raw = raw_flow(i, NOW - timedelta(minutes=minutes_ago + 5), NOW - timedelta(minutes=minutes_ago), port=port,
                   user=user)
    raw["num_connections"] = conns
    if process:
        raw["service"]["process_name"] = process
    if dst_ip:
        raw["dst"]["ip"] = dst_ip
    if dst_href is not None:
        raw["dst"]["workload"] = {"href": dst_href, "hostname": dst_href, "managed": True, "labels": []} \
            if dst_href else None
    return normalize_flow(raw)


@pytest.fixture
def ctx(tmp_path):
    return configured_ctx(tmp_path)


def write(ctx, recs, *, origin=DataOrigin.INGEST, now=NOW, increments="none"):
    with ctx.flows().connect() as conn:
        upsert_flows(conn, recs, origin=origin, now=now, increments=increments)


DAY = 24 * 60


def test_account_reads(ctx):
    write(ctx, [rec(1, minutes_ago=10 * DAY, user="CORP\\Alice"), rec(2, user="corp\\alice")],
          origin=DataOrigin.BACKFILL)
    first = fa.account_first_seen(ctx, [("corp\\alice", SRC.format(1)), ("corp\\alice", SRC.format(2)),
                                        ("corp\\nobody", SRC.format(1))])
    assert set(first) == {("corp\\alice", SRC.format(1)), ("corp\\alice", SRC.format(2))}
    assert fa.account_since(ctx, ["corp\\alice"])["corp\\alice"] == first[("corp\\alice", SRC.format(1))]
    assert fa.account_history(ctx, ["corp\\alice"], before=NOW - timedelta(days=1)) == {"corp\\alice": 1}


def test_process_reads(ctx):
    write(ctx, [rec(1, minutes_ago=10 * DAY, process="sshd"), rec(1, port=22, process="curl")],
          origin=DataOrigin.BACKFILL)
    first = fa.process_first_seen(ctx, [(SRC.format(1), "curl"), (SRC.format(1), "sshd")])
    assert first[(SRC.format(1), "sshd")] < first[(SRC.format(1), "curl")]
    assert fa.process_since(ctx, [SRC.format(1)])[SRC.format(1)] == first[(SRC.format(1), "sshd")]


def test_peer_seen(ctx):
    write(ctx, [rec(1, minutes_ago=5 * DAY, port=8443), rec(2, port=8443), rec(3, minutes_ago=5 * DAY, port=22)],
          origin=DataOrigin.BACKFILL)
    members = [SRC.format(i) for i in (1, 2, 3)]
    got = fa.peer_seen(ctx, {("g", 8443, 6): members, ("h", 8443, 6): members[1:], ("g", 22, 6): members},
                       before=NOW - timedelta(days=1))
    assert got == {("g", 8443, 6): {DST}, ("h", 8443, 6): set(), ("g", 22, 6): {DST}}


def test_peer_seen_reads_every_group_on_one_connection(ctx, monkeypatch):
    """Scale: a run asks about thousands of (group, port) pairs; each must not open its own connection."""
    write(ctx, [rec(1, minutes_ago=5 * DAY, port=8443)], origin=DataOrigin.BACKFILL)
    fdb = ctx.flows()
    real, opened = fdb.connect, []

    def connect():
        opened.append(1)
        return real()
    monkeypatch.setattr(fdb, "connect", connect)
    fa.peer_seen(ctx, {(f"g{i}", 8443, 6): [SRC.format(1)] for i in range(50)}, before=NOW)
    assert len(opened) == 1


def test_directory_reads(ctx):
    write(ctx, [rec(i, minutes_ago=3 * DAY, port=88) for i in (1, 2, 3)] + [rec(4, port=389)],
          origin=DataOrigin.BACKFILL)
    assert fa.directory_sources(ctx, [(88, None), (389, None)], since=NOW - timedelta(days=30)) == {DST: 4}
    assert fa.directory_sources(ctx, [(389, None)], since=NOW - timedelta(days=30)) == {DST: 1}
    before = fa.directory_clients_before(ctx, [SRC.format(i) for i in (1, 4, 9)], [DST], [(88, None), (389, None)],
                                         before=NOW - timedelta(days=1))
    assert before == {SRC.format(1)}


def test_activity_reads(ctx):
    write(ctx, [rec(1, conns=40)], now=NOW - timedelta(days=2), increments="cycle")
    write(ctx, [rec(1, conns=100)], now=NOW - timedelta(days=1), increments="cycle")  # grew by 60
    write(ctx, [rec(1, conns=400), rec(2, port=389, conns=7)], now=NOW - timedelta(minutes=20), increments="cycle")
    now = fa.activity_now(ctx, since=NOW - timedelta(minutes=60), until=NOW)
    assert now == {(SRC.format(1), "all"): (300, None), (SRC.format(2), "all"): (7, None),
                   (SRC.format(2), "directory"): (7, None)}
    hist = fa.activity_history(ctx, [SRC.format(1)], start=NOW - timedelta(days=7), end=NOW - timedelta(hours=2))
    assert hist == {(SRC.format(1), "all"): (60, None)}  # no hour carried byte data
    assert fa.activity_coverage(ctx) == (NOW - timedelta(days=2)).replace(minute=0)


def test_activity_now_takes_the_connections_current_primary_row(ctx):
    """The record measured may have paired since: its connection's primary row names the source."""
    write(ctx, [rec(1, conns=9)], now=NOW - timedelta(minutes=20), increments="cycle")
    with ctx.flows().connect() as conn:
        conn.execute("CREATE TEMP TABLE t AS SELECT * FROM flows")
        conn.execute("UPDATE t SET id = NULL, record_key = 'paired', src_key = 'other', is_primary = 1")
        conn.execute("UPDATE flows SET is_primary = 0")
        conn.execute("INSERT INTO flows SELECT * FROM t")
        conn.commit()
    assert fa.activity_now(ctx, since=NOW - timedelta(minutes=60), until=NOW) == {("other", "all"): (9, None)}


def _switching(ctx, monkeypatch):
    fdb = ctx.flows()
    real = fdb.connect

    def connect():
        fdb.generation += 1  # the operator saves another PCE while the read runs
        return real()
    monkeypatch.setattr(fdb, "connect", connect)


@pytest.mark.parametrize("read", [
    lambda c: fa.account_first_seen(c, [("a", "b")]),
    lambda c: fa.account_since(c, ["a"]),
    lambda c: fa.account_history(c, ["a"], before=NOW),
    lambda c: fa.process_first_seen(c, [("a", "b")]),
    lambda c: fa.process_since(c, ["a"]),
    lambda c: fa.peer_seen(c, {("g", 1, 6): ["a"]}, before=NOW),
    lambda c: fa.directory_sources(c, [(88, None)], since=NOW),
    lambda c: fa.directory_clients_before(c, ["a"], ["b"], [(88, None)], before=NOW),
    lambda c: fa.activity_now(c, since=NOW, until=NOW),
    lambda c: fa.activity_history(c, ["a"], start=NOW, end=NOW),
    lambda c: fa.activity_coverage(c),
    lambda c: fa.activity_gaps(c, start=NOW, end=NOW),
])
def test_reads_raise_stale_after_pce_switch(ctx, monkeypatch, read):
    _switching(ctx, monkeypatch)
    with pytest.raises(StaleGeneration):
        read(ctx)


def test_activity_history_bytes_only_from_hours_with_byte_data(ctx):
    with ctx.flows().connect() as conn:
        conn.executemany("INSERT INTO source_activity_hourly VALUES (?, ?, 'all', ?, ?, ?)", [
            ("2026-10-23T10:00:00.000+00:00", "s", 10, 0, 0), ("2026-10-23T11:00:00.000+00:00", "s", 5, 900, 2)])
        conn.commit()
    hist = fa.activity_history(ctx, ["s"], start=NOW - timedelta(days=7), end=NOW)
    assert hist == {("s", "all"): (10, 900)}


def test_directory_reads_keep_each_ports_protocol(ctx):
    """Review: TCP 8443 added as a directory port must not make UDP 8443 traffic count toward inference."""
    udp = [rec(i, minutes_ago=3 * DAY, port=8443) for i in (1, 2, 3)]
    udp = [type(r)(**{**r.__dict__, "proto": 17}) for r in udp]
    write(ctx, udp, origin=DataOrigin.BACKFILL)
    assert fa.directory_sources(ctx, [(8443, 6)], since=NOW - timedelta(days=30)) == {}
    assert fa.directory_sources(ctx, [(8443, None)], since=NOW - timedelta(days=30)) == {DST: 3}
    assert fa.directory_clients_before(ctx, [SRC.format(1)], [DST], [(8443, 6)], before=NOW) == set()


def test_activity_gaps_name_recorded_gaps(ctx):
    from illumio_ops.domain.values import IngestSource
    from illumio_ops.store.flowdb import ingest_state
    with ctx.flows().connect() as conn:
        ingest_state.add_coverage(conn, IngestSource.TRAFFIC, NOW - timedelta(days=8), NOW)
        ingest_state.record_gap(conn, IngestSource.TRAFFIC, NOW - timedelta(days=3, hours=1), NOW - timedelta(days=3),
                                kind="truncated", detail="x", at=NOW)
    gaps = fa.activity_gaps(ctx, start=NOW - timedelta(days=7), end=NOW)
    assert [(g[0], g[2]) for g in gaps] == [(NOW - timedelta(days=3, hours=1), "truncated")]
