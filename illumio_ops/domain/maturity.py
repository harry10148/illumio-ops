"""The segmentation maturity score of the security risk report (v6 definition, P5b-1 Task 4): five parts, each
0..1, weighted 40/25/15/10/10. A part without data is left out and the others rescaled to 100, so a missing input
never reads as 0. 5.x counted selective enforcement as full (its fallback path); here it is half."""
from __future__ import annotations

from dataclasses import dataclass

WEIGHTS = {"enforcement": 40, "policy": 25, "lateral": 15, "managed": 10, "ransomware": 10}
LATERAL_CAP = 0.30  # management-port connections not blocked: at 30% of all connections the part is 0
MANAGED_CAP = 0.50  # connections from unmanaged sources: at 50% the part is 0
GRADES = ((85, "A"), (70, "B"), (55, "C"), (40, "D"))


@dataclass(frozen=True)
class MaturityInputs:
    hosts_managed: int
    hosts_full: int
    hosts_selective: int
    connections: int
    allowed_connections: int
    admin_open_connections: int  # on management ports, decision not blocked
    unmanaged_source_connections: int
    ransomware_services: int | None  # critical/high services the PCE rated; None: no ransomware data
    ransomware_protected: int | None


@dataclass(frozen=True)
class Maturity:
    score: float | None
    grade: str | None
    parts: dict[str, float | None]


def grade(score: float) -> str:
    return next((g for floor, g in GRADES if score >= floor), "F")


def maturity(m: MaturityInputs) -> Maturity:
    share = (lambda n: n / m.connections) if m.connections else None
    parts: dict[str, float | None] = {
        "enforcement": (m.hosts_full + 0.5 * m.hosts_selective) / m.hosts_managed if m.hosts_managed else None,
        "policy": share(m.allowed_connections) if share else None,
        "lateral": 1 - min(share(m.admin_open_connections), LATERAL_CAP) / LATERAL_CAP if share else None,
        "managed": 1 - min(share(m.unmanaged_source_connections), MANAGED_CAP) / MANAGED_CAP if share else None,
        "ransomware": (m.ransomware_protected or 0) / m.ransomware_services if m.ransomware_services else None,
    }
    weight = sum(WEIGHTS[k] for k, v in parts.items() if v is not None)
    if not weight:
        return Maturity(score=None, grade=None, parts=parts)
    score = 100 * sum(WEIGHTS[k] * v for k, v in parts.items() if v is not None) / weight
    return Maturity(score=score, grade=grade(score), parts=parts)
