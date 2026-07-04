"""Tests for the policy-diff HTML exporter."""
from __future__ import annotations

import os
from pathlib import Path

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


def test_shell_has_print_only_aside_and_main(tmp_path):
    """spec N1: policy_diff now carries a print-only aside (button, no nav list)
    alongside the other exporters, so the shell has two children: the
    .report-toc aside and .report-main. The shared CSS still carries the
    :only-child full-span rule (for any TOC-less exporter), which remains
    present in the embedded stylesheet regardless."""
    html = open(PolicyDiffHtmlExporter(_diff(), lang="en").export(str(tmp_path)),
                encoding="utf-8").read()
    assert '<div class="report-shell">' in html
    assert '<aside class="report-toc screen-only">' in html
    assert '<main class="report-main">' in html
    assert ".report-shell > .report-main:only-child { grid-column: 1 / -1; }" in html


def test_wide_table_wrapped_for_horizontal_scroll(tmp_path):
    """Regression: the 9-column diff table must sit inside .report-table-wrap
    (overflow:auto) so a wide table scrolls internally instead of pushing the
    whole page into horizontal scroll. Also lets TABLE_JS find its wrapper."""
    html = open(PolicyDiffHtmlExporter(_diff(), lang="en").export(str(tmp_path)),
                encoding="utf-8").read()
    assert '<div class="report-table-wrap"><table class="report-table">' in html


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


def _object_results():
    ipl = pd.DataFrame([
        {"risk": "HIGH", "change_type": "modified", "object_kind": "ip_list",
         "name": "Corp-Nets", "object_id": "5", "field": "ip_ranges",
         "draft_value": "0.0.0.0/0, 10.0.0.0/8", "active_value": "10.0.0.0/8",
         "scope_expanded": True, "last_actor": "alice", "last_changed": "t", "last_event": "ip_list.update"},
    ])
    return {"ruleset_changes": pd.DataFrame(), "rule_changes": pd.DataFrame(),
            "ip_list_changes": ipl, "service_changes": pd.DataFrame(),
            "label_group_changes": pd.DataFrame(),
            "summary": {"rulesets_added": 0, "rulesets_removed": 0, "rulesets_modified": 0,
                        "rules_added": 0, "rules_removed": 0, "rules_modified": 0,
                        "ip_lists_added": 0, "ip_lists_removed": 0, "ip_lists_modified": 1,
                        "services_added": 0, "services_removed": 0, "services_modified": 0,
                        "label_groups_added": 0, "label_groups_removed": 0,
                        "label_groups_modified": 0, "total_changes": 1}}


def test_object_sections_rendered(tmp_path):
    path = PolicyDiffHtmlExporter(_object_results(), lang="en").export(str(tmp_path))
    html = Path(path).read_text(encoding="utf-8")
    assert 'id="ip-list-changes"' in html
    assert 'id="service-changes"' in html
    assert 'id="label-group-changes"' in html
    assert "Corp-Nets" in html
    assert 'class="pd-risk-high"' in html
    # 空的 service 章顯示 no-changes note 而非空表（用實際 div 開頭 tag 計數，避開
    # 共用 CSS/JS 字面內容裡本來就含有的 "report-table-wrap" 字串）
    assert html.count('<div class="report-table-wrap">') == 1


def test_object_section_headers_localized(tmp_path):
    path = PolicyDiffHtmlExporter(_object_results(), lang="zh_TW").export(str(tmp_path))
    html = Path(path).read_text(encoding="utf-8")
    assert "[MISSING" not in html
    assert "IP List" in html  # glossary：物件型別名保持英文
    # 內部欄位 scope_expanded / object_kind 不出現在表頭
    assert "scope_expanded" not in html
    assert "object_kind" not in html
