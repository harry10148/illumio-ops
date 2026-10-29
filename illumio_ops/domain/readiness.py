"""Whether one app is ready for enforcement (P5b-2 Task 5): 5.x readiness's five factors and weights, over the app's
inbound connections (enforcement blocks what comes in) and its own hosts. A connection without a reported decision
says nothing about policy, so policy and staged are shares of the decided ones. A factor without data is left out and the
others rescaled; grades are the maturity score's (A ≥ 85, B ≥ 70, C ≥ 55, D ≥ 40), one scale for both reports."""
from __future__ import annotations

from dataclasses import dataclass

from illumio_ops.domain.maturity import grade

WEIGHTS = {"policy": 35, "ringfence": 20, "enforcement": 20, "staged": 15, "remote": 10}


@dataclass(frozen=True)
class ReadinessInputs:
    connections: int          # into the app's managed hosts
    decided: int              # of them with a reported decision: policy and staged are shares of these
    allowed: int
    same_app: int             # from the app itself
    potentially_blocked: int
    remote: int               # on remote-execution ports
    remote_allowed: int
    hosts: int                # the app's managed hosts in the inventory
    full: int
    selective: int


@dataclass(frozen=True)
class Readiness:
    score: float | None
    grade: str | None
    parts: dict[str, float | None]
    blocking: str | None  # the factor that costs the most points


def score_with(parts: dict[str, float | None], factor: str) -> float | None:
    """The score with one factor at full marks: what fixing the factor that costs most would give."""
    known = {k: v for k, v in parts.items() if v is not None}
    if factor not in known:
        return None
    known[factor] = 1.0
    return 100 * sum(WEIGHTS[k] * v for k, v in known.items()) / sum(WEIGHTS[k] for k in known)


def readiness(i: ReadinessInputs) -> Readiness:
    def share(n: float, d: int) -> float | None:
        return n / d if d else None
    staged = share(i.potentially_blocked, i.decided)
    parts: dict[str, float | None] = {
        "policy": share(i.allowed, i.decided), "ringfence": share(i.same_app, i.connections),
        "enforcement": share(i.full + 0.5 * i.selective, i.hosts) if i.hosts else None,
        "staged": None if staged is None else 1 - staged, "remote": share(i.remote_allowed, i.remote)}
    known = {k: v for k, v in parts.items() if v is not None}
    if not known:
        return Readiness(score=None, grade=None, parts=parts, blocking=None)
    score = 100 * sum(WEIGHTS[k] * v for k, v in known.items()) / sum(WEIGHTS[k] for k in known)
    blocking = max(known, key=lambda k: WEIGHTS[k] * (1 - known[k]))
    return Readiness(score=score, grade=grade(score), parts=parts,
                     blocking=blocking if WEIGHTS[blocking] * (1 - known[blocking]) > 0 else None)
