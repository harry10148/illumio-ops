"""Alert rule models, the 5.x event-matching semantics they keep, and the best-practice pack."""
import pytest
from pydantic import TypeAdapter, ValidationError

from illumio_ops.domain.alertpack import PACK_KEYS, best_practice_rules
from illumio_ops.domain.alertrules import AlertRule, EventRule, event_matches
from illumio_ops.domain.values import AlertRuleType, DetectorKind

RULE = TypeAdapter(AlertRule)
BASE = {"id": "a" * 32, "name": "r", "pack_key": None, "enabled": True, "notify": True, "severity": "medium",
        "cooldown_minutes": 30, "throttle": None}


def event_rule(**kw):
    d = {**BASE, "type": "event", "event_types": ["agent.tampering"], "status": "all", "event_severity": "all",
         "match_fields": {}, "threshold": "immediate", "threshold_count": 1, "window_minutes": 10}
    d.update(kw)
    return EventRule.model_validate(d)


# ── 5.x matches_event_rule, case by case (tests/test_event_core.py, test_notification_matching.py) ──

PRUNE = {"event_type": "system_task.prune_old_log_events", "severity": "err", "status": None,
         "notifications": [{"notification_type": "hard_limit.exceeded", "info": {}}]}


@pytest.mark.parametrize("rule,event,expected", [
    # nested match_fields, alternatives, wildcards
    ({"event_types": ["user.login", "request.authentication_failed"], "status": "*", "event_severity": "err|warning",
          "match_fields": {"created_by.user.username": "admin@.*"}},
     {"event_type": "request.authentication_failed", "status": "failure", "severity": "err",
      "created_by": {"user": {"username": "admin@illumio.local"}}}, True),
    # literal dots are exact, not regex
    ({"event_types": ["request.authentication_failed"], "status": "failure", "event_severity": "err",
          "match_fields": {"created_by.user.username": "admin@example.com"}},
     {"event_type": "requestXauthentication_failed", "status": "failure", "severity": "err",
      "created_by": {"user": {"username": "admin@exampleXcom"}}}, False),
    ({"event_types": ["system_task.prune_old_log_events"],
          "match_fields": {"notification_type": "hard_limit.exceeded|soft_limit.exceeded"}}, PRUNE, True),
    ({"event_types": ["system_task.prune_old_log_events"], "match_fields": {"notification_type": "hard_limit.exceeded"}},
     dict(PRUNE, notifications=[{"notification_type": "system_task.event_pruning_completed"}]), False),
    ({"event_types": ["rule_set.create|rule_set.delete"]}, {"event_type": "rule_set.delete"}, True),
    ({"event_types": ["rule_set\\..*"]}, {"event_type": "rule_set.update"}, True),
    ({"event_types": ["agent.*"]}, {"event_type": "agent.tampering"}, True),
    ({"event_types": ["*"]}, {"event_type": "anything"}, True),
    ({"status": "!success"}, {"event_type": "agent.tampering", "status": "success"}, False),
    ({"status": "!success"}, {"event_type": "agent.tampering", "status": "failure"}, True),
    ({"status": "failure"}, {"event_type": "agent.tampering"}, False),
])
def test_event_rule_matches_like_5x(rule, event, expected):
    assert event_matches(event_rule(**rule), event) is expected


@pytest.mark.parametrize("rule_sev,event_sev,expected", [
    ("error", "err", True), ("err", "err", True), ("error", "error", True), ("error", "warning", False),
    ("error|warning", "err", True), ("!error", "err", False), ("!error", "info", True), ("all", "err", True),
    ("ERROR", "err", True),
])
def test_severity_err_error_alias(rule_sev, event_sev, expected):
    r = event_rule(event_severity=rule_sev)
    assert event_matches(r, {"event_type": "agent.tampering", "status": "success", "severity": event_sev}) is expected


# ── validation ──

def test_event_rule_invalid_regex_rejected():
    for kw in ({"event_types": ["agent.(tampering"]}, {"status": "fail[ure"}, {"event_severity": "(err"},
               {"match_fields": {"created_by.user.username": "admin@(.*"}}):
        with pytest.raises(ValidationError) as e:
            event_rule(**kw)
        msgs = [str(err["msg"]) for err in e.value.errors(include_input=False)]
        assert msgs and not any("(" in m or "[" in m for m in msgs)  # the message never echoes the pattern


def test_lateral_rule_needs_a_detector():
    d = {**BASE, "type": "lateral", "detectors": [], "min_severity": "medium", "critical_assets_only": False}
    with pytest.raises(ValidationError):
        RULE.validate_python(d)
    d["detectors"] = ["fanout"]
    assert RULE.validate_python(d).type == AlertRuleType.LATERAL


def test_traffic_window_minimum():
    d = {**BASE, "type": "traffic", "condition": {"decisions": ["blocked"]}, "threshold_connections": 25,
         "window_minutes": 5}
    with pytest.raises(ValidationError):
        RULE.validate_python(d)
    d["window_minutes"] = 10
    assert RULE.validate_python(d).condition.decisions[0].value == "blocked"


def test_severity_none_only_for_event_and_lateral_rules():
    assert event_rule(severity=None).severity is None
    assert RULE.validate_python({**BASE, "severity": None, "type": "lateral", "detectors": ["fanout"],
                                 "min_severity": "low", "critical_assets_only": False}).severity is None
    with pytest.raises(ValidationError):
        RULE.validate_python({**BASE, "severity": None, "type": "system", "check": "disk_low"})


def test_rule_id_must_be_32_hex():
    with pytest.raises(ValidationError):
        event_rule(id="18")


# ── the pack ──

