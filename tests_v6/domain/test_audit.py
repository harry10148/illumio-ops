"""The audit risk of a PCE event type (P5b-2 Task 3): 5.x audit_risk.AUDIT_RISK_MAP's levels; INFO is not listed."""
from illumio_ops.domain.audit import risk_of
from illumio_ops.domain.values import Severity


def test_risk_map_levels():
    assert risk_of("agent.tampering") is Severity.CRITICAL and risk_of("agent.clone_detected") is Severity.CRITICAL
    assert risk_of("request.authorization_failed") is Severity.HIGH and risk_of("workloads.unpair") is Severity.HIGH
    assert risk_of("sec_policy.create") is Severity.MEDIUM and risk_of("rule_set.update") is Severity.MEDIUM
    assert risk_of("sec_rule.delete") is Severity.MEDIUM and risk_of("enforcement_boundary.create") is Severity.MEDIUM
    assert risk_of("lost_agent.found") is Severity.LOW and risk_of("user.use_expired_password") is Severity.LOW
    assert risk_of("user.sign_in") is None and risk_of("rule_setx.create") is None
