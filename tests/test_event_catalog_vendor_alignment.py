"""Vendor-alignment tests: the vendor tier must match the official
Events Administration Guide list exactly; observed tier is disjoint."""
from __future__ import annotations

import json
from pathlib import Path

FIXTURE = Path("tests/fixtures/vendor_event_types.json")


def _fixture_set() -> frozenset[str]:
    return frozenset(json.loads(FIXTURE.read_text()))


def test_vendor_tier_matches_official_fixture_exactly():
    from src.events.catalog import VENDOR_DOCUMENTED_EVENT_TYPES
    official = _fixture_set()
    missing = official - VENDOR_DOCUMENTED_EVENT_TYPES
    extra = VENDOR_DOCUMENTED_EVENT_TYPES - official
    assert not missing, f"official types absent from vendor tier: {sorted(missing)}"
    assert not extra, f"vendor tier claims undocumented types: {sorted(extra)}"


def test_tiers_are_disjoint_and_union_is_known():
    from src.events.catalog import (
        KNOWN_EVENT_TYPES,
        OBSERVED_EXTENSION_EVENT_TYPES,
        VENDOR_DOCUMENTED_EVENT_TYPES,
    )
    assert not (VENDOR_DOCUMENTED_EVENT_TYPES & OBSERVED_EXTENSION_EVENT_TYPES)
    assert KNOWN_EVENT_TYPES == (VENDOR_DOCUMENTED_EVENT_TYPES | OBSERVED_EXTENSION_EVENT_TYPES)


def test_previously_missing_official_types_now_known():
    from src.events.catalog import VENDOR_DOCUMENTED_EVENT_TYPES, is_known_event_type
    for et in (
        "agent.refresh_policy",
        "logout_from_jwt",
        "support_report_request.create",
        "support_report_request.delete",
        "support_reports",
    ):
        assert et in VENDOR_DOCUMENTED_EVENT_TYPES
        assert is_known_event_type(et)


def test_typo_variant_stays_observed_and_hidden():
    from src.events.catalog import (
        OBSERVED_EXTENSION_EVENT_TYPES,
        VENDOR_DOCUMENTED_EVENT_TYPES,
        _HIDDEN_EVENT_TYPES,
    )
    assert "agent.reguest_policy" in OBSERVED_EXTENSION_EVENT_TYPES
    assert "agent.reguest_policy" not in VENDOR_DOCUMENTED_EVENT_TYPES
    assert "agent.reguest_policy" in _HIDDEN_EVENT_TYPES


def test_pce_25x_backfill_stays_known_via_observed_tier():
    from src.events.catalog import OBSERVED_EXTENSION_EVENT_TYPES, is_known_event_type
    for et in (
        "deny_rule.create",
        "agent.upgrade_successful",
        "container_cluster.kubernetes_workloads_bulk_create",
        "label_dimension.create",
    ):
        assert et in OBSERVED_EXTENSION_EVENT_TYPES
        assert is_known_event_type(et)


def test_is_vendor_documented_helper():
    from src.events.catalog import is_vendor_documented
    assert is_vendor_documented("agent.tampering")
    assert not is_vendor_documented("deny_rule.create")
    assert not is_vendor_documented("totally.unknown_thing")
