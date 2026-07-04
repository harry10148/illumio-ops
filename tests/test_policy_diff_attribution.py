"""Tests for policy-diff operator attribution (pure derivation)."""
from __future__ import annotations

import pandas as pd

from src.report.analysis.policy_diff.diff_engine import diff_rulesets
from src.report.analysis.policy_diff.attribution import attribute_changes


def _rs(rs_id, name, enabled):
    return {"href": f"/orgs/1/sec_policy/draft/rule_sets/{rs_id}",
            "name": name, "enabled": enabled, "description": "", "rules": []}


def _diff_with_one_modified_ruleset():
    draft = [_rs(1, "RS-A", False)]
    active = [_rs(1, "RS-A", True)]
    return diff_rulesets(draft, active)


def _policy_events(rows):
    return {"draft_events": pd.DataFrame(rows)}


def test_latest_event_is_attributed():
    diff = _diff_with_one_modified_ruleset()
    events = _policy_events([
        {"resource_name": "RS-A", "actor": "alice", "timestamp": "2026-06-01T10:00:00Z",
         "event_type": "rule_set.update"},
        {"resource_name": "RS-A", "actor": "bob", "timestamp": "2026-06-05T12:00:00Z",
         "event_type": "rule_set.update"},
    ])
    out = attribute_changes(diff, events)
    row = out["ruleset_changes"].to_dict("records")[0]
    assert row["last_actor"] == "bob"           # most recent wins
    assert row["last_changed"] == "2026-06-05T12:00:00Z"
    assert row["last_event"] == "rule_set.update"


def test_no_matching_event_leaves_attribution_blank():
    diff = _diff_with_one_modified_ruleset()
    events = _policy_events([
        {"resource_name": "OTHER-RS", "actor": "carol",
         "timestamp": "2026-06-05T12:00:00Z", "event_type": "rule_set.update"},
    ])
    out = attribute_changes(diff, events)
    row = out["ruleset_changes"].to_dict("records")[0]
    assert row["last_actor"] == ""
    assert row["last_changed"] == ""


def test_empty_events_does_not_raise():
    diff = _diff_with_one_modified_ruleset()
    out = attribute_changes(diff, {"draft_events": pd.DataFrame()})
    assert out["ruleset_changes"].to_dict("records")[0]["last_actor"] == ""


def test_error_events_dict_does_not_raise():
    diff = _diff_with_one_modified_ruleset()
    out = attribute_changes(diff, {"error": "No event data available"})
    assert out["ruleset_changes"].to_dict("records")[0]["last_actor"] == ""


def test_non_dict_events_does_not_raise():
    diff = _diff_with_one_modified_ruleset()
    out = attribute_changes(diff, None)
    assert out["ruleset_changes"].to_dict("records")[0]["last_actor"] == ""


def test_garbage_events_value_does_not_raise():
    diff = _diff_with_one_modified_ruleset()
    out = attribute_changes(diff, "not a dict")
    assert out["ruleset_changes"].to_dict("records")[0]["last_actor"] == ""


def test_object_changes_attributed_from_object_events():
    diff = {
        "ruleset_changes": pd.DataFrame(),
        "rule_changes": pd.DataFrame(),
        "ip_list_changes": pd.DataFrame([
            {"change_type": "modified", "object_kind": "ip_list", "name": "Corp-Nets",
             "object_id": "5", "field": "ip_ranges", "draft_value": "x", "active_value": "y",
             "scope_expanded": True, "last_actor": "", "last_changed": "", "last_event": ""},
        ]),
    }
    events = {
        "draft_events": pd.DataFrame(),
        "object_events": pd.DataFrame([
            {"resource_name": "Corp-Nets", "actor": "alice@corp",
             "timestamp": "2026-07-03T10:00:00Z", "event_type": "ip_list.update"},
        ]),
    }
    out = attribute_changes(diff, events)
    row = out["ip_list_changes"].iloc[0]
    assert row["last_actor"] == "alice@corp"
    assert row["last_event"] == "ip_list.update"


def test_object_changes_survive_missing_object_events_key():
    diff = {"ruleset_changes": pd.DataFrame(), "rule_changes": pd.DataFrame(),
            "ip_list_changes": pd.DataFrame([
                {"change_type": "removed", "object_kind": "ip_list", "name": "L",
                 "object_id": "1", "field": "*", "draft_value": "", "active_value": "L",
                 "scope_expanded": False, "last_actor": "", "last_changed": "", "last_event": ""}])}
    out = attribute_changes(diff, {"draft_events": pd.DataFrame()})
    assert out["ip_list_changes"].iloc[0]["last_actor"] == ""


def test_nan_timestamp_event_does_not_win():
    diff = {
        "ruleset_changes": pd.DataFrame([
            {"change_type": "modified", "ruleset_name": "RS-A", "ruleset_id": "1",
             "field": "enabled", "draft_value": "False", "active_value": "True",
             "last_actor": "", "last_changed": "", "last_event": ""}]),
        "rule_changes": pd.DataFrame(),
    }
    events = {"draft_events": pd.DataFrame([
        {"resource_name": "RS-A", "actor": "alice@corp",
         "timestamp": "2026-06-01T10:00:00Z", "event_type": "rule_set.update"},
        {"resource_name": "RS-A", "actor": "bob@corp",
         "timestamp": float("nan"), "event_type": "rule_set.update"},
    ])}
    out = attribute_changes(diff, events)
    row = out["ruleset_changes"].iloc[0]
    assert row["last_actor"] == "alice@corp"
    assert row["last_changed"] == "2026-06-01T10:00:00Z"


def test_none_actor_yields_empty_string_not_literal_none():
    diff = {"ruleset_changes": pd.DataFrame([
        {"change_type": "modified", "ruleset_name": "RS-B", "ruleset_id": "2",
         "field": "name", "draft_value": "x", "active_value": "y",
         "last_actor": "", "last_changed": "", "last_event": ""}]),
        "rule_changes": pd.DataFrame()}
    events = {"draft_events": pd.DataFrame([
        {"resource_name": "RS-B", "actor": None,
         "timestamp": "2026-06-02T10:00:00Z", "event_type": "rule_set.update"}])}
    out = attribute_changes(diff, events)
    assert out["ruleset_changes"].iloc[0]["last_actor"] == ""
