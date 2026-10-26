"""The exposure graph step: built from the connection baseline over the observation period, stored with
the day's lateral snapshot (spec §6.4)."""
from __future__ import annotations

from datetime import datetime, timedelta

from illumio_ops.domain import exposure as domain_exposure
from illumio_ops.domain.exposure import EdgeIn, ExposureResult, Foothold, edge_state
from illumio_ops.domain.identity import endpoint_key
from illumio_ops.domain.lateral import GRAPH_CLASSES
from illumio_ops.services.analysis.context import load_lateral_context
from illumio_ops.services.context import AppContext
from illumio_ops.services.flowsource import baseline_edges
from illumio_ops.settings.schema import LateralSettings
from illumio_ops.store.flowdb import analysis, ransomware
from illumio_ops.store.flowdb.db import db_day

KIND = "exposure"
compute_exposure = domain_exposure.compute_exposure  # module attribute: tests stand in for it


def run_exposure(ctx: AppContext, *, now: datetime) -> ExposureResult | None:
    """None when traffic is not collected (the run status says collection_off)."""
    lc = load_lateral_context(ctx, now=now)
    fdb = ctx.flows()
    lat: LateralSettings = lc.settings
    if not lc.collected:
        with fdb.writing(lc.generation) as conn:
            analysis.set_run(conn, KIND, status={"state": "collection_off"})
        return None
    # The graph cannot look further back than the baseline keeps (P3 Task 1 ruling).
    days = min(lat.observation_days, lc.baseline_required)
    since = now - timedelta(days=days)
    found = baseline_edges(ctx, lc.admin_ports, since=since, classes=GRAPH_CLASSES)
    edges = []
    for e in found.edges:
        state = edge_state(e.decision)
        if state is not None:
            edges.append(EdgeIn(e.src_key, e.dst_key, e.port, e.proto, state))
    with fdb.connect() as conn:
        landing = ransomware.unprotected_listening(conn)
    footholds = [Foothold(host=endpoint_key(href, ""), name=name, port=port, proto=proto, severity=sev)
                 for href, name, port, proto, sev in landing]
    env_key = lat.environment_label_key
    result = compute_exposure(
        edges, lc.hosts, footholds, hops=lat.graph_hops,
        critical=frozenset(k for k, h in lc.hosts.items() if h.critical),
        env_of={k: h.labels.get(env_key) for k, h in lc.hosts.items()},
        computed_at=now, observation_from=since, observation_to=now)
    metrics = {
        "nodes": result.nodes, "edges_now": result.edges_now, "edges_enforced": result.edges_enforced,
        "unknown_edges": result.unknown_edges, "pivots_now": sum(h.pivot_now for h in result.hosts),
        "assets_reachable_now": sum(1 for a in result.assets if a.sources_now),
        "assets_reachable_enforced": sum(1 for a in result.assets if a.sources_enforced),
        "cross_env_edges": result.cross_env_total, "max_reach_now": max((h.reach_now for h in result.hosts), default=0),
    }
    with fdb.writing(lc.generation) as conn:
        analysis.write_result(conn, KIND, params={"hops": lat.graph_hops, "observation_days": days,
                                                  "observation_days_setting": lat.observation_days},
                              result=result.model_dump(mode="json"), at=now)
        analysis.write_lateral_snapshot(conn, db_day(now), metrics)
        analysis.set_run(conn, KIND, status={"state": "ok", "baseline_days": round(lc.baseline_days, 1)})
    return result
