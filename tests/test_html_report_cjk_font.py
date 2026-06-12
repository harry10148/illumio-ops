"""Verify zh_TW chart spec is properly embedded (no encoding corruption in chart data)."""


def test_zh_tw_html_report_has_no_tofu():
    """Check that a zh_TW chart spec renders to a PNG without errors.

    The bundled Noto Sans CJK TC font (registered at import) lets the
    matplotlib renderer draw Chinese title/labels without raising; we verify
    only that a non-trivial PNG is produced.
    """
    from src.report.exporters.chart_renderer import render_matplotlib_png
    spec = {
        "type": "bar",
        "title": "連接埠 Top 5",
        "x_label": "連接埠",
        "y_label": "流量",
        "data": {"labels": ["80", "443", "22"], "values": [10, 5, 2]},
        "i18n": {"lang": "zh_TW"},
    }
    png = render_matplotlib_png(spec)
    # PNG is binary — can't inspect text, but ensure non-trivial size
    assert len(png) > 1000


def test_chart_renderer_loads_bundled_cjk_font():
    """The bundled Noto Sans CJK TC must be registered with matplotlib so
    chart PNGs render Chinese glyphs without falling back to glyph-missing
    boxes (the 豆腐 problem)."""
    import src.report.exporters.chart_renderer  # noqa: F401 — triggers font load
    from matplotlib import font_manager
    families = {f.name for f in font_manager.fontManager.ttflist}
    assert "Noto Sans CJK TC" in families, (
        "bundled NotoSansCJKtc-Regular.otf was not registered with matplotlib"
    )
