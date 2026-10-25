from illumio_ops.domain.values import (
    KNOWN_DRAFT_POLICY_DECISIONS,
    AlertRuleType,
    PolicyDecision,
    export_value_domains,
    parse_draft_policy_decision,
)


def test_policy_decision_values_are_exact_strings():
    assert [v.value for v in PolicyDecision] == ["allowed", "potentially_blocked", "blocked", "unknown"]


def test_alert_rule_types_include_volume():
    assert {v.value for v in AlertRuleType} == {"event", "traffic", "bandwidth", "volume", "system"}


def test_draft_decision_unknown_value_passes_through():
    assert parse_draft_policy_decision("Some_New_Value") == "some_new_value"


def test_draft_decision_known_values_cover_boundary_and_override_deny():
    assert {
        "blocked_by_boundary", "potentially_blocked_by_boundary", "blocked_by_override_deny",
        "potentially_blocked_by_override_deny", "allowed_across_boundary",
    } <= KNOWN_DRAFT_POLICY_DECISIONS


def test_export_has_every_enum_and_no_ints():
    d = export_value_domains()
    assert set(d) >= {"PolicyDecision", "RuleAction", "AlertRuleType", "DeploymentType", "Language",
                      "ProbeName", "DraftPolicyDecision"}
    assert all(isinstance(v, str) for vals in d.values() for v in vals)
    assert all(vals == sorted(vals) for vals in d.values())
