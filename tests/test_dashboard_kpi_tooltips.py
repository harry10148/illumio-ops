"""The d-unknown / d-suppressed story-stats should carry tooltip attributes
explaining their meaning, with i18n-localised text."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "src" / "templates" / "index.html"
EN = ROOT / "src" / "i18n_en.json"
ZH = ROOT / "src" / "i18n_zh_TW.json"
ZH_EXPLICIT = ROOT / "src" / "i18n" / "data" / "zh_explicit.json"


def _row_for_value_id(value_id: str) -> str:
    html = INDEX.read_text(encoding="utf-8")
    pat = re.compile(
        r'<div\s+class="story-stat"[^>]*>.*?id="' + re.escape(value_id) + r'"[^>]*>',
        flags=re.DOTALL,
    )
    m = pat.search(html)
    assert m, f"story-stat row containing id={value_id!r} not found"
    return m.group(0)


def test_d_unknown_row_has_tooltip():
    row = _row_for_value_id("d-unknown")
    assert 'data-i18n-title="gui_card_unknown_types_tooltip"' in row, (
        f"d-unknown row missing tooltip i18n binding: {row!r}"
    )
    assert ' title="' in row, "d-unknown row missing static title fallback"


def test_d_suppressed_row_has_tooltip():
    row = _row_for_value_id("d-suppressed")
    assert 'data-i18n-title="gui_card_suppressed_tooltip"' in row, (
        f"d-suppressed row missing tooltip i18n binding: {row!r}"
    )
    assert ' title="' in row, "d-suppressed row missing static title fallback"


def test_tooltip_keys_in_all_locales():
    en = json.loads(EN.read_text(encoding="utf-8"))
    zh = json.loads(ZH.read_text(encoding="utf-8"))
    expl = json.loads(ZH_EXPLICIT.read_text(encoding="utf-8"))
    for key in ("gui_card_unknown_types_tooltip", "gui_card_suppressed_tooltip"):
        assert key in en and en[key], f"{key} missing/empty in en"
        assert key in zh and zh[key], f"{key} missing/empty in zh_TW"
        assert key in expl and expl[key], f"{key} missing in zh_explicit"
        # zh values should be predominantly CJK
        han_chars = sum(1 for ch in zh[key] if "一" <= ch <= "鿿")
        assert han_chars >= 20, f"{key} zh value not substantive enough: {zh[key]!r}"


def test_css_cursor_help_on_titled_story_stat():
    css = (ROOT / "src" / "static" / "css" / "app.css").read_text(encoding="utf-8")
    assert ".story-stat[title]" in css, (
        ".story-stat[title] CSS rule missing — users won't get cursor:help affordance"
    )
