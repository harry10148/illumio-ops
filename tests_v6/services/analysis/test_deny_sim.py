"""simulate_deny: what a proposed deny rule would block in the collected traffic, and what it does to the
reach of critical assets. Never asks the PCE."""
from datetime import timedelta

import pytest

from illumio_ops.domain.deny import DenyProposal, cut_to_proposal
from illumio_ops.domain.filter import EndpointFilter, LabelCond, PortProto
from illumio_ops.domain.flows import normalize_flow
from illumio_ops.domain.values import DataOrigin
from illumio_ops.services.analysis.deny_sim import simulate_deny
from illumio_ops.services.analysis.exposure import run_exposure
from illumio_ops.store.flowdb import workloads
from illumio_ops.store.flowdb.flows import upsert_flows
from illumio_ops.store.flowdb.labels import label_set_id
from tests_v6.services.collect.conftest import NOW, configured_ctx, raw_flow


def rec(i, *, src, dst, port=3389, decision="potentially_blocked", env="Dev", conns=1, dst_href=None):
    last = NOW - timedelta(days=1, minutes=i)
    raw = raw_flow(i, last - timedelta(minutes=5), last, port=port)
    raw["src"]["ip"] = f"10.0.1.{src}"
    raw["src"]["workload"].update({"href": f"/orgs/1/workloads/s{src}", "labels": [{"key": "env", "value": env}]})
    raw["dst"]["ip"] = f"10.0.2.{dst}"
    raw["dst"]["workload"].update({"href": dst_href or f"/orgs/1/workloads/d{dst}"})
    raw["policy_decision"] = decision
    raw["num_connections"] = conns
    return normalize_flow(raw)


@pytest.fixture
def ctx(tmp_path):
    c = configured_ctx(tmp_path)
    c.settings.update(c.settings.current().revision,
                      lambda d: d["lateral"].update({"critical_assets": [{"key": "app", "value": "Finance"}]}))
    with c.flows().connect() as conn:
        fin = label_set_id(conn, (("app", "Finance"),))
        workloads.replace_inventory(conn, [workloads.WorkloadRow(
            href="/orgs/1/workloads/d9", hostname="fin-db", name=None, managed=1, enforcement_mode="selective",
            visibility_level=None, os_id=None, ven_version=None, ven_href=None, label_set=fin, online=1,
            risk_exposure=None, risk_percent=None, risk_updated_at=None, fetched_at="x")])
        upsert_flows(conn, [
            rec(1, src=1, dst=9, conns=3), rec(2, src=2, dst=9, conns=2), rec(3, src=3, dst=9, env="Prod"),
            rec(4, src=1, dst=9, port=22), rec(5, src=4, dst=9, decision="blocked"),
            rec(6, src=5, dst=8, dst_href="/orgs/1/workloads/s8"), rec(7, src=8, dst=9, port=445)], origin=DataOrigin.INGEST, now=NOW)
    return c


TO_FIN_RDP = DenyProposal(src=EndpointFilter(), dst=EndpointFilter(hrefs=("/orgs/1/workloads/d9",)),
                          ports=(PortProto(port=3389, proto=6),))


def test_simulation_counts_blocked_connections_and_sources(ctx):
    sim = simulate_deny(ctx, TO_FIN_RDP, now=NOW)
    assert (sim.blocked_flows, sim.blocked_connections) == (3, 6)
    assert {r.keys[0]: r.value for r in sim.sources} == {"/orgs/1/workloads/s1": 3, "/orgs/1/workloads/s2": 2,
                                                         "/orgs/1/workloads/s3": 1}
    assert [r.keys[0] for r in sim.destinations] == ["/orgs/1/workloads/d9"]
    assert len(sim.sample) == 3 and sim.limit_hit is False
    assert sim.window == (NOW - timedelta(days=30), NOW) and sim.coverage.source == "store"


def test_already_blocked_flows_not_counted(ctx):
    sim = simulate_deny(ctx, TO_FIN_RDP, now=NOW)
    assert "/orgs/1/workloads/s4" not in {r.keys[0] for r in sim.sources}


