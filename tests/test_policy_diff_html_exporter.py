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


def test_no_toc_shell_main_spans_full_width(tmp_path):
    """Regression: exporters without a TOC sidebar render <main> as the only
    shell child, so it lands in the 240px TOC grid track and gets squished.
    The shared CSS must carry the :only-child full-span rule that fixes it."""
    html = open(PolicyDiffHtmlExporter(_diff(), lang="en").export(str(tmp_path)),
                encoding="utf-8").read()
    # main is the only child of the shell (no <aside class="report-toc">)
    assert '<div class="report-shell"><main class="report-main">' in html
    assert 'class="report-toc"' not in html
    # the CSS rule that un-squishes a TOC-less main must be present
    assert ".report-shell > .report-main:only-child { grid-column: 1 / -1; }" in html


def test_blank_attribution_renders_em_dash_with_tooltip(tmp_path):
    """Empty last_actor / last_changed cells render — with explanatory tooltip."""
    rs = pd.DataFrame([{
        "change_type": "added", "ruleset_name": "RS-B", "ruleset_id": "2",
        "field": "name", "draft_value": "RS-B", "active_value": "",
        "last_actor": "", "last_changed": "",
        "last_event": "",
    }])
    diff = {"ruleset_changes": rs, "rule_changes": pd.DataFrame(),
            "summary": {"rulesets_added": 1, "rulesets_removed": 0, "rulesets_modified": 0,
                        "rules_added": 0, "rules_removed": 0, "rules_modified": 0,
                        "total_changes": 1}}
    html = open(PolicyDiffHtmlExporter(diff, lang="en").export(str(tmp_path)),
                encoding="utf-8").read()
    assert "—" in html
    assert 'title="' in html
    # tooltip should contain the attribution note text
    assert "Attribution" in html or "attribution" in html.lower()
