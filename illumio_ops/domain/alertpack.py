"""The best-practice rule pack: 5.x's built-in rules (src/config.py _best_practice_rules, 5.x 035f7519), the
system checks 5.x ran as its watchdog and data-loss meta-alerts, and the three lateral-movement rules spec
§6.5.2 turns on by default. A pack rule's id comes from its key, so "add what is missing" can tell which
are there."""
from __future__ import annotations

import hashlib

from illumio_ops.domain.alertrules import (
    AlertRule,
    EventRule,
    LateralRule,
    SystemRule,
    Throttle,
    TrafficRule,
)
from illumio_ops.domain.filter import FlowCondition
from illumio_ops.domain.values import (
    DetectorKind,
    PolicyDecision,
    Severity,
    SystemCheck,
    ThresholdType,
)

# (key, event types, threshold, count, window, cooldown, status, throttle (count, minutes) or None)
_EVENTS: tuple[tuple[str, str, ThresholdType, int, int, int, str, tuple[int, int] | None], ...] = (
    ("rule_agent_tampering", "agent.tampering", ThresholdType.IMMEDIATE, 1, 10, 30, "all", None),
    ("rule_agent_suspend", "agent.suspend", ThresholdType.IMMEDIATE, 1, 10, 30, "all", None),
    ("rule_agent_clone", "agent.clone_detected", ThresholdType.IMMEDIATE, 1, 10, 30, "all", None),
    ("rule_agent_heartbeat", "system_task.agent_missed_heartbeats_check", ThresholdType.COUNT, 3, 30, 60, "all",
     (1, 30)),
    ("rule_agent_offline", "system_task.agent_offline_check", ThresholdType.IMMEDIATE, 1, 10, 60, "all", None),
    ("rule_lost_agent", "lost_agent.found", ThresholdType.IMMEDIATE, 1, 10, 60, "all", None),
    ("rule_login_failed", "user.sign_in,user.login", ThresholdType.COUNT, 5, 10, 30, "failure", (1, 15)),
    ("rule_api_auth_failed", "request.authentication_failed", ThresholdType.COUNT, 5, 10, 30, "all", (1, 15)),
    ("rule_policy_fail", "agent.refresh_policy", ThresholdType.IMMEDIATE, 1, 10, 30, "failure", None),
    ("rule_ruleset_change", "rule_set.create,rule_set.update,rule_set.delete", ThresholdType.IMMEDIATE, 1, 10, 60,
     "all", None),
    ("rule_policy_provision", "sec_policy.create", ThresholdType.IMMEDIATE, 1, 10, 60, "all", None),
    ("rule_api_authz_failed", "request.authorization_failed", ThresholdType.COUNT, 3, 10, 30, "all", (1, 15)),
    ("rule_api_key_change", "api_key.create,api_key.delete", ThresholdType.IMMEDIATE, 1, 10, 60, "all", None),
    ("rule_sec_rule_change", "sec_rule.create,sec_rule.update,sec_rule.delete", ThresholdType.IMMEDIATE, 1, 10, 60,
     "all", None),
    ("rule_bulk_unpair", "workloads.unpair,agents.unpair", ThresholdType.IMMEDIATE, 1, 10, 60, "all", None),
    ("rule_auth_settings_change", "authentication_settings.update", ThresholdType.IMMEDIATE, 1, 10, 60, "all", None),
)
# Security-state changes worth a fixed high severity; the other event rules follow the event's own severity.
_HIGH = frozenset({"rule_agent_tampering", "rule_agent_clone", "rule_agent_suspend", "rule_lost_agent",
                   "rule_bulk_unpair", "rule_auth_settings_change", "rule_api_key_change"})
_SYSTEM: tuple[tuple[str, SystemCheck, Severity], ...] = (
    ("rule_system_pce_health", SystemCheck.PCE_HEALTH, Severity.HIGH),
    ("rule_system_collection_failing", SystemCheck.COLLECTION_FAILING, Severity.HIGH),
    ("rule_system_data_loss", SystemCheck.DATA_LOSS, Severity.HIGH),
    ("rule_system_job_failing", SystemCheck.JOB_FAILING, Severity.HIGH),
    ("rule_system_disk_low", SystemCheck.DISK_LOW, Severity.MEDIUM),
)
_LATERAL: tuple[tuple[str, DetectorKind], ...] = (
    ("rule_lateral_fanout", DetectorKind.FANOUT),
    ("rule_lateral_new_admin", DetectorKind.NEW_ADMIN_CONNECTION),
    ("rule_lateral_cross_env", DetectorKind.CROSS_ENV),
)
HIGH_BLOCKED = "rule_high_blocked"

PACK_KEYS: frozenset[str] = frozenset(
    {k for k, *_ in _EVENTS} | {k for k, *_ in _SYSTEM} | {k for k, _ in _LATERAL} | {HIGH_BLOCKED})


def pack_rule_id(key: str) -> str:
    return hashlib.md5(key.encode(), usedforsecurity=False).hexdigest()


def best_practice_rules(*, notify_new_defaults: bool) -> tuple[AlertRule, ...]:
    """notify_new_defaults applies to the lateral-movement rules only: an install upgraded from 5.x records
    them without sending until the operator turns each on (spec §7)."""
    out: list[AlertRule] = []
    for key, types, threshold, count, window, cooldown, status, throttle in _EVENTS:
        out.append(EventRule(
            type="event", id=pack_rule_id(key), name="", pack_key=key, enabled=True, notify=True,
            severity=Severity.HIGH if key in _HIGH else None, cooldown_minutes=cooldown,
            throttle=Throttle(count=throttle[0], period_minutes=throttle[1]) if throttle else None,
            event_types=tuple(types.split(",")), status=status, event_severity="all", match_fields={},
            threshold=threshold, threshold_count=count, window_minutes=window))
    out.append(TrafficRule(
        type="traffic", id=pack_rule_id(HIGH_BLOCKED), name="", pack_key=HIGH_BLOCKED, enabled=True, notify=True,
        severity=Severity.MEDIUM, cooldown_minutes=30, throttle=Throttle(count=1, period_minutes=15),
        condition=FlowCondition(decisions=(PolicyDecision.BLOCKED,)), threshold_connections=25, window_minutes=10))
    for key, check, severity in _SYSTEM:
        out.append(SystemRule(type="system", id=pack_rule_id(key), name="", pack_key=key, enabled=True, notify=True,
                              severity=severity, cooldown_minutes=60, throttle=None, check=check))
    for key, detector in _LATERAL:
        out.append(LateralRule(type="lateral", id=pack_rule_id(key), name="", pack_key=key, enabled=True,
                               notify=notify_new_defaults, severity=None, cooldown_minutes=0, throttle=None,
                               detectors=(detector,), min_severity=Severity.MEDIUM, critical_assets_only=False))
    return tuple(out)
