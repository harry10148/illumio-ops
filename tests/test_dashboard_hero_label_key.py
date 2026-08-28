"""Task 6: hero KPI matching must use label_key, not the localised label text.

Regression coverage for the bug where dashboard_hero.build_hero() matched the
already-localised KPI label against the English substring "maturity". On a
zh-TW appliance the label is retranslated to "微分段成熟度" by
_retranslate_kpi_labels (src/gui/routes/dashboard.py), so the substring check
never matched and the hero silently fell back to score=0.0/grade="?".
"""
from src.dashboard_hero import build_hero


def _snapshot(kpi):
    return {
        "kpis": [kpi],
        "key_findings": [],
    }


def test_zh_label_with_label_key_yields_real_score():
    """Chinese label + label_key must still resolve the real score/grade."""
    snapshot = _snapshot({
        "label_key": "mod12_kpi_maturity_score",
        "label": "微分段成熟度",
        "value": "72.5/100 (B)",
    })
    hero = build_hero(snapshot)
    assert hero["score"] == 72.5
    assert hero["score_grade"] == "B"


def test_en_label_with_label_key_yields_real_score():
    """English label + label_key: primary label_key path still works."""
    snapshot = _snapshot({
        "label_key": "mod12_kpi_maturity_score",
        "label": "Maturity Score",
        "value": "72.5/100 (B)",
    })
    hero = build_hero(snapshot)
    assert hero["score"] == 72.5
    assert hero["score_grade"] == "B"


def test_legacy_snapshot_without_label_key_falls_back_to_substring():
    """No label_key at all (legacy snapshot) must still work via the
    substring fallback that _retranslate_kpi_labels explicitly tolerates."""
    snapshot = _snapshot({
        "label": "Maturity Score",
        "value": "72.5/100 (B)",
    })
    hero = build_hero(snapshot)
    assert hero["score"] == 72.5
    assert hero["score_grade"] == "B"
