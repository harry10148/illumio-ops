"""Alert categories as the alerts page filters them (UI redesign spec §4.1): lateral movement, anomalies in allowed
traffic (spec §6.5.8), traffic rules, events and system checks. A lateral-rule alert's category follows the detector
that raised it."""
from __future__ import annotations

from typing import Literal

from illumio_ops.domain.values import AlertRuleType, DetectorKind

AlertCategory = Literal["lateral", "anomaly", "traffic", "event", "system"]
CATEGORIES: tuple[AlertCategory, ...] = ("lateral", "anomaly", "traffic", "event", "system")

ANOMALY_DETECTORS: frozenset[DetectorKind] = frozenset({
    DetectorKind.PEER_DEVIATION, DetectorKind.VOLUME_SURGE, DetectorKind.ACCOUNT_NEW_SOURCE,
    DetectorKind.SUSPICIOUS_TOOL, DetectorKind.NEW_PROCESS, DetectorKind.AUTH_TO_NON_DC, DetectorKind.NEW_DC_CLIENT,
    DetectorKind.DIRECTORY_SURGE, DetectorKind.DIRECTION_REVERSAL, DetectorKind.NEW_PAIR_PORT,
    DetectorKind.QUIET_HOST_WAKES, DetectorKind.DATA_STAGING, DetectorKind.OFF_HOURS,
})
_ANOMALY_VALUES = tuple(sorted(d.value for d in ANOMALY_DETECTORS))
TRAFFIC_TYPES = (AlertRuleType.TRAFFIC.value, AlertRuleType.BANDWIDTH.value, AlertRuleType.VOLUME.value)


def category(rule_type: AlertRuleType, detector: str | None) -> AlertCategory:
    if rule_type is AlertRuleType.LATERAL:
        return "anomaly" if detector in _ANOMALY_VALUES else "lateral"
    if rule_type.value in TRAFFIC_TYPES:
        return "traffic"
    return "event" if rule_type is AlertRuleType.EVENT else "system"


def category_filter(cat: AlertCategory) -> tuple[tuple[str, ...], tuple[str, ...] | None, tuple[str, ...] | None]:
    """(rule types, detectors the alert must have, detectors it must not have) for the store's query."""
    if cat == "anomaly":
        return (AlertRuleType.LATERAL.value,), _ANOMALY_VALUES, None
    if cat == "lateral":
        return (AlertRuleType.LATERAL.value,), None, _ANOMALY_VALUES
    if cat == "traffic":
        return TRAFFIC_TYPES, None, None
    return (cat,), None, None
