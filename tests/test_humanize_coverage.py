"""Regression: key display paths must use humanize helpers, not raw format."""

from __future__ import annotations

from pathlib import Path


def test_gui_templates_use_human_filters():
    html = Path("src/templates/index.html").read_text(encoding="utf-8")
    assert html.count("| human_time_ago") >= 2, "GUI not using human_time_ago filter"
    assert html.count("| human_number") >= 2, "GUI not using human_number filter"


def test_html_exporters_use_humanize():
    for path in (
        "src/report/exporters/html_exporter.py",
        "src/report/exporters/audit_html_exporter.py",
        "src/report/exporters/ven_html_exporter.py",
        "src/report/exporters/policy_usage_html_exporter.py",
    ):
        src = Path(path).read_text(encoding="utf-8")
        assert "human_" in src, f"{path}: no humanize_ext usage detected"


def test_dashboard_js_uses_humanize_helper():
    js = Path("src/static/js/dashboard.js").read_text(encoding="utf-8")
    assert "humanTimeAgo" in js, "dashboard.js missing humanTimeAgo helper"
