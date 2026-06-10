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
