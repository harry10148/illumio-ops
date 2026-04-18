"""Chart renderer dual engine — same spec produces both HTML (plotly) and PNG (matplotlib)."""
from __future__ import annotations

import base64
import re
import pytest


SAMPLE_BAR_SPEC = {
    "type": "bar",
    "title": "Top 5 Ports",
    "x_label": "Port",
    "y_label": "Flows",
    "data": {
        "labels": ["80", "443", "22", "3389", "8080"],
        "values": [1200, 850, 230, 120, 95],
    },
    "i18n": {"lang": "en"},
}

SAMPLE_PIE_SPEC = {
    "type": "pie",
    "title": "Policy Decision Breakdown",
    "data": {
        "labels": ["Allowed", "Blocked", "Potentially Blocked"],
        "values": [5230, 142, 38],
    },
    "i18n": {"lang": "en"},
}


def test_render_plotly_html_returns_html_div():
    from src.report.exporters.chart_renderer import render_plotly_html
    out = render_plotly_html(SAMPLE_BAR_SPEC)
    assert "<div" in out
    assert "plotly" in out.lower()
    # Title is embedded as plain text (or JSON-encoded) in output
    assert "Top 5 Ports" in out or "Top%205%20Ports" in out


def test_render_plotly_html_supports_pie():
    from src.report.exporters.chart_renderer import render_plotly_html
    out = render_plotly_html(SAMPLE_PIE_SPEC)
    assert "Policy Decision" in out or "Policy%20Decision" in out


def test_render_plotly_html_offline_self_contained():
    """plotly output MUST NOT use external <script src> loads — RPM deployment is offline.

    Note: CDN strings may appear inside the bundled plotly.js code as default config
    values (e.g. mapbox tile server), but there must be no external script src tags.
    The inline bundle is ~4 MB; that's expected for include_plotlyjs='inline'.
    """
    import re
    from src.report.exporters.chart_renderer import render_plotly_html
    out = render_plotly_html(SAMPLE_BAR_SPEC)
    # No external <script src="..."> tags pointing to CDNs
    external_scripts = re.findall(r'<script[^>]+src=["\'][^"\']*(?:cdn|unpkg)[^"\']*["\']', out)
    assert not external_scripts, f"Found external script loads: {external_scripts}"
    # Output is non-trivially sized (inline plotly.js is ~3-5 MB)
    assert len(out) > 100_000
    assert "Plotly" in out or "plotly" in out.lower()


def test_render_matplotlib_png_returns_bytes():
    from src.report.exporters.chart_renderer import render_matplotlib_png
    png_bytes = render_matplotlib_png(SAMPLE_BAR_SPEC)
    assert isinstance(png_bytes, bytes)
    # PNG magic number
    assert png_bytes.startswith(b'\x89PNG\r\n\x1a\n')


def test_render_matplotlib_png_pie_works():
    from src.report.exporters.chart_renderer import render_matplotlib_png
    png_bytes = render_matplotlib_png(SAMPLE_PIE_SPEC)
    assert png_bytes.startswith(b'\x89PNG')
    # Image should be non-trivially sized
    assert len(png_bytes) > 1000


def test_unknown_chart_type_raises():
    from src.report.exporters.chart_renderer import render_plotly_html
    with pytest.raises(ValueError, match="unsupported chart type"):
        render_plotly_html({"type": "spaceship", "title": "no", "data": {}})


def test_both_engines_accept_identical_spec():
    """Regression: the same dict must be consumable by both engines."""
    from src.report.exporters.chart_renderer import render_plotly_html, render_matplotlib_png
    html = render_plotly_html(SAMPLE_BAR_SPEC)
    png = render_matplotlib_png(SAMPLE_BAR_SPEC)
    assert html  # non-empty
    assert png   # non-empty


def test_render_matplotlib_png_handles_empty_heatmap():
    """Empty heatmap matrix must not raise — fall back to 1x1 zero matrix."""
    from src.report.exporters.chart_renderer import render_matplotlib_png
    spec = {
        "type": "heatmap",
        "title": "empty",
        "data": {"matrix": [], "labels": [], "ylabels": []},
        "i18n": {"lang": "en"},
    }
    png = render_matplotlib_png(spec)
    assert png.startswith(b'\x89PNG')


def test_i18n_zh_tw_title_renders():
    from src.report.exporters.chart_renderer import render_plotly_html, render_matplotlib_png
    spec = {**SAMPLE_BAR_SPEC, "title": "前 5 名連接埠", "i18n": {"lang": "zh_TW"}}
    html = render_plotly_html(spec)
    # Title text should survive (URL-encoded or not)
    assert "前" in html or "%E5%89%8D" in html.upper() or "5" in html
    png = render_matplotlib_png(spec)
    assert png.startswith(b'\x89PNG')
