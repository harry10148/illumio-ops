"""Ransomware protection as the PCE judges it (spec §6.5.6), broken down per service, with the vendor's own
number reported as it is and contradictions marked (anti-goal 9).

Weights per severity are the Visualization Guide's (spec §6.6 F6). The exact per-service coverage (blocked
share of the address space) is not in the API, only protection_state, so a service counts as 1.0 when
protected and 0.0 when not: the computed percent is an approximation and says so.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from illumio_ops.domain.values import RansomwareTrafficClass

SEVERITY_WEIGHT: Mapping[str, int] = {"critical": 40, "high": 30, "medium": 20, "low": 10}
# PCE percent and the breakdown differ by more than this many points. Wide on purpose: the breakdown cannot
# see partial coverage (allow rules beside a deny), so small differences are the approximation, not the PCE
# contradicting itself; lab's case is 100 against 0 (spec §6.6 F5).
CONTRADICTION_POINTS = 25.0
UNENFORCED_MODES = frozenset({"visibility_only", "idle"})


def service_coverage(protection_state: str | None) -> float | None:
    if not protection_state:
        return None
    state = protection_state.lower()
    if state.startswith("protected"):
        return 1.0
    if state == "unprotected":
        return 0.0
    return None


def classify_traffic(protection_state: str | None, port_status: str | None,
                     recent_sources: int | None) -> RansomwareTrafficClass:
    """Unprotected and listening: in use (priority) or idle (safe to block); unprotected and not listening
    yet connected to: suspicious. Without traffic data nothing is guessed."""
    if service_coverage(protection_state) == 1.0:
        return RansomwareTrafficClass.PROTECTED
    if service_coverage(protection_state) != 0.0 or recent_sources is None:
        return RansomwareTrafficClass.UNKNOWN
    listening = (port_status or "").lower() == "listening"
    if listening:
        return RansomwareTrafficClass.PRIORITY if recent_sources > 0 else RansomwareTrafficClass.SAFE_TO_BLOCK
    return RansomwareTrafficClass.SUSPICIOUS if recent_sources > 0 else RansomwareTrafficClass.UNKNOWN


@dataclass(frozen=True)
class ServiceContribution:
    name: str
    port: int
    proto: int
    severity: str | None
    category: str | None
    protection_state: str | None
    port_status: str | None
    active_policy: str | None
    weight: int | None
    coverage: float | None
    contribution: float | None
    traffic: RansomwareTrafficClass
    recent_sources: int | None


@dataclass(frozen=True)
class HostBreakdown:
    href: str
    hostname: str | None
    enforcement_mode: str | None
    pce_percent: float | None   # the PCE's ransomware_protection_percent, as given (0-100)
    pce_exposure: str | None
    computed_percent: float | None
    approximate: bool
    contradiction: bool
    services: tuple[ServiceContribution, ...]


def host_breakdown(href: str, hostname: str | None, enforcement_mode: str | None, pce_percent: float | None,
                   pce_exposure: str | None, services: Sequence[Mapping[str, Any]],
                   traffic: Mapping[tuple[int, int], int | None]) -> HostBreakdown:
    """`traffic`: (port, proto) -> distinct recent sources (absent = traffic not known)."""
    rows = []
    mode = (enforcement_mode or "").lower()
    for s in services:
        port, proto = int(s.get("port", -1)), int(s.get("proto", 0))
        weight = SEVERITY_WEIGHT.get(str(s.get("severity") or "").lower())
        # The vendor counts only enforced hosts (user 2026-10-29, Visualization Guide): Full protects every risky
        # service rule or not, Visibility Only and Idle protect none; Selective goes by each service's state.
        coverage = (1.0 if mode == "full" else 0.0 if mode in UNENFORCED_MODES
                    else service_coverage(s.get("protection_state")))
        sources = traffic.get((port, proto))
        rows.append(ServiceContribution(
            name=str(s.get("name") or ""), port=port, proto=proto, severity=s.get("severity"),
            category=s.get("category"), protection_state=s.get("protection_state"), port_status=s.get("port_status"),
            active_policy=s.get("active_policy"), weight=weight, coverage=coverage,
            contribution=weight * coverage if weight is not None and coverage is not None else None,
            traffic=classify_traffic(s.get("protection_state"), s.get("port_status"), sources),
            recent_sources=sources))
    known = [r for r in rows if r.weight is not None and r.coverage is not None]
    total = sum(r.weight for r in known if r.weight is not None)
    computed = sum(r.contribution for r in known if r.contribution is not None) / total * 100 if total else None
    contradiction = (pce_percent is not None and computed is not None
                     and abs(float(pce_percent) - computed) > CONTRADICTION_POINTS)
    return HostBreakdown(href=href, hostname=hostname, enforcement_mode=enforcement_mode, pce_percent=pce_percent,
                         pce_exposure=pce_exposure, computed_percent=computed, approximate=True,
                         contradiction=contradiction, services=tuple(rows))
