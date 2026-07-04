"""Tests for the PolicyDiffReport facade (wiring + export)."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pandas as pd

from src.report.policy_diff_report import PolicyDiffReport


def _draft():
    return [{"href": "/orgs/1/sec_policy/draft/rule_sets/1", "name": "RS-A",
             "enabled": False, "description": "", "rules": []}]


def _active():
    return [{"href": "/orgs/1/sec_policy/active/rule_sets/1", "name": "RS-A",
             "enabled": True, "description": "", "rules": []}]


def test_run_produces_html_with_diff_and_attribution(tmp_path):
    api = MagicMock()
    api.get_all_rulesets.return_value = _draft()
    api.get_active_rulesets.return_value = _active()

    events = {"draft_events": pd.DataFrame([
        {"resource_name": "RS-A", "actor": "bob",
         "timestamp": "2026-06-05T12:00:00Z", "event_type": "rule_set.update"},
    ])}

    with patch("src.report.policy_diff_report.PolicyDiffReport._fetch_policy_events",
               return_value=events):
        path = PolicyDiffReport(cm=MagicMock(), api_client=api).run(
            output_dir=str(tmp_path), lang="en")

    assert os.path.isfile(path)
    html = open(path, encoding="utf-8").read()
    assert "RS-A" in html
    assert "bob" in html


def test_run_uses_force_refresh_for_draft(tmp_path):
    api = MagicMock()
    api.get_all_rulesets.return_value = _draft()
    api.get_active_rulesets.return_value = _active()
    with patch("src.report.policy_diff_report.PolicyDiffReport._fetch_policy_events",
               return_value={"draft_events": pd.DataFrame()}):
        PolicyDiffReport(cm=MagicMock(), api_client=api).run(output_dir=str(tmp_path))
    api.get_all_rulesets.assert_called_once_with(force_refresh=True)


def test_build_without_api_returns_empty_diff():
    report = PolicyDiffReport(cm=MagicMock(), api_client=None)
    diff = report.build()
    assert diff["summary"]["total_changes"] == 0
    assert diff["ruleset_changes"].empty
    assert diff["rule_changes"].empty
    assert diff["summary"]["ip_lists_added"] == 0
    assert diff["summary"]["ip_lists_removed"] == 0
    assert diff["summary"]["ip_lists_modified"] == 0
    assert diff["summary"]["services_added"] == 0
    assert diff["summary"]["services_removed"] == 0
    assert diff["summary"]["services_modified"] == 0
    assert diff["summary"]["label_groups_added"] == 0
    assert diff["summary"]["label_groups_removed"] == 0
    assert diff["summary"]["label_groups_modified"] == 0


def test_build_includes_object_layers():
    api = MagicMock()
    api.get_all_rulesets.return_value = []
    api.get_active_rulesets.return_value = []
    api.get_ip_lists.side_effect = lambda pversion="active": {
        "active": [{"href": "/orgs/1/sec_policy/active/ip_lists/5", "name": "L",
                    "ip_ranges": [{"from_ip": "10.0.0.0/8"}], "fqdns": [], "description": ""}],
        "draft": [{"href": "/orgs/1/sec_policy/draft/ip_lists/5", "name": "L",
                   "ip_ranges": [{"from_ip": "10.0.0.0/8"}, {"from_ip": "0.0.0.0/0"}],
                   "fqdns": [], "description": ""}],
    }[pversion]
    api.get_services.side_effect = lambda pversion="active": []
    api.get_label_groups.side_effect = lambda pversion="active": []
    rep = PolicyDiffReport(MagicMock(), api_client=api)
    with patch.object(rep, "_fetch_policy_events", return_value={"draft_events": None}):
        diff = rep.build()
    assert len(diff["ip_list_changes"]) == 1
    assert diff["summary"]["ip_lists_modified"] == 1
    assert diff["summary"]["services_added"] == 0
    assert diff["summary"]["total_changes"] == 1
    assert "risk" in diff["ip_list_changes"].columns


def test_build_object_layers_draft_and_active_fetched():
    api = MagicMock()
    api.get_all_rulesets.return_value = []
    api.get_active_rulesets.return_value = []
    api.get_ip_lists.return_value = []
    api.get_services.return_value = []
    api.get_label_groups.return_value = []
    rep = PolicyDiffReport(MagicMock(), api_client=api)
    with patch.object(rep, "_fetch_policy_events", return_value={"draft_events": None}):
        rep.build()
    for m in (api.get_ip_lists, api.get_services, api.get_label_groups):
        kwargs_seen = {c.kwargs.get("pversion", "active") for c in m.call_args_list}
        assert kwargs_seen == {"active", "draft"}


def test_label_group_members_resolve_via_all_labels():
    api = MagicMock()
    api.get_all_rulesets.return_value = []
    api.get_active_rulesets.return_value = []
    api.get_ip_lists.side_effect = lambda pversion="active": []
    api.get_services.side_effect = lambda pversion="active": []
    api.get_label_groups.side_effect = lambda pversion="active": {
        "active": [{"href": "/orgs/1/sec_policy/active/label_groups/8", "name": "G",
                    "labels": [], "sub_groups": [], "description": ""}],
        "draft": [{"href": "/orgs/1/sec_policy/draft/label_groups/8", "name": "G",
                   "labels": [{"href": "/orgs/1/labels/9"}], "sub_groups": [],
                   "description": ""}],
    }[pversion]
    api.get_all_labels.return_value = [
        {"href": "/orgs/1/labels/9", "key": "role", "value": "web"}]
    rep = PolicyDiffReport(MagicMock(), api_client=api)
    with patch.object(rep, "_fetch_policy_events", return_value={"draft_events": None}):
        diff = rep.build()
    row = diff["label_group_changes"].iloc[0]
    assert "role:web" in row["draft_value"]
    assert "/orgs/1/labels/9" not in row["draft_value"]


def test_attribution_window_is_configurable():
    from src.report.policy_diff_report import PolicyDiffReport

    r = PolicyDiffReport(cm=None, api_client=None, attribution_days=90)
    assert r._attribution_days == 90


def test_attribution_window_default_30():
    from src.report.policy_diff_report import PolicyDiffReport

    r = PolicyDiffReport(cm=None, api_client=None)
    assert r._attribution_days == 30
