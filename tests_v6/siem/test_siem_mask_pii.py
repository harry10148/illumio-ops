"""SIEM PII mask covering NotebookLM-recommended redaction surfaces:
created_by.user.username (admin email), action.src_ip, resource_changes
before/after values.

Default behaviour MUST be backward compatible (mask_pii=False -> no change)."""
from __future__ import annotations

from copy import deepcopy

import pytest

from illumio_ops.siem.mask import REDACTED, mask_event


@pytest.fixture
def pce_event():
    return {
        "href": "/orgs/1/events/abc-def",
        "event_type": "sec_rule.update",
        "timestamp": "2026-05-15T12:34:56Z",
        "status": "success",
        "severity": "info",
        "actor": "admin@lab.local",
        "source_ip": "192.168.20.30",
        "created_by": {
            "user": {
                "href": "/users/3",
                "username": "admin@lab.local",
                "name": "Lab Admin",
            },
        },
        "action": {
            "api_method": "PUT",
            "api_endpoint": "/api/v2/orgs/1/sec_policy/draft/rule_sets/1/sec_rules/5",
            "src_ip": "192.168.20.30",
            "http_status_code": 204,
        },
        "resource_changes": [
            {
                "resource": {"sec_rule": {"href": "/orgs/1/sec_policy/draft/rule_sets/1/sec_rules/5"}},
                "change_type": "update",
                "changes": [
                    {"name": "description", "before": "internal: ACME Corp", "after": "internal: ACME Corp v2"},
                    {"name": "resolve_labels", "before": True, "after": False},
                ],
            },
        ],
    }


def test_mask_disabled_returns_input_unchanged(pce_event):
    """Default opt-out: no mutation, same object reference."""
    out = mask_event(pce_event, mask_pii=False)
    assert out is pce_event


def test_mask_enabled_returns_deep_copy(pce_event):
    """When masking, original event must not be mutated."""
    snapshot = deepcopy(pce_event)
    out = mask_event(pce_event, mask_pii=True)
    assert out is not pce_event
    assert pce_event == snapshot, "input was mutated"


def test_mask_redacts_created_by_user_username(pce_event):
    out = mask_event(pce_event, mask_pii=True)
    assert out["created_by"]["user"]["username"] == REDACTED
    assert out["created_by"]["user"]["name"] == REDACTED
    # href stays — it's not PII
    assert out["created_by"]["user"]["href"] == "/users/3"


def test_mask_redacts_top_level_actor_and_source_ip(pce_event):
    out = mask_event(pce_event, mask_pii=True)
    assert out["actor"] == REDACTED
    assert out["source_ip"] == REDACTED


def test_mask_redacts_action_src_ip(pce_event):
    out = mask_event(pce_event, mask_pii=True)
    assert out["action"]["src_ip"] == REDACTED
    # API method / status code are operational, not redacted
    assert out["action"]["api_method"] == "PUT"
    assert out["action"]["http_status_code"] == 204


def test_mask_redacts_resource_changes_before_after_list_form(pce_event):
    out = mask_event(pce_event, mask_pii=True)
    changes = out["resource_changes"][0]["changes"]
    for ch in changes:
        assert ch["before"] == REDACTED
        assert ch["after"] == REDACTED
    # Change name (attr name) is not redacted — it's schema, not data
    assert changes[0]["name"] == "description"


def test_mask_redacts_resource_changes_before_after_dict_form():
    """PCE schema variants: changes may be a dict keyed by attribute."""
    event = {
        "event_type": "sec_rule.update",
        "resource_changes": [
            {
                "resource": {"sec_rule": {"href": "/x"}},
                "changes": {
                    "description": {"before": "old", "after": "new"},
                    "enabled": {"before": True, "after": False},
                },
            },
        ],
    }
    out = mask_event(event, mask_pii=True)
    for attr, ch in out["resource_changes"][0]["changes"].items():
        assert ch["before"] == REDACTED, f"{attr} before not redacted"
        assert ch["after"] == REDACTED, f"{attr} after not redacted"


def test_mask_tolerates_system_actor():
    """`actor == 'System'` is not PII — leave it alone (operational signal)."""
    event = {"actor": "System", "source_ip": "10.0.0.1"}
    out = mask_event(event, mask_pii=True)
    assert out["actor"] == "System"
    # source_ip is still redacted (admin path)
    assert out["source_ip"] == REDACTED


def test_mask_handles_missing_optional_fields():
    """Events without created_by / action / resource_changes should not crash."""
    event = {"event_type": "user.create_session", "timestamp": "2026-05-15T00:00:00Z"}
    out = mask_event(event, mask_pii=True)
    assert out == event  # nothing to redact












def test_mask_redacts_notification_user_and_src_ip():
    from illumio_ops.siem.mask import REDACTED, mask_event
    event = {"event_type": "user.login", "notifications": [
        {"notification_type": "user.pce_session_created", "info": {"user": {"href": "/users/11", "username": "admin@lab.local"}}},
        {"notification_type": "request.authentication_failed", "info": {"api_endpoint": "/api/v2/users/login", "src_ip": "192.168.20.30"}},
        {"notification_type": "x", "info": None},
        "not-a-dict",
    ]}
    out = mask_event(event, mask_pii=True)
    assert out["notifications"][0]["info"]["user"]["username"] == REDACTED
    assert out["notifications"][0]["info"]["user"]["href"] == "/users/11"
    assert out["notifications"][1]["info"]["src_ip"] == REDACTED
    assert out["notifications"][1]["info"]["api_endpoint"] == "/api/v2/users/login"
    assert event["notifications"][0]["info"]["user"]["username"] == "admin@lab.local"  # caller untouched


def _emails(text: str) -> list[str]:
    import re
    return re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", text)


def test_masked_real_events_carry_no_email_or_client_ip_in_any_format():
    """The 19 recorded PCE events (golden pairs), masked: no email address and no client IP is left anywhere in
    the forwarded line — the user's own resource (resource_changes[].resource.user) included (P7 security review)."""
    import json
    from pathlib import Path

    from illumio_ops.siem.formatters.cef import CEFFormatter
    from illumio_ops.siem.formatters.cef_pce import PceNativeCEFFormatter
    from illumio_ops.siem.formatters.normalized_json import NormalizedJSONFormatter
    pairs = json.loads(Path("tests_v6/siem/fixtures/pce_native_cef_pairs.json").read_text(encoding="utf-8"))["audit"]
    leaked = []
    for p in pairs:
        ev = p["event"]
        ip = (ev.get("action") or {}).get("src_ip")
        masked = mask_event(ev, mask_pii=True)
        for fmt in (PceNativeCEFFormatter(), CEFFormatter(), NormalizedJSONFormatter()):
            line = fmt.format_event(masked)
            if _emails(line) or (ip and ip != "FILTERED" and ip in line):
                leaked.append((ev.get("event_type"), type(fmt).__name__, _emails(line)[:2]))
    assert not leaked


def test_mask_redacts_user_resource_and_nested_before_after():
    ev = {"resource_changes": [{"resource": {"user": {"href": "/users/7", "username": "a@corp.example",
                                                      "full_name": "A B"}},
                                "changes": {"labels": {"added": [{"before": "x", "after": {"value": "proj-x"}}]}}}]}
    out = mask_event(ev, mask_pii=True)
    user = out["resource_changes"][0]["resource"]["user"]
    assert user["username"] == REDACTED and user["full_name"] == REDACTED and user["href"] == "/users/7"
    nested = out["resource_changes"][0]["changes"]["labels"]["added"][0]
    assert nested["before"] == REDACTED and nested["after"] == REDACTED
