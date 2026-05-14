"""Verify Web 安全設定 has confirm-password field & client-side mismatch guard."""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).parent.parent
JS = ROOT / "src" / "static" / "js" / "settings.js"
EN = ROOT / "src" / "i18n_en.json"
ZH = ROOT / "src" / "i18n_zh_TW.json"
ZH_EXPLICIT = ROOT / "src" / "i18n" / "data" / "zh_explicit.json"


def test_settings_has_confirm_password_input():
    js = JS.read_text(encoding="utf-8")
    assert 's-sec-newpass-confirm' in js, (
        "Expected confirm-password input id 's-sec-newpass-confirm' in settings.js"
    )


def test_settings_validates_password_match():
    js = JS.read_text(encoding="utf-8")
    # Helper / inline check that produces a localized error when they differ
    assert 'gui_password_mismatch' in js, (
        "Expected i18n key gui_password_mismatch used for client-side validation"
    )


def test_i18n_password_mismatch_keys_exist_en():
    en = json.loads(EN.read_text(encoding="utf-8"))
    assert en.get("gui_new_password_confirm") == "Confirm New Password"
    assert en.get("gui_password_mismatch") == "New password and confirmation do not match."


def test_i18n_password_mismatch_keys_exist_zh():
    zh = json.loads(ZH.read_text(encoding="utf-8"))
    assert zh.get("gui_new_password_confirm") == "確認新密碼"
    assert zh.get("gui_password_mismatch") == "新密碼與確認欄位不一致。"


def test_zh_explicit_sync_password_keys():
    """zh_explicit.json must also have the new keys; otherwise precompute reverts."""
    explicit = json.loads(ZH_EXPLICIT.read_text(encoding="utf-8"))
    assert explicit.get("gui_new_password_confirm") == "確認新密碼"
    assert explicit.get("gui_password_mismatch") == "新密碼與確認欄位不一致。"
