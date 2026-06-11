"""Tests for the policy-diff HTML exporter."""
from __future__ import annotations

import os

import pandas as pd

from src.report.exporters.policy_diff_html_exporter import PolicyDiffHtmlExporter


def _diff():
    rs = pd.DataFrame([{
        "change_type": "modified", "ruleset_name": "RS-A", "ruleset_id": "1",
        "field": "enabled", "draft_value": "False", "active_value": "True",
        "last_actor": "bob", "last_changed": "2026-06-05T12:00:00Z",
        "last_event": "rule_set.update",
    }])
    rule = pd.DataFrame(columns=["change_type", "ruleset_name", "rule_id", "field",
                                 "draft_value", "active_value",
                                 "last_actor", "last_changed", "last_event"])
    return {"ruleset_changes": rs, "rule_changes": rule,
            "summary": {"rulesets_added": 0, "rulesets_removed": 0, "rulesets_modified": 1,
                        "rules_added": 0, "rules_removed": 0, "rules_modified": 0,
                        "total_changes": 1}}


def test_exports_html_file_with_content(tmp_path):
    path = PolicyDiffHtmlExporter(_diff(), lang="en").export(str(tmp_path))
    assert os.path.isfile(path)
    assert path.endswith(".html")
    html = open(path, encoding="utf-8").read()
    assert "RS-A" in html
    assert "bob" in html        # attribution rendered
    assert "modified" in html.lower()


def test_no_changes_still_produces_report(tmp_path):
    empty = {"ruleset_changes": pd.DataFrame(), "rule_changes": pd.DataFrame(),
             "summary": {"rulesets_added": 0, "rulesets_removed": 0, "rulesets_modified": 0,
                         "rules_added": 0, "rules_removed": 0, "rules_modified": 0,
                         "total_changes": 0}}
    path = PolicyDiffHtmlExporter(empty, lang="en").export(str(tmp_path))
    assert os.path.isfile(path)


def test_table_headers_are_localized(tmp_path):
    """Diff-table <th> headers use i18n labels, not raw DataFrame column names."""
    html = open(PolicyDiffHtmlExporter(_diff(), lang="en").export(str(tmp_path)),
                encoding="utf-8").read()
    for label in ("Change", "Field", "DRAFT value", "ACTIVE value",
                  "Operator", "Ruleset"):
        assert f"<th>{label}</th>" in html, label
    for raw in ("change_type", "draft_value", "active_value", "last_actor",
                "last_changed", "ruleset_name"):
        assert f"<th>{raw}</th>" not in html, raw
    assert "[MISSING" not in html
