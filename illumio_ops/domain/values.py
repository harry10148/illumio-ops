"""The single registry of value domains. Values are strings, never integer codes.

5.x encoded policy decisions six different ways (ints with conflicting
sentinels among them); v6 keeps one string vocabulary here and exports it to
the frontend through the API contracts.
"""
from __future__ import annotations

from enum import StrEnum


class PolicyDecision(StrEnum):
    ALLOWED = "allowed"
    POTENTIALLY_BLOCKED = "potentially_blocked"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class RuleAction(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    OVERRIDE_DENY = "override_deny"


class AlertRuleType(StrEnum):
    EVENT = "event"
    TRAFFIC = "traffic"
    BANDWIDTH = "bandwidth"
    VOLUME = "volume"
    SYSTEM = "system"


class DeploymentType(StrEnum):
    ON_PREM = "on_prem"
    SAAS = "saas"


class Language(StrEnum):
    EN = "en"
    ZH_TW = "zh_TW"


class ProbeName(StrEnum):
    NOOP = "noop"
    HEALTH = "health"
    NODE_AVAILABLE = "node_available"


# Draft policy decision is an OPEN domain: the PCE adds values (boundary and
# override-deny variants arrived after the base four), and neither the REST
# API guide nor the schema lists them all. Unknown values pass through
# unchanged so a PCE upgrade never makes data disappear. Known values: the
# four base decisions plus every variant observed in 5.x code paths.
KNOWN_DRAFT_POLICY_DECISIONS: frozenset[str] = frozenset({
    "allowed",
    "potentially_blocked",
    "blocked",
    "unknown",
    "blocked_by_boundary",
    "potentially_blocked_by_boundary",
    "blocked_by_override_deny",
    "potentially_blocked_by_override_deny",
    "allowed_across_boundary",
})


def parse_draft_policy_decision(raw: str) -> str:
    """Normalise case only; never reject a value the PCE sends."""
    return raw.strip().lower()


_ENUMS: tuple[type[StrEnum], ...] = (
    PolicyDecision, RuleAction, AlertRuleType, DeploymentType, Language, ProbeName,
)


def export_value_domains() -> dict[str, list[str]]:
    """Every value domain by class name, values sorted — the frontend's copy of this module."""
    out = {e.__name__: sorted(v.value for v in e) for e in _ENUMS}
    out["DraftPolicyDecision"] = sorted(KNOWN_DRAFT_POLICY_DECISIONS)
    return out
