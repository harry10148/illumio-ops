"""Catalog coverage tests for the 7 PCE 25.x event_types we hit in the wild
plus the resource-prefix fallback mechanism."""
from __future__ import annotations

import pytest

from src.events.catalog import (
    KNOWN_EVENT_TYPES,
    KNOWN_RESOURCE_PREFIXES,
    classify_unknown_event_type,
    is_known_event_type,
)


# These were the 7 event_types accumulated in unknown_events on the test
# machine before this catalog backfill (2026-05-15 audit).
PCE_25X_BACKFILL = [
    "deny_rule.create",
    "deny_rule.update",
    "deny_rule.delete",  # added for symmetry
    "agent.upgrade_successful",
    "container_cluster.kubernetes_workloads_bulk_create",
    "container_cluster.kubernetes_workloads_bulk_update",
    "label_dimension.create",
    "label_dimension.update",
    "label_dimension.delete",
    "label_mapping_rule.create",
    "label_mapping_rule.update",
    "label_mapping_rule.delete",
]


@pytest.mark.parametrize("event_type", PCE_25X_BACKFILL)
def test_backfilled_event_type_in_catalog(event_type):
    assert event_type in KNOWN_EVENT_TYPES, f"{event_type} missing from catalog"
    assert is_known_event_type(event_type) is True


def test_resource_prefix_set_contains_known_families():
    for resource in ("deny_rule", "agent", "container_cluster",
                     "label_dimension", "label_mapping_rule",
                     "sec_rule", "rule_set", "workload"):
        assert resource in KNOWN_RESOURCE_PREFIXES, (
            f"{resource} missing from KNOWN_RESOURCE_PREFIXES"
        )


def test_lenient_known_accepts_new_action_on_known_resource():
    """Future PCE versions may add deny_rule.bulk_delete or
    agent.upgrade_failed — lenient=True must classify these as known."""
    novel = [
        "deny_rule.bulk_delete",
        "agent.upgrade_failed",
        "container_cluster.kubernetes_workloads_bulk_delete",
        "label_dimension.archive",
        "sec_rule.bulk_update",
    ]
    for et in novel:
        assert et not in KNOWN_EVENT_TYPES  # not in explicit catalog
        assert is_known_event_type(et) is False  # strict: not known
        assert is_known_event_type(et, lenient=True) is True, (
            f"lenient mode should accept {et} (known resource prefix)"
        )


def test_lenient_known_rejects_truly_novel_resource():
    """If the resource family itself is new (e.g. PCE introduces 'compliance_policy'),
    lenient mode should NOT mark it as known."""
    truly_novel = [
        "compliance_policy.create",
        "ai_governance.update",
        "quantum_workload.create",
    ]
    for et in truly_novel:
        assert is_known_event_type(et, lenient=True) is False


def test_classify_returns_resource_for_known_family():
    assert classify_unknown_event_type("deny_rule.bulk_delete") == "deny_rule"
    assert classify_unknown_event_type("agent.upgrade_failed") == "agent"


def test_classify_returns_unclassified_for_unknown_resource():
    assert classify_unknown_event_type("compliance_policy.create") == "unclassified"


def test_classify_returns_unclassified_for_malformed():
    assert classify_unknown_event_type("") == "unclassified"
    assert classify_unknown_event_type("no_dot_here") == "unclassified"
    assert classify_unknown_event_type(".bare_action") == "unclassified"


def test_backward_compat_no_kwargs_call():
    """is_known_event_type() must remain callable positionally without kwargs
    (used by analyzer.py, normalizer.py)."""
    assert is_known_event_type("agent.activate") is True
    assert is_known_event_type("nope.nada") is False


# ----- 3rd fallback: payload resource_type hint -----

def test_lenient_uses_resource_type_hint_when_event_type_malformed():
    """If event_type is missing the dot but payload carries resource_type
    (extracted from resource_changes[0].resource), lenient mode accepts it."""
    assert is_known_event_type("malformed_no_dot", lenient=True,
                               resource_type="deny_rule") is True
    assert is_known_event_type("", lenient=True,
                               resource_type="agent") is True


def test_lenient_rejects_when_neither_event_prefix_nor_resource_type_known():
    assert is_known_event_type("compliance_policy.create", lenient=True,
                               resource_type="compliance_policy") is False
    assert is_known_event_type("garbage", lenient=True,
                               resource_type=None) is False


def test_classify_uses_resource_type_when_prefix_unhelpful():
    # event_type prefix says nothing useful; resource_type hint saves it
    assert classify_unknown_event_type("ev_42", resource_type="deny_rule") == "deny_rule"
    assert classify_unknown_event_type("", resource_type="agent") == "agent"


def test_classify_prefers_event_type_prefix_over_resource_type():
    """When both are usable, event_type prefix wins (more specific)."""
    # Both deny_rule and agent are known — event_type prefix path returns first
    assert classify_unknown_event_type("deny_rule.foo",
                                       resource_type="agent") == "deny_rule"
