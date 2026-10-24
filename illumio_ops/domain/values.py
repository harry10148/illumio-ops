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


class FlowDirection(StrEnum):
    """Which VEN reported the flow: outbound = the initiating side, inbound = the serving side."""
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class VisibilityLevel(StrEnum):
    FLOW_SUMMARY = "flow_summary"
    ENHANCED_DATA_COLLECTION = "enhanced_data_collection"
    FLOW_DROPS = "flow_drops"
    FLOW_OFF = "flow_off"


class TamperClassification(StrEnum):
    CONFIRMED = "confirmed"
    SIGNAL = "signal"


class IngestSource(StrEnum):
    TRAFFIC = "traffic"
    EVENTS = "events"
    INVENTORY = "inventory"
    RANSOMWARE = "ransomware"
    BACKFILL = "backfill"


class DataOrigin(StrEnum):
    INGEST = "ingest"
    BACKFILL = "backfill"


# REST API guide: flow_summary records allowed, blocked and potentially blocked connections;
# flow_drops only blocked and potentially blocked; flow_off nothing. Enhanced data collection
# adds byte counts on top of flow_summary. Anything else is unknown, never guessed.
_SEES_ALLOWED: dict[str, bool] = {
    VisibilityLevel.FLOW_SUMMARY: True,
    VisibilityLevel.ENHANCED_DATA_COLLECTION: True,
    VisibilityLevel.FLOW_DROPS: False,
    VisibilityLevel.FLOW_OFF: False,
}


def visibility_sees_allowed(level: str | None) -> bool | None:
    """Whether a VEN at this visibility level reports allowed traffic (None = unknown level)."""
    return _SEES_ALLOWED.get(level) if level is not None else None


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
    FlowDirection, VisibilityLevel, TamperClassification, IngestSource, DataOrigin,
)


def export_value_domains() -> dict[str, list[str]]:
    """Every value domain by class name, values sorted — the frontend's copy of this module."""
    out = {e.__name__: sorted(v.value for v in e) for e in _ENUMS}
    out["DraftPolicyDecision"] = sorted(KNOWN_DRAFT_POLICY_DECISIONS)
    return out
