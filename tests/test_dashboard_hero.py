"""Tests for the dashboard story-mode hero block (Phase 3.1, Task 1)."""
import json
import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "src" / "templates" / "index.html"
DASHBOARD_JS = ROOT / "src" / "static" / "js" / "dashboard.js"
I18N_EN = ROOT / "src" / "i18n_en.json"
I18N_ZH = ROOT / "src" / "i18n_zh_TW.json"


def test_build_hero_with_snapshot():
    from src.dashboard_hero import build_hero
    snapshot = {
        "kpis": [
            {"label": "Maturity Score", "value": "78/100 (B)"},
        ],
        "key_findings": [
            {"severity": "HIGH"},
            {"severity": "CRITICAL"},
            {"severity": "MEDIUM"},
        ],
    }
    hero = build_hero(snapshot, status={})
    assert hero["sentence_key"] == "gui_hero_sentence"
    assert hero["score"] == 78.0
    assert hero["score_grade"] == "B"
    assert hero["high_risk_count"] == 2


def test_build_hero_empty_snapshot():
    from src.dashboard_hero import build_hero
    hero = build_hero({}, status={})
    assert hero["sentence_key"] == "gui_hero_no_data"
    assert hero["high_risk_count"] == 0


def test_index_html_has_hero_block_before_cards():
    html = INDEX_HTML.read_text(encoding="utf-8")
    # hero must exist
    assert 'id="d-hero"' in html
    # hero must be after p-dashboard but before first .cards block following it
    p_idx = html.find('id="p-dashboard"')
    hero_idx = html.find('id="d-hero"', p_idx)
    cards_idx = html.find('class="cards"', p_idx)
    assert p_idx >= 0 and hero_idx > p_idx
    assert cards_idx > hero_idx


def test_dashboard_js_has_renderHero():
    js = DASHBOARD_JS.read_text(encoding="utf-8")
    assert "function renderHero" in js
    assert "renderHero(" in js


def test_i18n_has_hero_keys():
    en = json.loads(I18N_EN.read_text(encoding="utf-8"))
    zh = json.loads(I18N_ZH.read_text(encoding="utf-8"))
    for key in ("gui_hero_sentence", "gui_hero_view_high_risk", "gui_hero_no_data"):
        assert key in en, f"missing key {key} in EN i18n"
        assert key in zh, f"missing key {key} in ZH_TW i18n"
    assert "{score}" in en["gui_hero_sentence"]
    assert "{high_risk}" in en["gui_hero_sentence"]
