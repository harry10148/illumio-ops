"""Operations dropdown menu must exist, be initially hidden, and have
a toggle handler registered in the event dispatcher."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "src" / "templates" / "index.html"
ACTIONS_JS = ROOT / "src" / "static" / "js" / "actions.js"
CSS = ROOT / "src" / "static" / "css" / "app.css"
EN = ROOT / "src" / "i18n_en.json"
ZH = ROOT / "src" / "i18n_zh_TW.json"


def test_operations_button_exists() -> None:
    html = INDEX.read_text(encoding="utf-8")
    assert 'data-action="hdrMenuToggle"' in html
    assert 'aria-haspopup="menu"' in html


def test_dropdown_panel_initially_hidden() -> None:
    html = INDEX.read_text(encoding="utf-8")
    m = re.search(r'<div[^>]*id="hdr-menu-panel"[^>]*>', html)
    assert m, "hdr-menu-panel container missing"
    assert "hidden" in m.group(0)


def test_dispatcher_registers_handler() -> None:
    js = ACTIONS_JS.read_text(encoding="utf-8")
    assert "function hdrMenuToggle" in js
    assert "function hdrMenuClose" in js


def test_css_has_hdr_menu_rules() -> None:
    css = CSS.read_text(encoding="utf-8")
    assert ".hdr-menu" in css


def test_i18n_operations_label() -> None:
    en = json.loads(EN.read_text(encoding="utf-8"))
    zh = json.loads(ZH.read_text(encoding="utf-8"))
    assert en.get("gui_hdr_operations") == "Operations"
    assert zh.get("gui_hdr_operations") == "操作"
