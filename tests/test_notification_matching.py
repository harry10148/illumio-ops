"""notification_type extraction and rule matching (capacity alerts rely on it:
hard_limit.exceeded / soft_limit.exceeded are notification types, not event types)."""
from __future__ import annotations

from src.events.matcher import matches_event_rule
from src.events.normalizer import normalize_event

PRUNE_EVENT = {
    "href": "/orgs/1/events/abc",
    "event_type": "system_task.prune_old_log_events",
    "timestamp": "2026-07-04T03:00:00Z",
    "severity": "err",
    "status": None,
    "notifications": [
        {"notification_type": "hard_limit.exceeded", "info": {}},
    ],
}


def test_normalizer_extracts_notification_types():
    norm = normalize_event(PRUNE_EVENT)
    assert norm["notification_types"] == ["hard_limit.exceeded"]


def test_normalizer_handles_missing_notifications():
    norm = normalize_event({"event_type": "user.login", "timestamp": "2026-07-04T00:00:00Z"})
    assert norm["notification_types"] == []


def test_rule_matches_on_notification_type():
    rule = {
        "filter_value": "system_task.prune_old_log_events",
        "filter_status": "all",
        "filter_severity": "all",
        "match_fields": {"notification_type": "hard_limit.exceeded|soft_limit.exceeded"},
    }
    assert matches_event_rule(rule, PRUNE_EVENT)


def test_rule_rejects_when_notification_type_absent():
    rule = {
        "filter_value": "system_task.prune_old_log_events",
        "filter_status": "all",
        "filter_severity": "all",
        "match_fields": {"notification_type": "hard_limit.exceeded"},
    }
    benign = dict(PRUNE_EVENT, notifications=[{"notification_type": "system_task.event_pruning_completed"}])
    assert not matches_event_rule(rule, benign)
