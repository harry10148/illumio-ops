"""Lock down approved zh_TW translations for dashboard mini-KPI keys.

These translations were re-reviewed against Illumio's official terminology
(Anomaly / Visibility / Enforcement / Boundary / Blast Radius / Blind Spots)
on 2026-05-15 — see docs/ux-review-2026-05-14/dashboard_i18n_flagged.md."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ZH = ROOT / "src" / "i18n_zh_TW.json"
EN = ROOT / "src" / "i18n_en.json"

APPROVED_ZH = {
    "gui_dashboard_rules":     "規則數",
    "gui_card_health_rule":    "健康檢查規則",
    "gui_card_event_poll":     "事件輪詢",
    "gui_card_last_dispatch":  "最後派送",
    "gui_card_unknown_types":  "未知事件類型",
    "gui_card_suppressed":     "已抑制",
    "gui_card_ransomware_exp": "Ransomware 暴露面",
    "gui_cooldown_title":      "冷卻中規則",
}


def test_approved_zh_translations_present() -> None:
    zh = json.loads(ZH.read_text(encoding="utf-8"))
    diffs: list[str] = []
    for key, want in APPROVED_ZH.items():
        got = zh.get(key)
        if got != want:
            diffs.append(f"  {key}: want={want!r} got={got!r}")
    assert not diffs, "Approved zh_TW translations drifted:\n" + "\n".join(diffs)


def test_approved_keys_present_in_english_too() -> None:
    en = json.loads(EN.read_text(encoding="utf-8"))
    missing = [k for k in APPROVED_ZH if k not in en]
    assert not missing, f"Approved keys missing from EN: {missing}"
