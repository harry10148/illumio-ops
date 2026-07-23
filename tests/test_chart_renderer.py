"""Chart renderer — chart spec produces PNG (matplotlib) and inline SVG output."""
from __future__ import annotations

import base64
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
    from src.report.exporters.chart_renderer import render_matplotlib_png
    with pytest.raises(ValueError, match="unsupported chart type"):
        render_matplotlib_png({"type": "spaceship", "title": "no", "data": {}})


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
    from src.report.exporters.chart_renderer import render_matplotlib_png
    spec = {**SAMPLE_BAR_SPEC, "title": "前 5 名連接埠", "i18n": {"lang": "zh_TW"}}
    png = render_matplotlib_png(spec)
    assert png.startswith(b'\x89PNG')


def test_pie_autopct_filter():
    """Default behaviour: hide only exactly-zero slices, render everything else."""
    from src.report.exporters.chart_renderer import _pie_autopct
    # Default threshold (0.0) — only literal zero hidden
    assert _pie_autopct(0.0) == ""
    assert _pie_autopct(0.04) == "0.0%"     # rounds to 0 but not literally zero
    assert _pie_autopct(0.4) == "0.4%"
    assert _pie_autopct(1.0) == "1.0%"
    assert _pie_autopct(93.4) == "93.4%"
    # Caller can opt into higher threshold
    assert _pie_autopct(0.5, threshold=1.0) == ""
    assert _pie_autopct(1.5, threshold=1.0) == "1.5%"


def test_filter_existing_font_families_keeps_sans_serif_safety_net():
    from src.report.exporters.chart_renderer import _filter_existing_font_families
    # 'sans-serif' is a generic family name matplotlib always honours.
    out = _filter_existing_font_families(["DefinitelyNotAFontXYZ", "sans-serif"])
    assert out[-1] == "sans-serif"
    assert "DefinitelyNotAFontXYZ" not in out


def test_filter_existing_font_families_keeps_real_font_when_present():
    """If a known matplotlib default like DejaVu Sans is installed, it survives."""
    from src.report.exporters.chart_renderer import _filter_existing_font_families
    out = _filter_existing_font_families(["DejaVu Sans", "sans-serif"])
    # DejaVu Sans is bundled with matplotlib itself, so always present.
    assert "DejaVu Sans" in out


def test_render_matplotlib_resolves_title_key_for_lang(monkeypatch):
    """If chart_spec carries title_key, the renderer resolves it via STRINGS+lang."""
    from src.report.exporters import chart_renderer
    from src.report.exporters import report_i18n
    # monkeypatch.setitem ensures the synthetic entry is removed after the test
    monkeypatch.setitem(
        report_i18n.STRINGS,
        "rpt_chart_test_title",
        {"en": "English Title", "zh_TW": "中文標題"},
    )
    spec = {
        "type": "bar",
        "title": "English Title",        # backward-compat literal
        "title_key": "rpt_chart_test_title",
        "data": {"labels": ["a"], "values": [1]},
    }
    out_en = chart_renderer._resolve_chart_text(spec, "title", lang="en")
    out_zh = chart_renderer._resolve_chart_text(spec, "title", lang="zh_TW")
    assert out_en == "English Title"
    assert out_zh == "中文標題"


def test_render_matplotlib_falls_back_to_literal_when_key_missing():
    from src.report.exporters import chart_renderer
    spec = {"type": "bar", "title": "Plain Title", "data": {"labels": [], "values": []}}
    assert chart_renderer._resolve_chart_text(spec, "title", lang="zh_TW") == "Plain Title"


def test_bar_many_labels_rotates_xticks():
    """>6 categories must angle x tick labels so they don't collide (audit
    event-type ranking regression). Few-label charts stay horizontal."""
    import matplotlib
    matplotlib.use("Agg")
    from src.report.exporters.chart_renderer import _build_matplotlib_figure
    many = {"type": "bar", "title": "T", "x_label": "x", "y_label": "y",
            "data": {"labels": [f"event_type_{i}" for i in range(10)],
                     "values": list(range(10))}, "i18n": {"lang": "en"}}
    fig = _build_matplotlib_figure(many)
    rot = {round(lbl.get_rotation()) for lbl in fig.axes[0].get_xticklabels()}
    matplotlib.pyplot.close(fig)
    assert 30 in rot

    fig2 = _build_matplotlib_figure(SAMPLE_BAR_SPEC)  # 5 labels
    rot2 = {round(lbl.get_rotation()) for lbl in fig2.axes[0].get_xticklabels()}
    matplotlib.pyplot.close(fig2)
    assert rot2 == {0}


SEMANTIC_PIE_SPEC = {
    "type": "pie",
    "title": "Policy Decision Breakdown",
    "data": {
        "labels": ["Allowed", "Blocked", "Potentially Blocked", "Unknown"],
        "values": [208, 1, 11642, 190218],
    },
    "i18n": {"lang": "en"},
}


def test_pie_semantic_colors_fixed_by_label():
    """判定圓餅顏色必須依語意固定（allowed 綠/blocked 紅/PB 橘/unknown 灰），
    不得依切片順序輪替——順序色曾把 98% 未覆蓋流量畫成安全綠。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from src.report.exporters.chart_renderer import _build_matplotlib_figure
    fig = _build_matplotlib_figure(SEMANTIC_PIE_SPEC, lang="en")
    try:
        ax = fig.axes[0]
        wedges = [p for p in ax.patches]
        got = [w.get_facecolor() for w in wedges]
        from matplotlib.colors import to_rgba
        assert got[0] == to_rgba("#16a34a")   # allowed
        assert got[1] == to_rgba("#dc2626")   # blocked
        assert got[2] == to_rgba("#f59e0b")   # potentially blocked
        assert got[3] == to_rgba("#6b7280")   # unknown
    finally:
        plt.close(fig)


def test_pie_small_slices_move_to_legend():
    """<3% 切片的切片名與百分比標籤留白（防重疊），完整資訊移到圖例。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from src.report.exporters.chart_renderer import _build_matplotlib_figure
    fig = _build_matplotlib_figure(SEMANTIC_PIE_SPEC, lang="en")
    try:
        ax = fig.axes[0]
        texts = [t.get_text() for t in ax.texts]
        # Allowed(0.1%)/Blocked(0.0%) 切片名不得出現在切片標籤上
        assert "Allowed" not in texts
        assert "Blocked" not in texts
        # 大切片仍就地標示
        assert "Unknown" in texts
        legend = ax.get_legend()
        assert legend is not None
        legend_texts = " ".join(t.get_text() for t in legend.get_texts())
        assert "Allowed" in legend_texts and "208" in legend_texts
        assert "Blocked" in legend_texts
    finally:
        plt.close(fig)


def test_pie_unknown_labels_keep_default_palette():
    """任一 label 不在語意表中 → 整組維持 matplotlib 預設循環（不混用）。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import to_rgba
    from src.report.exporters.chart_renderer import _build_matplotlib_figure
    spec = {"type": "pie", "title": "x",
            "data": {"labels": ["Alpha", "Beta"], "values": [60, 40]},
            "i18n": {"lang": "en"}}
    fig = _build_matplotlib_figure(spec, lang="en")
    try:
        ax = fig.axes[0]
        got = [w.get_facecolor() for w in ax.patches]
        assert got[0] != to_rgba("#16a34a")
    finally:
        plt.close(fig)
