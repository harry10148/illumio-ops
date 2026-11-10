"""The lateral-movement default rankings (spec §6.5.7, 6.5.0 B3): who initiates management-port connections —
users, processes, system accounts — from domain.segment.lateral_default_segments, with how much of that traffic
names a user or a process at all."""
from datetime import UTC, datetime

import pytest

from illumio_ops.domain.values import DataOrigin
from illumio_ops.services.analysis import lateral_defaults
from illumio_ops.store.flowdb.flows import upsert_flows
from tests.services.collect.conftest import configured_ctx
from tests.services.reports.test_findings import flow

NOW = datetime(2026, 10, 27, 1, 0, tzinfo=UTC)
START, END = datetime(2026, 10, 20, tzinfo=UTC), datetime(2026, 10, 27, tzinfo=UTC)


@pytest.fixture
def ctx(tmp_path):
    c = configured_ctx(tmp_path)
    with c.flows().connect() as conn:
        upsert_flows(conn, [
            flow(src="adm", dst="db1", port=3389, user="CORP\\alice"),
            flow(src="adm", dst="db2", port=3389, user="CORP\\alice"),
            flow(src="adm", dst="db1", port=22, user="CORP\\bob"),
            flow(src="bak", dst="db1", port=445, user="root"),
            flow(src="bak", dst="db2", port=445),                      # no user on this one
            flow(src="web", dst="db1", port=8443, user="CORP\\carol"),  # not a management port
        ], origin=DataOrigin.INGEST, now=NOW)
    return c


def test_three_rankings_from_management_port_traffic(ctx):
    d = lateral_defaults.lateral_defaults(ctx, start=START, end=END, now=NOW)
    users = [(r.name, r.destinations) for r in d.users]
    assert users == [("corp\\alice", 2), ("corp\\bob", 1)]  # by distinct destination hosts; system accounts left out
    assert [(r.name, r.destinations) for r in d.system_accounts] == [("root", 1)]
    assert d.processes == []
    assert (d.flows, d.with_user, d.with_process) == (5, 4, 0)  # flow records; 8443 is not counted
    assert d.capped == {}


def test_the_segments_are_the_domain_defaults(ctx, monkeypatch):
    """Gate (spec §6.5.7): the page and the report read lateral_default_segments, never a copy of them."""
    from illumio_ops.domain import segment
    seen = []
    real = segment.lateral_default_segments

    def spy(ports, **kw):
        seen.append(kw)
        return real(ports, **kw)
    monkeypatch.setattr(lateral_defaults, "lateral_default_segments", spy)
    lateral_defaults.lateral_defaults(ctx, start=START, end=END, now=NOW)
    assert seen == [{"start": START, "end": END}]


def test_a_read_that_stopped_at_its_limit_is_said(ctx, monkeypatch):
    """With more initiators than a ranking reads, the rest are neither counted nor checked: the result says where
    each read stopped, so the page never states "no system account" about accounts it did not look at. The system
    accounts are looked for among SYSTEM_SCAN accounts, not the ranking's 50."""
    from illumio_ops.services.analysis.segments import SegmentResult
    asked = []

    def fake(c, seg, **kw):
        asked.append(seg.limit)
        return SegmentResult.model_construct(ranking=[], limit_hit=True)
    monkeypatch.setattr(lateral_defaults, "run_segment", fake)
    d = lateral_defaults.lateral_defaults(ctx, start=START, end=END, now=NOW)
    assert asked == [50, 50, lateral_defaults.SYSTEM_SCAN]
    assert d.capped == {"users": 50, "processes": 50, "system_accounts": lateral_defaults.SYSTEM_SCAN}
