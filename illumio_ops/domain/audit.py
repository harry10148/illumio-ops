"""How much a PCE event type matters to an audit (P5b-2 Task 3): the levels of 5.x audit_risk.AUDIT_RISK_MAP. An
event type not listed is informational and carries no level (v6 severities start at low)."""
from __future__ import annotations

from illumio_ops.domain.values import Severity

_EXACT: dict[str, Severity] = {
    "agent.tampering": Severity.CRITICAL, "agent.clone_detected": Severity.CRITICAL,
    "agent.suspend": Severity.HIGH, "workloads.unpair": Severity.HIGH, "agents.unpair": Severity.HIGH,
    "request.authorization_failed": Severity.HIGH,
    "sec_policy.create": Severity.MEDIUM, "api_key.create": Severity.MEDIUM, "api_key.delete": Severity.MEDIUM,
    "authentication_settings.update": Severity.MEDIUM, "firewall_settings.update": Severity.MEDIUM,
    "system_task.agent_missed_heartbeats_check": Severity.LOW, "system_task.agent_offline_check": Severity.LOW,
    "lost_agent.found": Severity.LOW, "user.use_expired_password": Severity.LOW,
}
# Every event of these resources (rule_set.create, sec_rule.update, ...): one dot after the prefix.
_FAMILIES: dict[str, Severity] = {
    "rule_set.": Severity.MEDIUM, "sec_rule.": Severity.MEDIUM, "enforcement_boundary.": Severity.MEDIUM,
}
AUTH_FAILED = "request.authentication_failed"
AUTHZ_DENIED = "request.authorization_failed"
PROVISION = "sec_policy.create"
DRAFT_FAMILIES = ("rule_set.", "sec_rule.")
AGENT_SECURITY = ("agent.tampering", "agent.clone_detected", "agent.suspend", "workloads.unpair", "agents.unpair")


def risk_of(event_type: str) -> Severity | None:
    if event_type in _EXACT:
        return _EXACT[event_type]
    return next((s for prefix, s in _FAMILIES.items() if event_type.startswith(prefix)), None)


def is_draft_change(event_type: str) -> bool:
    return event_type.startswith(DRAFT_FAMILIES)
