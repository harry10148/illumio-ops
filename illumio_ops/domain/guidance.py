"""What to do next about an alert: the dictionary keys of its steps, chosen by what fired (the PCE event type, the
system check, the detector), so a rule an operator wrote about the same event gets the same steps. The PCE facts in
the event steps were checked against the vendor documents (Admin and REST API guides 25.2/26.1, Events Monitoring
Best Practices; 2026-11-06); a step names only pages and actions this product or the PCE has. An alert with nothing
specific to say gets no step rather than filler."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from illumio_ops.domain.alerting import (
    EVENT_MESSAGE_KEYS,
    EVENT_SUBJECT_KEYS,
    LATERAL_MESSAGE_KEYS,
    SYSTEM_MESSAGE_KEYS,
)
from illumio_ops.domain.alertpack import HIGH_BLOCKED
from illumio_ops.domain.values import DetectorKind, SystemCheck

# PCE event type -> step. Changes to rule sets and to rules share one.
EVENT_GUIDE: Mapping[str, str] = {
    "agent.tampering": "guide_ev_tampering",
    "agent.suspend": "guide_ev_suspend",
    "agent.clone_detected": "guide_ev_clone",
    "system_task.agent_missed_heartbeats_check": "guide_ev_missed_heartbeats",
    "system_task.agent_offline_check": "guide_ev_offline",
    "lost_agent.found": "guide_ev_lost_agent",
    "user.sign_in": "guide_ev_login_failed",
    "user.login": "guide_ev_login_failed",
    "request.authentication_failed": "guide_ev_api_authn",
    "request.authorization_failed": "guide_ev_api_authz",
    "agent.refresh_policy": "guide_ev_policy_apply",
    "rule_set.create": "guide_ev_policy_change",
    "rule_set.update": "guide_ev_policy_change",
    "rule_set.delete": "guide_ev_policy_change",
    "sec_rule.create": "guide_ev_policy_change",
    "sec_rule.update": "guide_ev_policy_change",
    "sec_rule.delete": "guide_ev_policy_change",
    "sec_policy.create": "guide_ev_provision",
    "api_key.create": "guide_ev_api_key",
    "api_key.delete": "guide_ev_api_key",
    "workloads.unpair": "guide_ev_unpair",
    "agents.unpair": "guide_ev_unpair",
    "authentication_settings.update": "guide_ev_auth_settings",
}

SYSTEM_GUIDE_KEYS: Mapping[SystemCheck, str] = {
    SystemCheck.PCE_HEALTH: "guide_sys_pce_health",
    SystemCheck.COLLECTION_FAILING: "guide_sys_collection_failing",
    SystemCheck.DATA_LOSS: "guide_sys_data_loss",
    SystemCheck.JOB_FAILING: "guide_sys_job_failing",
    SystemCheck.DISK_LOW: "guide_sys_disk_low",
    SystemCheck.SIEM_BACKLOG: "guide_sys_siem_backlog",
}
DETECTOR_GUIDE_KEYS: Mapping[DetectorKind, str] = {
    DetectorKind.FANOUT: "guide_det_fanout",
    DetectorKind.NEW_ADMIN_CONNECTION: "guide_det_new_admin_connection",
    DetectorKind.PIVOT_CHAIN: "guide_det_pivot_chain",
    DetectorKind.BLOCKED_SURGE: "guide_det_blocked_surge",
    DetectorKind.NON_ADMIN_GROUP: "guide_det_non_admin_group",
    DetectorKind.CROSS_ENV: "guide_det_cross_env",
    DetectorKind.ACCOUNT_FANOUT: "guide_det_account_fanout",
    DetectorKind.UNEXPECTED_INITIATOR: "guide_det_unexpected_initiator",
    DetectorKind.PEER_DEVIATION: "guide_det_peer_deviation",
    DetectorKind.VOLUME_SURGE: "guide_det_volume_surge",
    DetectorKind.ACCOUNT_NEW_SOURCE: "guide_det_account_new_source",
    DetectorKind.SUSPICIOUS_TOOL: "guide_det_suspicious_tool",
    DetectorKind.NEW_PROCESS: "guide_det_new_process",
    DetectorKind.AUTH_TO_NON_DC: "guide_det_auth_to_non_dc",
    DetectorKind.NEW_DC_CLIENT: "guide_det_new_dc_client",
    DetectorKind.DIRECTORY_SURGE: "guide_det_directory_surge",
    DetectorKind.DIRECTION_REVERSAL: "guide_det_direction_reversal",
    DetectorKind.NEW_PAIR_PORT: "guide_det_new_pair_port",
    DetectorKind.QUIET_HOST_WAKES: "guide_det_quiet_host_wakes",
    DetectorKind.DATA_STAGING: "guide_det_data_staging",
    DetectorKind.OFF_HOURS: "guide_det_off_hours",
}

_EVENT_KEYS = frozenset(EVENT_MESSAGE_KEYS.values()) | frozenset(EVENT_SUBJECT_KEYS.values())
_SYSTEM = {SYSTEM_MESSAGE_KEYS[k]: v for k, v in SYSTEM_GUIDE_KEYS.items()}
_DETECTOR = {LATERAL_MESSAGE_KEYS[k]: v for k, v in DETECTOR_GUIDE_KEYS.items()}
_PACK = {HIGH_BLOCKED: "guide_high_blocked"}


def guide_keys(message_key: str, params: Mapping[str, Any], pack_key: str | None) -> tuple[str, ...]:
    """The steps' dictionary keys, each once, in the order the alert names what fired."""
    if message_key in _EVENT_KEYS:
        types = params.get("event_types") or []
        keys = [EVENT_GUIDE[t] for t in types if isinstance(t, str) and t in EVENT_GUIDE]
        return tuple(dict.fromkeys(keys))
    if message_key in _SYSTEM:
        return (_SYSTEM[message_key],)
    if message_key in _DETECTOR:
        return (_DETECTOR[message_key],)
    if pack_key in _PACK:
        return (_PACK[pack_key],)
    return ()
