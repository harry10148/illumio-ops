"""Compare current event matching with legacy analyzer semantics."""

from __future__ import annotations

from typing import Any

from .matcher import matches_event_rule
from .poller import event_identity

def _legacy_value_matches(expected: str, actual: Any) -> bool:
    normalized_expected = str(expected or "all")
    if normalized_expected in {"all", "*", ""}:
        return True
    return normalized_expected == str(actual or "")

def matches_event_rule_legacy(rule: dict[str, Any], event: dict[str, Any]) -> bool:
    event_type = str(event.get("event_type") or "")
    patterns = [
        value.strip()
        for value in str(rule.get("filter_value") or "").split(",")
        if value.strip()
    ]
    if not patterns:
        return False

    if event_type not in patterns:
        return False
    if not _legacy_value_matches(rule.get("filter_status", "all"), event.get("status")):
        return False
    if not _legacy_value_matches(rule.get("filter_severity", "all"), event.get("severity")):
        return False
    return True

def compare_event_rules(rules: list[dict[str, Any]], events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    comparisons: list[dict[str, Any]] = []
    for rule in rules:
        current_ids = {
            event_identity(event)
            for event in events
            if matches_event_rule(rule, event)
        }
        legacy_ids = {
            event_identity(event)
            for event in events
            if matches_event_rule_legacy(rule, event)
        }

        only_current = current_ids - legacy_ids
        only_legacy = legacy_ids - current_ids
        if not only_current and not only_legacy and len(current_ids) == len(legacy_ids):
            status = "same"
        elif only_current and only_legacy:
            status = "mixed"
        elif only_current:
            status = "current_more"
        else:
            status = "legacy_more"

        event_lookup = {event_identity(event): event for event in events}
        comparisons.append({
            "rule_id": rule.get("id"),
            "rule_name": rule.get("name", f"Rule {rule.get('id')}"),
            "current_count": len(current_ids),
            "legacy_count": len(legacy_ids),
            "delta": len(current_ids) - len(legacy_ids),
            "status": status,
            "only_current": [
                {
                    "event_id": event_id,
                    "event_type": event_lookup.get(event_id, {}).get("event_type"),
                    "timestamp": event_lookup.get(event_id, {}).get("timestamp"),
                }
                for event_id in sorted(only_current)
            ][:5],
            "only_legacy": [
                {
                    "event_id": event_id,
                    "event_type": event_lookup.get(event_id, {}).get("event_type"),
                    "timestamp": event_lookup.get(event_id, {}).get("timestamp"),
                }
                for event_id in sorted(only_legacy)
            ][:5],
        })
    return comparisons
