import json
from pathlib import Path

from src.events import compare_event_rules, normalize_event


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "event_replay_samples.json"


def _load_events():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_replay_fixture_normalizes_without_unknowns_or_notes():
    events = _load_events()

    normalized = [normalize_event(event) for event in events]

    assert all(item["known_event_type"] for item in normalized)
    assert all(item["parser_notes"] == [] for item in normalized)

    by_type = {item["event_type"]: item for item in normalized}
    assert by_type["user.create_session"]["target_name"] == "admin@lab.local"
    assert by_type["container_cluster.security_policy_applied"]["actor"] == "local_k8s"
    assert by_type["agent.upload_existing_ip_table_rules"]["target_name"] == "agent:1228"
    assert by_type["sec_policy.create"]["workloads_affected"] == 69
    assert by_type["rule_set.update"]["resource_name"] == "CoreServices | VMware"


def test_shadow_compare_detects_nested_field_rules_but_not_simple_rules():
    events = _load_events()
    rules = [
        {
            "id": 1,
            "type": "event",
            "name": "Simple exact",
            "filter_value": "rule_set.update",
            "filter_status": "success",
            "filter_severity": "info",
        },
        {
            "id": 2,
            "type": "event",
            "name": "Nested actor",
            "filter_value": "rule_set.update",
            "filter_status": "success",
            "filter_severity": "info",
            "match_fields": {
                "created_by.user.username": "other@lab.local",
            },
        },
    ]

    comparison = compare_event_rules(rules, events)
    by_rule = {item["rule_id"]: item for item in comparison}

    assert by_rule[1]["status"] == "same"
    assert by_rule[1]["current_count"] == 1
    assert by_rule[2]["status"] == "legacy_more"
    assert by_rule[2]["current_count"] == 0
    assert by_rule[2]["legacy_count"] == 1
