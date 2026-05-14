"""TLS days-remaining should render with humanized parens."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
JS = ROOT / "src" / "static" / "js" / "settings.js"
EN = ROOT / "src" / "i18n_en.json"
ZH = ROOT / "src" / "i18n_zh_TW.json"
ZH_EXPLICIT = ROOT / "src" / "i18n" / "data" / "zh_explicit.json"


def test_settings_has_humanize_days_helper():
    js = JS.read_text(encoding="utf-8")
    assert "humanizeDays" in js, "Expected humanizeDays() helper in settings.js"


def test_humanize_days_keys_present_en():
    en = json.loads(EN.read_text(encoding="utf-8"))
    assert en.get("gui_tls_days_humanized") == "{n} days (about {label})"
    assert en.get("gui_tls_days_label_years") == "{y}y {m}m"
    assert en.get("gui_tls_days_label_months") == "{m} months"


def test_humanize_days_keys_present_zh():
    zh = json.loads(ZH.read_text(encoding="utf-8"))
    assert zh.get("gui_tls_days_humanized") == "{n} 天（約 {label}）"
    assert zh.get("gui_tls_days_label_years") == "{y} 年 {m} 個月"
    assert zh.get("gui_tls_days_label_months") == "{m} 個月"


def test_zh_explicit_sync_tls_keys():
    explicit = json.loads(ZH_EXPLICIT.read_text(encoding="utf-8"))
    assert explicit.get("gui_tls_days_humanized") == "{n} 天（約 {label}）"
    assert explicit.get("gui_tls_days_label_years") == "{y} 年 {m} 個月"
    assert explicit.get("gui_tls_days_label_months") == "{m} 個月"


def test_humanize_days_used_in_render():
    """humanizeDays must be called when rendering days_remaining."""
    js = JS.read_text(encoding="utf-8")
    # The render block at line ~414 used `${days}`; should now use `${humanizeDays(days)}`.
    assert "humanizeDays(days)" in js, (
        "Expected humanizeDays(days) call in the TLS render block"
    )
