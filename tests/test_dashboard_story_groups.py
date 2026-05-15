"""Phase 3.1 Task 2 — story-card grouping for Dashboard top stats."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "src" / "templates" / "index.html"
DASHBOARD_JS = ROOT / "src" / "static" / "js" / "dashboard.js"
I18N_EN = ROOT / "src" / "i18n_en.json"
I18N_ZH = ROOT / "src" / "i18n_zh_TW.json"


def test_index_html_has_three_story_card_classes():
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert "story-card--health" in html
    assert "story-card--traffic" in html
    assert "story-card--risk" in html


def test_legacy_card_ids_preserved():
    html = INDEX_HTML.read_text(encoding="utf-8")
    for lid in ("d-rules", "d-health", "d-event-poll", "d-dispatch", "d-unknown", "d-suppressed", "d-ransom"):
        assert f'id="{lid}"' in html, f"missing legacy id {lid}"


def test_i18n_has_group_keys():
    en = json.loads(I18N_EN.read_text(encoding="utf-8"))
    zh = json.loads(I18N_ZH.read_text(encoding="utf-8"))
    for k in ("gui_story_group_health", "gui_story_group_traffic", "gui_story_group_risk", "gui_hi_risk_findings"):
        assert k in en, f"missing EN {k}"
        assert k in zh, f"missing ZH {k}"


def test_dashboard_js_has_renderStoryGroups():
    js = DASHBOARD_JS.read_text(encoding="utf-8")
    assert "renderStoryGroups" in js
