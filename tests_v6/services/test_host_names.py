"""How a host key is shown (hosts.display_names and the reports' rankings): never an href — the inventory's name,
else what the flows called it, else an address it was seen with, else words that say what it is (lab 2026-10-31:
Kubernetes Workloads, which the inventory does not hold, showed as hrefs in the reports' rankings)."""
from datetime import UTC, datetime

import pytest

from illumio_ops.domain.report import Column
from illumio_ops.domain.segment import GroupBy
from illumio_ops.domain.values import (
    DataOrigin,
    Language,
    ReportType,
    SegmentDimension,
    SegmentMetric,
)
from illumio_ops.services import hosts
from illumio_ops.services.reports import flowsections
from illumio_ops.services.reports.registry import BuildInput, ReportParams
from illumio_ops.store.flowdb.flows import upsert_flows
from tests_v6.services.collect.conftest import configured_ctx
from tests_v6.services.reports.test_findings import flow

NOW = datetime(2026, 10, 27, 1, tzinfo=UTC)
START, END = datetime(2026, 10, 20, tzinfo=UTC), datetime(2026, 10, 27, tzinfo=UTC)
K8S = "/orgs/1/kubernetes_workloads/698dd122-7dbd-4d8f-906c-3b04dd98caaf"
GONE = "/orgs/1/workloads/2c10dcd1-3bf6-4a7c-b441-14f549a8f1eb"


@pytest.fixture
def ctx(tmp_path):
    c = configured_ctx(tmp_path, mode="full")
    with c.flows().connect() as conn:
        upsert_flows(conn, [flow(src="a", dst="k8s"), flow(src="a", dst="k8s")], origin=DataOrigin.INGEST, now=NOW)
        # flows ingested before the name was read: the PCE's Kubernetes Workload, no hostname
        conn.execute("UPDATE flows SET dst_key = ?, dst_href = ?, dst_hostname = NULL WHERE dst_key = ?",
                     (K8S, K8S, "/orgs/1/workloads/k8s"))
        conn.commit()
    return c


def _ip(ctx, key):
    with ctx.flows().connect() as conn:
        return conn.execute("SELECT dst_ip FROM flows WHERE dst_key = ?", (key,)).fetchone()[0]


def test_kubernetes_workload_shown_by_address(ctx):
    assert hosts.display_names(ctx, {K8S})[K8S] == _ip(ctx, K8S)


def test_kubernetes_workload_shown_by_the_name_the_flows_carry(ctx):
    with ctx.flows().connect() as conn:
        conn.execute("UPDATE flows SET dst_hostname = 'coredns' WHERE dst_key = ?", (K8S,))
        conn.commit()
    assert hosts.display_names(ctx, {K8S})[K8S] == "coredns"


def test_workload_known_nowhere_said_in_words(ctx):
    """P6c deferred: a workload with no name in the inventory and no address in the flows kept its href."""
    got = hosts.display_names(ctx, {GONE, "/orgs/1/container_workloads/0f1e2d3c4b5a"}, lang=Language.EN)
    assert got[GONE] == "Removed workload …a8f1eb"
    assert got["/orgs/1/container_workloads/0f1e2d3c4b5a"] == "Container workload …3c4b5a"
    zh = hosts.display_names(ctx, {GONE}, lang=Language.ZH_TW)
    assert not zh[GONE].startswith("/orgs/")


def test_report_ranking_never_shows_a_container_href(ctx):
    inp = BuildInput(ctx=ctx, params=ReportParams(report_type=ReportType.TRAFFIC), start=START, end=END,
                     lang=Language.EN, tz=UTC, now=NOW, pce_label="pce")
    table = flowsections.ranking(inp, title="t", group_by=(GroupBy(dimension=SegmentDimension.DST_HOST),),
                                 metric=SegmentMetric.FLOWS, columns=(Column(key="h", label="h"),
                                                                      Column(key="n", label="n", kind="number")))
    shown = {r[0] for r in table.rows}
    assert _ip(ctx, K8S) in shown
    assert not any(str(s).startswith("/orgs/") for s in shown)


def test_one_lookup_per_unnamed_host(ctx, monkeypatch):
    """Final review (Codex): the name was looked up before the address, so a host the flows never named cost two
    unindexed scans of the flows table more than before (500k rows, 20 hosts: 0.0001 s → 2.4 s)."""
    from illumio_ops.services.flowsource import host_addresses
    statements: list[str] = []
    real = ctx.flows().connect

    def traced():
        conn = real()
        conn.set_trace_callback(statements.append)
        return conn
    monkeypatch.setattr(ctx.flows(), "connect", traced)
    assert host_addresses(ctx, {K8S}) == {K8S: _ip_raw(real, K8S)}
    assert len([s for s in statements if s.lstrip().upper().startswith("SELECT") and "FROM flows" in s]) == 1


def _ip_raw(connect, key):
    with connect() as conn:
        return conn.execute("SELECT dst_ip FROM flows WHERE dst_key = ?", (key,)).fetchone()[0]


def test_profile_of_an_unnamed_host_says_so(ctx):
    """Final review (Codex): the host page asks the traffic for a name when the store had none; the words the
    profile now gives instead of the href must not stop it asking."""
    p = hosts.profile(ctx, GONE, now=NOW)
    assert not p.named and not p.name.startswith("/orgs/")
