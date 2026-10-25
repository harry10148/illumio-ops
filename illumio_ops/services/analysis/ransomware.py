"""Ransomware protection breakdown (spec §6.5.6): per host on demand (with the allow rules that expose a
service, from rule search), and every host in the hourly step with the traffic overlay lists."""
from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, ConfigDict

from illumio_ops.domain.identity import endpoint_key
from illumio_ops.domain.policy import RuleRef
from illumio_ops.domain.ransomware import (
    HostBreakdown,
    ServiceContribution,
    host_breakdown,
)
from illumio_ops.domain.values import CapabilityState, RansomwareTrafficClass
from illumio_ops.services.analysis.explain import explain_service
from illumio_ops.services.context import AppContext
from illumio_ops.services.flowsource import service_traffic
from illumio_ops.store.flowdb import analysis, capabilities, ransomware, workloads

KIND = "ransomware"
OVERLAY_DAYS = 30  # "近 30 天有無流量" (spec §6.5.6), bounded by what the baseline keeps
ALLOWING = frozenset({"allowed", "potentially_blocked"})  # an active decision that lets sources in


class HostRansomware(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    breakdown: HostBreakdown
    allow_rules: dict[str, list[RuleRef]]  # "port/proto" -> the allow rules exposing that service


def _breakdowns(ctx: AppContext, now: datetime, only: str | None = None) -> list[HostBreakdown]:
    fdb = ctx.flows()
    days = min(OVERLAY_DAYS, ctx.settings.current().collection.retention.baseline_days)
    with fdb.connect() as conn:
        inventory = {w.href: w for w in workloads.all_workloads(conn)}
        services = ransomware.services_by_host(conn)
    if only is not None:
        services = {only: services.get(only, [])}
    targets = {(endpoint_key(href, ""), int(s["port"]), int(s["proto"])) for href, rows in services.items() for s in rows}
    traffic = service_traffic(ctx, targets, since=now - timedelta(days=days), now=now)
    out = []
    for href, rows in sorted(services.items()):
        wl = inventory.get(href)
        per_service = {(port, proto): t.sources for (dst, port, proto), t in traffic.items() if dst == endpoint_key(href, "")}
        out.append(host_breakdown(href, wl.hostname if wl else None, wl.enforcement_mode if wl else None,
                                  wl.risk_percent if wl else None, wl.risk_exposure if wl else None,
                                  [dict(r) for r in rows], per_service))
    return out


def host_ransomware(ctx: AppContext, href: str, *, now: datetime | None = None,
                    explain_allows: bool = True) -> HostRansomware:
    at = (now or datetime.now(UTC)).astimezone(UTC)
    [breakdown] = _breakdowns(ctx, at, only=href)
    allow_rules: dict[str, list[RuleRef]] = {}
    if explain_allows:
        for s in breakdown.services:
            if (s.active_policy or "").lower() in ALLOWING:  # only services an allow rule can be behind
                allow_rules[f"{s.port}/{s.proto}"] = explain_service(ctx, href, s.port, s.proto).allow
    return HostRansomware(breakdown=breakdown, allow_rules=allow_rules)


def _row(b: HostBreakdown, s: ServiceContribution) -> dict[str, object]:
    return {"host": b.href, "hostname": b.hostname, "name": s.name, "port": s.port, "proto": s.proto,
            "severity": s.severity, "weight": s.weight, "recent_sources": s.recent_sources}


def ransomware_overlay(ctx: AppContext, now: datetime) -> None:
    """The hourly step: every host's breakdown and the three action lists, ordered by the service's own
    weight and traffic — never by the PCE percent (a contradicted number is not used for sorting)."""
    fdb = ctx.flows()
    gen = fdb.generation
    with fdb.connect() as conn:
        cap = capabilities.all(conn).get("ransomware_risk")
    if cap is not None and cap.state == CapabilityState.UNSUPPORTED:
        with fdb.writing(gen) as conn:
            analysis.write_result(conn, KIND, params={}, result={"unsupported": True}, at=now)
        return
    hosts = _breakdowns(ctx, now)
    found: dict[RansomwareTrafficClass, list[tuple[HostBreakdown, ServiceContribution]]] = {
        c: [] for c in RansomwareTrafficClass}
    for b in hosts:
        for svc in b.services:
            found[svc.traffic].append((b, svc))
    lists = {c: [_row(b, svc) for b, svc in sorted(pairs, key=lambda p: (-(p[1].weight or 0), -(p[1].recent_sources or 0),
                                                                           p[0].href, p[1].port))]
             for c, pairs in found.items()}
    result = {
        "unsupported": False, "contradictions": sum(b.contradiction for b in hosts),
        "priority": lists[RansomwareTrafficClass.PRIORITY], "safe_to_block": lists[RansomwareTrafficClass.SAFE_TO_BLOCK],
        "suspicious": lists[RansomwareTrafficClass.SUSPICIOUS],
        "hosts": [{**{k: v for k, v in asdict(b).items() if k != "services"},
                   "services": [{**asdict(s), "traffic": s.traffic.value} for s in b.services]} for b in hosts],
    }
    with fdb.writing(gen) as conn:
        analysis.write_result(conn, KIND, params={"overlay_days": OVERLAY_DAYS}, result=result, at=now)
