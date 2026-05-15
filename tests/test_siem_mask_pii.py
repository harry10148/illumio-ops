"""SIEM PII mask covering NotebookLM-recommended redaction surfaces:
created_by.user.username (admin email), action.src_ip, resource_changes
before/after values.

Default behaviour MUST be backward compatible (mask_pii=False -> no change)."""
from __future__ import annotations

from copy import deepcopy

import pytest

from src.siem.mask import REDACTED, mask_event, mask_flow


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


def test_mask_flow_default_passthrough():
    flow = {"src_ip": "10.0.0.1", "dst_ip": "10.0.0.2", "dst_port": 443}
    assert mask_flow(flow, mask_pii=True) is flow


def test_dispatcher_builder_threads_mask_pii_through():
    """build_dispatcher must propagate dest_cfg.mask_pii into the dispatcher."""
    from src.siem.dispatcher import build_dispatcher
    from src.config_models import SiemDestinationSettings

    class _SF:  # minimal session_factory stub — not exercised in __init__
        pass

    cfg = SiemDestinationSettings(
        name="masked-dest",
        transport="udp",
        format="json",
        host="127.0.0.1",
        port=514,
        mask_pii=True,
    )
    disp = build_dispatcher(cfg, _SF())
    assert getattr(disp, "_mask_pii", None) is True

    cfg2 = SiemDestinationSettings(
        name="open-dest", transport="udp", format="json",
        host="127.0.0.1", port=514,
    )
    disp2 = build_dispatcher(cfg2, _SF())
    assert getattr(disp2, "_mask_pii", None) is False
