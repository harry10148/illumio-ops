"""Rendering tests for RuleHitCountHtmlExporter (sections, notes, truncation)."""
from __future__ import annotations

import os
import tempfile
import unittest

import pandas as pd

from src.report.rule_hit_count_generator import RuleHitCountResult
from src.report.exporters.rule_hit_count_html_exporter import RuleHitCountHtmlExporter


def _row(**over):
    base = {"rule_href": "/r/1", "ruleset": "RS-A", "rule_no": 1, "rule_id": "1",
            "rule_type": "Allow", "description": "d", "consumers": "c",
            "providers": "p", "services": "s", "enabled": True,
            "hit_count": 5, "days_since_last_hit": "3",
            "last_hit_at": "2026-06-28T09:14:23Z",
            "last_updated_by": "admin@lab.local",
            "last_updated_at": "2026-05-01T00:00:00Z"}
    base.update(over)
    return base


def _result(rows, enrich_failed=False, source="native"):
    df = pd.DataFrame(rows)
    hit_df = df[df["hit_count"] > 0] if len(df) else df
    unused_df = df[df["hit_count"] == 0] if len(df) else df
    return RuleHitCountResult(
        record_count=len(rows),
        date_range=("2026-06-01", "2026-07-01"),
        source=source,
        module_results={
            "kpis": {"total_rules": len(rows), "hit_rules": len(hit_df),
                     "unused_rules": len(unused_df), "hit_rate_pct": 50.0,
                     "total_hits": int(df["hit_count"].sum()) if len(df) else 0},
            "hit_df": hit_df, "unused_df": unused_df, "cleanup_df": unused_df,
            "enrich_failed": enrich_failed,
        },
        dataframe=df,
    )


class TestExporter(unittest.TestCase):
    def test_renders_sections_and_semantic_notes(self):
        with tempfile.TemporaryDirectory() as td:
            path = RuleHitCountHtmlExporter(_result([_row()]), lang="en").export(td)
            self.assertIn("Illumio_Rule_Hit_Count_Report_", os.path.basename(path))
            html = open(path, encoding="utf-8").read()
        self.assertIn("RS-A", html)
        self.assertIn("Cleanup Candidates", html)
        self.assertIn("VEN-measured", html)          # rpt_rhc_note_semantics
        self.assertIn("at most 100 rules", html)     # rpt_rhc_note_optimization
        self.assertIn("90 days", html)               # rpt_rhc_note_retention

    def test_csv_source_shows_window_note(self):
        with tempfile.TemporaryDirectory() as td:
            path = RuleHitCountHtmlExporter(_result([_row()], source="csv"),
                                            lang="en").export(td)
            html = open(path, encoding="utf-8").read()
        self.assertIn("Start/End Date", html)        # rpt_rhc_note_csv_window

    def test_enrich_failed_note_shown(self):
        with tempfile.TemporaryDirectory() as td:
            path = RuleHitCountHtmlExporter(_result([_row()], enrich_failed=True),
                                            lang="en").export(td)
            html = open(path, encoding="utf-8").read()
        self.assertIn("enrichment failed", html)

    def test_long_cell_truncated_with_full_value_in_title(self):
        long_val = "label-" + "x" * 300
        with tempfile.TemporaryDirectory() as td:
            path = RuleHitCountHtmlExporter(
                _result([_row(consumers=long_val)]), lang="en").export(td)
            html = open(path, encoding="utf-8").read()
        self.assertIn("…", html)
        self.assertIn(long_val, html)                 # full value survives in title=
        self.assertNotIn(long_val + "</td>", html)    # cell text itself is cut

    def test_empty_section_shows_note(self):
        with tempfile.TemporaryDirectory() as td:
            path = RuleHitCountHtmlExporter(_result([]), lang="en").export(td)
            html = open(path, encoding="utf-8").read()
        self.assertIn("No rules in this section.", html)

    def test_last_hit_at_rendered_in_full_and_governance_columns_hidden(self):
        # last_hit_at：固定長度時戳，比照 days_since_last_hit 整值呈現（不進
        # _TRUNC_COLS 截斷路徑；CLAUDE.md：截斷必須明確，此欄無截斷需要）。
        # last_updated_by/last_updated_at：CSV pass-through only，HTML 不顯示。
        with tempfile.TemporaryDirectory() as td:
            path = RuleHitCountHtmlExporter(_result([_row()]), lang="en").export(td)
            html = open(path, encoding="utf-8").read()
        self.assertIn("Timestamp of Last Hit", html)            # 表頭 i18n
        self.assertIn(">2026-06-28T09:14:23Z</td>", html)        # 整值、無截斷
        self.assertNotIn("admin@lab.local", html)                # 治理欄不進 HTML


if __name__ == "__main__":
    unittest.main()


def test_hit_metrics_columns_precede_long_text_columns():
    """命中量測欄必須排在 consumers 等長文字欄之前——主指標曾被推出
    可視範圍（2026-07-23 視覺實檢）。"""
    from src.report.exporters.rule_hit_count_html_exporter import _COLS
    assert _COLS.index("hit_count") < _COLS.index("consumers")
    assert _COLS.index("days_since_last_hit") < _COLS.index("consumers")
    assert _COLS.index("last_hit_at") < _COLS.index("consumers")
