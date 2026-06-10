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
