"""Readiness HTML exporter — sections, truncation, print affordance."""
from __future__ import annotations

import os

import pandas as pd

from src.report.readiness_report import ReadinessResult
from src.report.exporters.readiness_html_exporter import ReadinessHtmlExporter


def _result(long_action: str = "act"):
    queue_df = pd.DataFrame([{
        "app_display": "appA (prod)", "app_env_key": "appa|prod",
        "readiness_score": 91.0, "grade": "A", "current_mode": "full×2",
        "blocking_factor": "Ringfence Maturity", "blocking_factor_key": "ringfence_maturity",
        "recommended_action": long_action, "flow_count": 6, "pb_uncovered_count": 0,
    }])
    factor_table = pd.DataFrame([{"Factor": "Policy Coverage", "Weight": 35,
                                  "Score": 30.0, "Ratio %": 85.0}])
    recs = pd.DataFrame([{"Priority": "P2", "App (Env)": "appB (prod)",
                          "App Env Key": "appb|prod", "Issue": "Enforcement Gap",
                          "Action": "Move to enforcement", "Action Code": "MOVE_TO_ENFORCEMENT",
                          "Severity": "HIGH"}])
    readiness = {"total_score": 78.5, "grade": "B",
                 "factor_table": factor_table, "recommendations": recs,
                 "enforcement_mode_distribution": {"full": 2}}
    return ReadinessResult(
        record_count=12,
        module_results={"readiness": readiness, "queue_df": queue_df,
                        "kpis": [{"i18n_key": "rpt_readiness_kpi_score",
                                  "label": "Readiness Score", "value": 78.5}],
                        "_trend_deltas": []},
        date_range=("2026-07-01", "2026-07-08"))


def _render(tmp_path, result, lang="en"):
    path = ReadinessHtmlExporter(result, lang=lang).export(str(tmp_path))
    with open(path, encoding="utf-8") as fh:
        return path, fh.read()


def test_export_writes_prefixed_file_with_sections(tmp_path):
    path, html = _render(tmp_path, _result())
    assert os.path.basename(path).startswith("Illumio_Readiness_Report_")
    for anchor in ("readiness-summary", "readiness-queue", "readiness-factors",
                   "readiness-recommendations", "readiness-trend"):
        assert f'id="{anchor}"' in html


def test_print_button_present(tmp_path):
    _, html = _render(tmp_path, _result())
    assert "window.print()" in html and "print-btn" in html


def test_long_action_truncated_with_title_attr(tmp_path):
    long_action = "x" * 200
    _, html = _render(tmp_path, _result(long_action=long_action))
    assert long_action not in html.replace(f'title="{long_action}"', "")
    assert f'title="{long_action}"' in html
    assert ("x" * 159 + "…") in html


def test_trend_first_run_note(tmp_path):
    _, html = _render(tmp_path, _result())
    from src.i18n import t
    assert t("rpt_readiness_trend_first_run", lang="en") in html


def test_zh_render_has_no_missing_keys(tmp_path):
    _, html = _render(tmp_path, _result(), lang="zh_TW")
    assert "rpt_readiness_sec_queue" not in html  # key leaked = missing translation
