# tests/test_html_exporter_static_charts.py
"""HTML reports embed static SVG charts, not plotly.js."""
from src.report.exporters.html_exporter import _render_chart_for_html

BAR_SPEC = {
    "type": "bar",
    "title": "Top Ports",
    "data": {"labels": ["443", "80"], "values": [12, 8]},
}


def test_chart_html_is_static_svg():
    html = _render_chart_for_html(BAR_SPEC, lang="en")
    assert "<svg" in html
    assert "plotly" not in html.lower()


def test_none_spec_renders_empty():
    assert _render_chart_for_html(None, lang="en") == ""


def test_invalid_spec_degrades_gracefully():
    # 不支援的 type 不得讓整份報表炸掉 — 回傳空字串並繼續
    assert _render_chart_for_html({"type": "sankey", "data": {}}, lang="en") == ""
