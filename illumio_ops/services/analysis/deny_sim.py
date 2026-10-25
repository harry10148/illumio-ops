"""Deny rule simulation (spec §6.5.1 防堵, read-only): what a proposed deny rule would block in the traffic
collected over the observation period, and how it changes who can reach each critical asset. Reads the
store only; never writes to or asks the PCE."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pydantic import BaseModel

from illumio_ops.domain.deny import DenyProposal, apply_deny, proposal_filter
from illumio_ops.domain.exposure import EdgeIn, build_graph, edge_state, paths_to
from illumio_ops.domain.lateral import HostInfo
from illumio_ops.domain.segment import FlowSegment, GroupBy
from illumio_ops.domain.values import SegmentDimension, SegmentMetric, SegmentView
from illumio_ops.services.analysis.context import host_for, load_lateral_context
from illumio_ops.services.context import AppContext
from illumio_ops.services.coverage import Coverage
from illumio_ops.services.flowsource import (
    AggRow,
    FieldCoverage,
    FlowRow,
    aggregate_flows,
    baseline_edges,
    query_flows,
)

TOP = 50


class AssetReachChange(BaseModel):
    asset: str
    before: int
    after: int


class DenySimulation(BaseModel):
    window: tuple[datetime, datetime]
    blocked_connections: int
    blocked_flows: int
    sources: list[AggRow]          # by source host, the TOP largest
    destinations: list[AggRow]     # by destination host, the TOP largest
    sample: list[FlowRow]
    limit_hit: bool
    reach_change: list[AssetReachChange]
    coverage: Coverage
    field_coverage: FieldCoverage


def simulate_deny(ctx: AppContext, proposal: DenyProposal, *, now: datetime | None = None,
                  sample: int = 200) -> DenySimulation:
    at = (now or datetime.now(UTC)).astimezone(UTC)
    lc = load_lateral_context(ctx, now=at)
    start = at - timedelta(days=min(lc.settings.observation_days, lc.baseline_required))
    spec = proposal_filter(proposal, start=start, end=at)

    def ranking(dim: SegmentDimension, metric: SegmentMetric, limit: int = TOP) -> FlowSegment:
        return FlowSegment(filter=spec, view=SegmentView.RANKING, group_by=(GroupBy(dimension=dim),),
                           metric=metric, limit=limit)

    by_src = aggregate_flows(ctx, ranking(SegmentDimension.SRC_HOST, SegmentMetric.CONNECTIONS), now=at)
    by_dst = aggregate_flows(ctx, ranking(SegmentDimension.DST_HOST, SegmentMetric.CONNECTIONS), now=at)
    flows = aggregate_flows(ctx, ranking(SegmentDimension.DECISION, SegmentMetric.FLOWS), now=at)
    conns = aggregate_flows(ctx, ranking(SegmentDimension.DECISION, SegmentMetric.CONNECTIONS), now=at)
    detail = query_flows(ctx, spec, limit=sample, order="connections_desc", now=at)

    edges = []
    for e in baseline_edges(ctx, lc.admin_ports, since=start).edges:
        state = edge_state(e.decision)
        if state is not None:
            edges.append(EdgeIn(e.src_key, e.dst_key, e.port, e.proto, state))

    def host(key: str) -> HostInfo:
        return host_for(lc, key, ip=key[3:] if key.startswith("ip:") else "", hostname=None)

    before, after = build_graph(edges, enforced=False), build_graph(apply_deny(edges, proposal, host), enforced=False)
    change = [AssetReachChange(asset=k, before=len(paths_to(before, k, lc.settings.graph_hops)),
                               after=len(paths_to(after, k, lc.settings.graph_hops)))
              for k in sorted(k for k, h in lc.hosts.items() if h.critical)]
    return DenySimulation(
        window=(start, at), blocked_flows=sum(r.value for r in flows.rows),
        blocked_connections=sum(r.value for r in conns.rows), sources=by_src.rows, destinations=by_dst.rows,
        sample=detail.rows, limit_hit=detail.limit_hit or by_src.limit_hit or by_dst.limit_hit,
        reach_change=change, coverage=by_src.coverage, field_coverage=by_src.field_coverage)