def test_label_proposal_matches_by_host_labels(ctx):
    dev_only = DenyProposal(src=EndpointFilter(labels=(LabelCond(key="env", values=("Dev",)),)),
                            dst=EndpointFilter(hrefs=("/orgs/1/workloads/d9",)), ports=(PortProto(port=3389, proto=6),))
    sim = simulate_deny(ctx, dev_only, now=NOW)
    assert {r.keys[0] for r in sim.sources} == {"/orgs/1/workloads/s1", "/orgs/1/workloads/s2"}


def test_all_services_proposal(ctx):
    sim = simulate_deny(ctx, DenyProposal(src=EndpointFilter(hrefs=("/orgs/1/workloads/s1",)),
                                          dst=EndpointFilter()), now=NOW)
    assert sim.blocked_flows == 2  # RDP and SSH from s1


def test_reach_change_for_critical_asset(ctx):
    sim = simulate_deny(ctx, TO_FIN_RDP, now=NOW)
    [change] = sim.reach_change
    # before: s1, s2, s3 (RDP), s1 (SSH), s8 (SMB) and s5 via s8 → 5 sources; RDP denied: s1 (SSH), s8, s5 stay
    assert (change.asset, change.before, change.after) == ("/orgs/1/workloads/d9", 5, 3)


def test_cut_converts_to_proposal_and_reduces_reach(ctx):
    result = run_exposure(ctx, now=NOW)
    [asset] = result.assets
    best = asset.cuts[0]
    sim = simulate_deny(ctx, cut_to_proposal(best, {}), now=NOW)
    [change] = sim.reach_change
    assert change.before == best.before and change.after == best.after


def test_simulation_never_calls_pce(ctx, monkeypatch):
    def no_pce(*a, **kw):
        raise AssertionError("simulate_deny must not ask the PCE")
    monkeypatch.setattr(ctx, "pce_factory", no_pce)
    from illumio_ops.services import flowsource
    monkeypatch.setattr(flowsource, "run_traffic_query", no_pce)
    assert simulate_deny(ctx, TO_FIN_RDP, now=NOW).blocked_flows == 3


# ── P6c ───────────────────────────────────────────────────────────────────────

def test_all_empty_proposal_refused():
    """No source, no destination, no service: a rule that blocks everything is not a suggestion to try."""
    with pytest.raises(ValueError):
        DenyProposal(src=EndpointFilter(), dst=EndpointFilter())


def test_given_edges_used(ctx, monkeypatch):
    """Lightweight mode: the graph is the edges pulled for the page, not the store's baseline."""
    from illumio_ops.domain.exposure import EdgeIn
    from illumio_ops.domain.values import EdgeState
    from illumio_ops.services.analysis import exposure

    def no_baseline(*a, **kw):
        raise AssertionError("baseline_edges read although the edges were given")
    monkeypatch.setattr(exposure, "baseline_edges", no_baseline)
    edges = [EdgeIn("/orgs/1/workloads/s1", "/orgs/1/workloads/d9", 3389, 6, EdgeState.POTENTIALLY_BLOCKED),
             EdgeIn("/orgs/1/workloads/s2", "/orgs/1/workloads/d9", 22, 6, EdgeState.ALLOWED)]
    window = (NOW - timedelta(days=7), NOW)
    sim = simulate_deny(ctx, TO_FIN_RDP, now=NOW, window=window, edges=edges)
    [change] = sim.reach_change
    assert (change.before, change.after) == (2, 1) and sim.window == window


def test_every_cut_simulates_to_its_own_numbers(ctx):
    """Lab acceptance 2026-10-30: a host cut said 6 → 1 and its simulation 6 → 2. What the page suggests and what the
    simulation of that suggestion says must be the same numbers."""
    from illumio_ops.domain.exposure import build_graph, suggest_cuts
    from illumio_ops.services.analysis.context import load_lateral_context
    from illumio_ops.services.analysis.exposure import graph_edges
    lc = load_lateral_context(ctx, now=NOW)
    g = build_graph(graph_edges(ctx, lc, since=NOW - timedelta(days=30)), enforced=False)
    cuts = suggest_cuts(g, "/orgs/1/workloads/d9", 3, top=10)
    assert {c.kind for c in cuts} == {"edge", "node"}
    for cut in cuts:
        [change] = simulate_deny(ctx, cut_to_proposal(cut, {}), now=NOW).reach_change
        assert (change.before, change.after) == (cut.before, cut.after), cut
