"""The investigation table's peer-precedent column (UI redesign spec §5.1): for a row of a source host and a
destination, how many other members of the source's peer group had connected to a destination of the same kind
(its own peer group, or the host itself) before the period began."""
from datetime import UTC, datetime, timedelta

import pytest

from illumio_ops.domain.filter import FlowCondition, PortProto
from illumio_ops.domain.segment import GroupBy
from illumio_ops.domain.values import SegmentDimension, SegmentView
from illumio_ops.services.flowsource import AggRow
from illumio_ops.services.workbench import FlowRequest
from illumio_ops.services.workbench_peer import peer_precedent
from illumio_ops.store.flowdb import workloads
from illumio_ops.store.flowdb.db import db_time
from illumio_ops.store.flowdb.labels import label_set_id
from tests.services.collect.conftest import configured_ctx

NOW = datetime(2026, 11, 3, 12, tzinfo=UTC)
START = NOW - timedelta(days=1)
A, B, C, D = (f"/orgs/1/workloads/{n}" for n in "abcd")
X, Y = "/orgs/1/workloads/x", "/orgs/1/workloads/y"
LONE = "/orgs/1/workloads/lone"


def _wl(href, label_set):
    return workloads.WorkloadRow(
        href=href, hostname=href.rsplit("/", 1)[1], name=None, managed=1, enforcement_mode="selective",
        visibility_level=None, os_id=None, ven_version=None, ven_href=None, label_set=label_set, online=1,
        risk_exposure=None, risk_percent=None, risk_updated_at=None, fetched_at="x")


def _base(conn, src, dst, port, first):
    conn.execute("INSERT INTO connection_baseline (src_key, dst_key, port, proto, first_seen, last_seen) "
                 "VALUES (?, ?, ?, 6, ?, ?)", (src, dst, port, db_time(first), db_time(first)))


@pytest.fixture
def ctx(tmp_path):
    c = configured_ctx(tmp_path, mode="full")
    c.settings.update(c.settings.current().revision,
                      lambda d: d["lateral"]["detectors"].update({"peer_min_group": 3}))
    with c.flows().connect() as conn:
        pay = label_set_id(conn, (("app", "pay"), ("role", "web")))
        db = label_set_id(conn, (("app", "pay"), ("role", "db")))
        other = label_set_id(conn, (("app", "hr"), ("role", "web")))
        workloads.replace_inventory(conn, [_wl(h, pay) for h in (A, B, C, D)] + [_wl(X, db), _wl(Y, db),
                                                                                _wl(LONE, other)])
        before = START - timedelta(days=3)
        _base(conn, B, X, 1433, before)
        _base(conn, C, Y, 1433, before)            # another host of the same kind counts
        _base(conn, D, X, 1433, NOW)               # after the period began: not a precedent
        _base(conn, A, X, 1433, before)            # the row's own source is not a peer
        _base(conn, B, X, 22, before)              # another port
        conn.commit()
    return c


MSSQL = (PortProto(port=1433, proto=6),)


def _req(*dims, ports=MSSQL):
    return FlowRequest(mode="flows", start=START, end=NOW, view=SegmentView.RANKING,
                       group_by=tuple(GroupBy(dimension=d) for d in dims), condition=FlowCondition(ports=ports))


def _row(*keys):
    return AggRow(keys=list(keys), display=[None] * len(keys), value=1, bytes_known=None)


def test_counts_other_members_with_same_destination_kind(ctx):
    p = peer_precedent(ctx, _req(SegmentDimension.SRC_HOST, SegmentDimension.DST_HOST), [_row(A, X)], now=NOW)
    assert p.state == "ok" and p.values == [2]


def test_ports_scope_any_port_when_unfiltered(ctx):
    p = peer_precedent(ctx, _req(SegmentDimension.SRC_HOST, SegmentDimension.DST_HOST, ports=()), [_row(A, X)],
                       now=NOW)
    assert p.values == [2] and p.ports == []


def test_dst_first_column_order(ctx):
    p = peer_precedent(ctx, _req(SegmentDimension.DST_HOST, SegmentDimension.SRC_HOST), [_row(X, A)], now=NOW)
    assert p.values == [2]


def test_column_absent_without_source_dimension(ctx):
    p = peer_precedent(ctx, _req(SegmentDimension.DST_HOST), [_row(X)], now=NOW)
    assert p.state == "no_source_dimension" and p.values == [None]


def test_needs_destination(ctx):
    p = peer_precedent(ctx, _req(SegmentDimension.SRC_HOST), [_row(A)], now=NOW)
    assert p.state == "needs_destination" and p.values == [None]


def test_group_too_small_or_ungrouped_row(ctx):
    p = peer_precedent(ctx, _req(SegmentDimension.SRC_HOST, SegmentDimension.DST_HOST),
                       [_row(LONE, X), _row("ip:10.0.0.9", X), _row(A, X)], now=NOW)
    assert p.state == "ok" and p.values == [None, None, 2]
    assert p.reasons == ["group_too_small", "no_group", None]


def test_basic_mode_state(tmp_path):
    light = configured_ctx(tmp_path, mode="lightweight")
    p = peer_precedent(light, _req(SegmentDimension.SRC_HOST, SegmentDimension.DST_HOST), [_row(A, X)], now=NOW)
    assert p.state == "basic_mode" and p.values == [None]


def test_port_range_and_protocol_only(ctx):
    rng = peer_precedent(ctx, _req(SegmentDimension.SRC_HOST, SegmentDimension.DST_HOST,
                                   ports=(PortProto(port=1400, to_port=1500, proto=6),)), [_row(A, X)], now=NOW)
    assert rng.values == [2] and rng.ports == ["1400-1500/6"]
    tcp = peer_precedent(ctx, _req(SegmentDimension.SRC_HOST, SegmentDimension.DST_HOST,
                                   ports=(PortProto(proto=6),)), [_row(A, X)], now=NOW)
    assert tcp.values == [2]
