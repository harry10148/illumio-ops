"""Modal 物件庫（object-browser.js）的靜態契約，樣式同 test_component_object_filter_bar.py。"""
import json
from pathlib import Path

_JS = Path("src/static/js/object-browser.js")
_FB = Path("src/static/js/filter-bar.js")
_INDEX = Path("src/templates/index.html")
_EN = Path("src/i18n_en.json")
_ZH = Path("src/i18n_zh_TW.json")


def test_object_browser_exists_and_exports():
    src = _JS.read_text(encoding="utf-8")
    assert "window.openObjectBrowser" in src
    assert "onclick=" not in src  # CSP


def test_object_browser_modal_markup_present():
    html = _INDEX.read_text(encoding="utf-8")
    assert 'id="modal-obj-browser"' in html
    assert "object-browser.js" in html


def test_filter_bar_has_browser_entry():
    src = _FB.read_text(encoding="utf-8")
    assert "gui_fb_browse_all" in src and "openObjectBrowser" in src


def test_object_browser_i18n_bilingual():
    en = json.loads(_EN.read_text(encoding="utf-8"))
    zh = json.loads(_ZH.read_text(encoding="utf-8"))
    for k in ("gui_fb_browse_all", "gui_ob_title", "gui_ob_add", "gui_ob_selected",
              "gui_ob_search_ph", "gui_ob_page", "gui_ob_dir_hint"):
        assert k in en and k in zh