def test_pack_ids_stable_and_unique():
    a, b = best_practice_rules(notify_new_defaults=True), best_practice_rules(notify_new_defaults=True)
    assert [r.id for r in a] == [r.id for r in b]
    assert len({r.id for r in a}) == len(a)
    assert {r.pack_key for r in a} == PACK_KEYS and all(r.name == "" for r in a)


# 5.x src/config.py _best_practice_rules: (name_key, filter_value, threshold, count, window, cooldown, status, throttle)
FIVE_X = [
    ("rule_agent_tampering", "agent.tampering", "immediate", 1, 10, 30, "all", None),
    ("rule_agent_suspend", "agent.suspend", "immediate", 1, 10, 30, "all", None),
    ("rule_agent_clone", "agent.clone_detected", "immediate", 1, 10, 30, "all", None),
    ("rule_agent_heartbeat", "system_task.agent_missed_heartbeats_check", "count", 3, 30, 60, "all", (1, 30)),
    ("rule_agent_offline", "system_task.agent_offline_check", "immediate", 1, 10, 60, "all", None),
    ("rule_lost_agent", "lost_agent.found", "immediate", 1, 10, 60, "all", None),
    ("rule_login_failed", "user.sign_in,user.login", "count", 5, 10, 30, "failure", (1, 15)),
    ("rule_api_auth_failed", "request.authentication_failed", "count", 5, 10, 30, "all", (1, 15)),
    ("rule_policy_fail", "agent.refresh_policy", "immediate", 1, 10, 30, "failure", None),
    ("rule_ruleset_change", "rule_set.create,rule_set.update,rule_set.delete", "immediate", 1, 10, 60, "all", None),
    ("rule_policy_provision", "sec_policy.create", "immediate", 1, 10, 60, "all", None),
    ("rule_api_authz_failed", "request.authorization_failed", "count", 3, 10, 30, "all", (1, 15)),
    ("rule_api_key_change", "api_key.create,api_key.delete", "immediate", 1, 10, 60, "all", None),
    ("rule_sec_rule_change", "sec_rule.create,sec_rule.update,sec_rule.delete", "immediate", 1, 10, 60, "all", None),
    ("rule_bulk_unpair", "workloads.unpair,agents.unpair", "immediate", 1, 10, 60, "all", None),
    ("rule_auth_settings_change", "authentication_settings.update", "immediate", 1, 10, 60, "all", None),
]


def test_pack_matches_5x_event_specs():
    by_key = {r.pack_key: r for r in best_practice_rules(notify_new_defaults=True)}
    for key, types, threshold, count, window, cooldown, status, throttle in FIVE_X:
        r = by_key[key]
        assert (r.type, list(r.event_types), r.threshold.value, r.threshold_count, r.window_minutes,
                r.cooldown_minutes, r.status, r.event_severity) == \
            ("event", types.split(","), threshold, count, window, cooldown, status, "all"), key
        assert (None if r.throttle is None else (r.throttle.count, r.throttle.period_minutes)) == throttle, key
    hb = by_key["rule_high_blocked"]
    assert (hb.type, [d.value for d in hb.condition.decisions], hb.threshold_connections, hb.window_minutes,
            hb.cooldown_minutes, (hb.throttle.count, hb.throttle.period_minutes)) == \
        ("traffic", ["blocked"], 25, 10, 30, (1, 15))


def test_pack_lateral_notify_follows_flag():
    for flag in (True, False):
        rules = best_practice_rules(notify_new_defaults=flag)
        lateral = [r for r in rules if r.type == "lateral"]
        assert sorted(d.value for r in lateral for d in r.detectors) == sorted(
            [DetectorKind.FANOUT, DetectorKind.NEW_ADMIN_CONNECTION, DetectorKind.CROSS_ENV,
             DetectorKind.PEER_DEVIATION, DetectorKind.VOLUME_SURGE, DetectorKind.ACCOUNT_NEW_SOURCE,
             DetectorKind.SUSPICIOUS_TOOL, DetectorKind.AUTH_TO_NON_DC, DetectorKind.NEW_DC_CLIENT,
             DetectorKind.DIRECTORY_SURGE])
        assert all(r.notify is flag for r in lateral)
        assert all(r.notify for r in rules if r.type != "lateral")
    systems = sorted(r.check.value for r in best_practice_rules(notify_new_defaults=True) if r.type == "system")
    assert systems == ["collection_failing", "data_loss", "disk_low", "job_failing", "pce_health"]


def test_pattern_compiled_the_way_it_runs():
    """(?i)x.* compiles on its own but not once anchored as the matcher runs it (review: saved, then every
    evaluation of the batch raised and the watermark never moved)."""
    for kw in ({"event_types": ["(?i)rule_set.*"]}, {"match_fields": {"created_by.user.username": "(?i)admin.*"}}):
        with pytest.raises(ValidationError):
            event_rule(**kw)


def test_unrunnable_pattern_never_raises():
    rule = event_rule().model_copy(update={"event_types": ["(?i)rule_set.*"]})  # stored before this check existed
    assert event_matches(rule, {"event_type": "rule_set.create"}) is False


def test_pack_has_anomaly_rules():
    """Spec §6.5.8: one rule per anomaly kind (the directory ones together); a new process is low and has none."""
    by_key = {r.pack_key: r for r in best_practice_rules(notify_new_defaults=True)}
    assert [d.value for d in by_key["rule_anomaly_directory"].detectors] == [
        "auth_to_non_dc", "new_dc_client", "directory_surge"]
    assert {"rule_anomaly_peer", "rule_anomaly_volume", "rule_anomaly_account_source", "rule_anomaly_tool"} <= set(by_key)
    assert not any(DetectorKind.NEW_PROCESS in getattr(r, "detectors", ()) for r in by_key.values())
    assert all(by_key[k].min_severity == "medium" and by_key[k].enabled for k in by_key if k.startswith("rule_anomaly"))
