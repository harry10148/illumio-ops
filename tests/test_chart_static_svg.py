"""Static SVG chart rendering (shares the matplotlib builder with PNG)."""
import pytest

from src.report.exporters.chart_renderer import render_matplotlib_png, render_matplotlib_svg

BAR_SPEC = {
    "type": "bar",
    "title": "Top Ports",
    "x_label": "Port",
    "y_label": "Flows",
    "data": {"labels": ["443", "80", "22"], "values": [120, 80, 15]},
}


def test_svg_output_is_svg_markup():
    svg = render_matplotlib_svg(BAR_SPEC, lang="en")
    assert isinstance(svg, str)
    assert "<svg" in svg
    assert "</svg>" in svg


def test_svg_unsupported_type_raises():
    with pytest.raises(ValueError):
        render_matplotlib_svg({"type": "sankey", "data": {}}, lang="en")


def test_png_still_works_after_refactor():
    png = render_matplotlib_png(BAR_SPEC, lang="en")
    assert isinstance(png, (bytes, bytearray))
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
