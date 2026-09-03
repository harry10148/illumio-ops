"""An executive summary's grade must carry its severity, not just its letter.

The cover already tones the grade chip — a readiness report with grade F shows
a red chip. One page later the executive summary repeats that F as a plain KPI
value in body ink, so the page that exists to be skimmed is the one page that
does not say the grade is bad.

Only the grade is toned. The other KPIs are counts, and colouring a count
implies a judgement the number does not carry.
"""
from __future__ import annotations

import re

from src.report.exporters._exec_summary import render_exec_summary_html


def _mod00(**over):
    base = {"kpis": [
        {"i18n_key": "rpt_readiness_kpi_score", "label": "Score", "value": "28.8"},
        {"i18n_key": "rpt_readiness_kpi_grade", "label": "Grade", "value": "F"},
        {"i18n_key": "rpt_readiness_kpi_ready", "label": "Ready", "value": "0"},
    ]}
    base.update(over)
    return base


def _kpi_block(html: str, label: str) -> str:
    m = re.search(rf'<div class="kpi"[^>]*>(?:(?!</div>).)*?{label}.*?</div>', html, re.S)
    assert m, f"no KPI block for {label}"
    return m.group(0)


def test_grade_kpi_carries_its_tone():
    html = render_exec_summary_html(_mod00(), report_name="Readiness", lang="en")
    assert 'data-tone="crit"' in _kpi_block(html, "Grade")


def test_good_grade_is_toned_ok_not_left_neutral():
    mod = _mod00(kpis=[{"i18n_key": "rpt_readiness_kpi_grade", "label": "Grade", "value": "A"}])
    html = render_exec_summary_html(mod, report_name="Readiness", lang="en")
    assert 'data-tone="ok"' in _kpi_block(html, "Grade")


def test_counts_are_not_toned():
    """Colouring a count implies a judgement the number does not carry."""
    html = render_exec_summary_html(_mod00(), report_name="Readiness", lang="en")
    assert "data-tone" not in _kpi_block(html, "Ready")
    assert "data-tone" not in _kpi_block(html, "Score")


def test_unknown_grade_value_is_left_neutral():
    mod = _mod00(kpis=[{"i18n_key": "rpt_readiness_kpi_grade", "label": "Grade", "value": "?"}])
    html = render_exec_summary_html(mod, report_name="Readiness", lang="en")
    assert "data-tone" not in _kpi_block(html, "Grade")
