from illumio_ops.domain.values import (
    KNOWN_DRAFT_POLICY_DECISIONS,
    LATERAL_PORTS_DEFAULT,
    AlertRuleType,
    PolicyDecision,
    Severity,
    export_value_domains,
    parse_draft_policy_decision,
    raise_severity,
)


def test_policy_decision_values_are_exact_strings():
    assert [v.value for v in PolicyDecision] == ["allowed", "potentially_blocked", "blocked", "unknown"]


def test_alert_rule_types_include_volume():
    assert {v.value for v in AlertRuleType} == {"event", "traffic", "bandwidth", "volume", "system", "lateral"}


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



def test_raise_severity_caps_at_critical():
    assert raise_severity(Severity.LOW) is Severity.MEDIUM
    assert raise_severity(Severity.MEDIUM, 2) is Severity.CRITICAL
    assert raise_severity(Severity.HIGH, 3) is Severity.CRITICAL
    assert raise_severity(Severity.CRITICAL) is Severity.CRITICAL


def test_new_value_domains_exported():
    d = export_value_domains()
    assert d["Severity"] == ["critical", "high", "low", "medium"]
    assert set(d["DetectorKind"]) == {"fanout", "new_admin_connection", "pivot_chain", "blocked_surge",
                                      "non_admin_group", "cross_env", "account_fanout", "unexpected_initiator",
                                      "peer_deviation", "volume_surge"}
    assert set(d["PortClass"]) == {"remote", "directory", "database"}
    assert set(d["DetectorState"]) == {"ok", "disabled", "accumulating", "no_data", "collection_off", "incomplete"}
    assert {"src_host", "dst_label", "service", "initiator_user", "event_type", "actor"} <= set(d["SegmentDimension"])
    assert set(d["SegmentMetric"]) == {"flows", "connections", "distinct_dst", "distinct_src", "distinct_ports",
                                       "bytes", "events"}
    assert set(d["SegmentView"]) == {"detail", "ranking", "predicted_block"}
    assert set(d["EdgeState"]) == {"allowed", "potentially_blocked", "unknown"}
    assert set(d["TamperPattern"]) == {"regular_cycle", "burst", "sporadic", "too_few"}
    assert set(d["TamperAction"]) == {"add_rule", "delete_rule", "add_chain", "delete_chain", "add_table", "delete_table"}
    assert set(d["PrecursorKind"]) == {"tamper", "suspend", "offline"}
    assert set(d["RansomwareTrafficClass"]) == {"priority", "safe_to_block", "suspicious", "protected", "unknown"}
    assert len(d["FocusKind"]) == 14 and {"detection", "stale_selector", "vendor_contradiction"} <= set(d["FocusKind"])
    assert set(d["Confidence"]) == {"high", "medium", "low"}


def test_lateral_ports_default_is_the_5x_list_in_three_classes():
    from illumio_ops.domain.values import DIRECTORY_PORTS, PortClass
    by_class: dict = {}
    for port, _, cls in LATERAL_PORTS_DEFAULT:
        by_class.setdefault(cls, set()).add(port)
    assert by_class[PortClass.REMOTE] == {445, 135, 139, 3389, 22, 5985, 5986, 23, 2049, 111, 5900, 5938}
    assert by_class[PortClass.DIRECTORY] == DIRECTORY_PORTS == {88, 464, 389, 636, 3268, 3269, 9389}
    assert by_class[PortClass.DATABASE] == {1433, 3306, 5432}
    names = {p: n for p, n, _ in LATERAL_PORTS_DEFAULT}
    assert names[111] == "RPC Portmapper" and names[5985] == "WinRM-HTTP" and len(names) == len(LATERAL_PORTS_DEFAULT)


def test_alert_value_domains():
    from illumio_ops.domain.values import Severity, alert_severity_of_event
    d = export_value_domains()
    assert "lateral" in d["AlertRuleType"]
    assert d["ChannelKind"] == ["line", "smtp", "teams", "telegram", "webhook"]
    assert d["SystemCheck"] == ["collection_failing", "data_loss", "disk_low", "job_failing", "pce_health"]
    assert d["ThresholdType"] == ["count", "immediate"]
    assert set(d["DeliveryStatus"]) == {"pending", "sent", "failed", "not_notified", "grouped", "no_channel"}
    assert [alert_severity_of_event(s) for s in ("err", "error", "warning", "info", None, "odd")] == [
        Severity.HIGH, Severity.HIGH, Severity.MEDIUM, Severity.LOW, Severity.MEDIUM, Severity.MEDIUM]
