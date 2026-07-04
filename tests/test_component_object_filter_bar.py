"""Static assertions for the filter-bar pill component (Phase 3 Task 2).

Mirrors tests/test_component_filter_bar.py's pattern: read the shipped
files as text and regex/substring assert rather than executing the JS
(no JS runtime in the Python test suite).
"""
from pathlib import Path

_JS = Path("src/static/js/filter-bar.js")
_CSS = Path("src/static/css/app.css")
_EN = Path("src/i18n_en.json")
_ZH = Path("src/i18n_zh_TW.json")
_INDEX = Path("src/templates/index.html")


def test_filter_bar_js_exists_and_exports_factory():
    src = _JS.read_text(encoding="utf-8")
    assert "window.createFilterBar" in src


def test_filter_bar_handlers_on_window():
    src = _JS.read_text(encoding="utf-8")
    for fn in ("_objfbInput", "_objfbKeydown", "_objfbPillClick", "_objfbAddDir"):
        assert f"window.{fn}" in src, f"{fn} must be on window for CSP dispatcher"


def test_filter_bar_no_inline_onclick():
    src = _JS.read_text(encoding="utf-8")
    # 元件不得用 inline on-click 屬性（CSP）；事件走 data-action/data-on-* 委派
    assert "onclick=" not in src


def test_filter_bar_css_class_present():
    css = _CSS.read_text(encoding="utf-8")
    assert ".objfb-bar" in css
    assert ".objfb-pill" in css


def test_filter_bar_i18n_keys_present():
    import json
    en = json.loads(_EN.read_text(encoding="utf-8"))
    zh = json.loads(_ZH.read_text(encoding="utf-8"))
    for k in ("gui_fb_placeholder", "gui_fb_add_ipcidr", "gui_fb_any_slow",
              "gui_fb_offline", "gui_fb_or"):
        assert k in en and k in zh, f"{k} missing in i18n"


def test_filter_bar_loaded_in_index_html():
    html = _INDEX.read_text(encoding="utf-8")
    assert "filter-bar.js" in html


def test_filter_bar_serialize_deserialize_present():
    src = _JS.read_text(encoding="utf-8")
    assert "function _objfbSerialize(state)" in src
    assert "function _objfbDeserialize(state, dict)" in src


def test_filter_bar_or_marker_for_same_key_labels():
    src = _JS.read_text(encoding="utf-8")
    assert "objfb-or" in src


def test_filter_bar_any_dir_distinct_style_and_hint():
    src = _JS.read_text(encoding="utf-8")
    assert "objfb-any" in src
    assert "gui_fb_any_slow" in src


def test_filter_bar_uses_suggest_endpoint():
    src = _JS.read_text(encoding="utf-8")
    assert "/api/filter-objects/suggest" in src


def test_filter_bar_uses_debounce_and_abort():
    src = _JS.read_text(encoding="utf-8")
    assert "AbortController" in src
    assert "debounce" in src


def test_filter_bar_handles_offline():
    src = _JS.read_text(encoding="utf-8")
    # 消費 workload 的 pce_unreachable error 欄
    assert "pce_unreachable" in src


def test_traffic_analyzer_modal_mounts_filter_bar():
    """Phase 3 Task 4: qt-src/qt-dst/qt-any-*/qt-ex* 分欄已換成單一 FilterBar 掛載點。"""
    html = _INDEX.read_text(encoding="utf-8")
    assert 'id="qt-filter-bar"' in html
    for removed_id in (
        "qt-src", "qt-dst", "qt-any-label", "qt-any-ip",
        "qt-exsrc", "qt-exdst", "qt-ex-any-label", "qt-ex-any-ip",
    ):
        assert f'id="{removed_id}"' not in html, f"{removed_id} should be removed from modal-qt-filters"
    # port/proto/PD radio 保留（不屬 FilterBar 範圍）
    assert 'id="qt-port"' in html
    assert 'id="qt-proto"' in html
    assert 'name="qt-pd-radio"' in html


def test_quarantine_js_uses_filter_bar_for_traffic_analyzer():
    js = Path("src/static/js/quarantine.js").read_text(encoding="utf-8")
    assert "createFilterBar(document.getElementById('qt-filter-bar')" in js
    assert "_ensureQtFilterBar().getFilters()" in js
    for removed_id in ("qt-src", "qt-dst", "qt-exsrc", "qt-exdst", "qt-any-label", "qt-any-ip"):
        assert f"getElementById('{removed_id}')" not in js
