"""Menu strings must not mix English verbs with Chinese nouns."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
ZH = ROOT / "src" / "i18n_zh_TW.json"
ZH_EXPLICIT = ROOT / "src" / "i18n" / "data" / "zh_explicit.json"


def test_main_menu_pce_cache_uses_chinese_verb():
    zh = json.loads(ZH.read_text(encoding="utf-8"))
    val = zh["main_menu_root_7"]
    assert "Manage" not in val, f"Mixed English in main_menu_root_7: {val!r}"
    assert "管理" in val, f"Missing 管理 verb in main_menu_root_7: {val!r}"


def test_main_menu_siem_uses_chinese_verb():
    zh = json.loads(ZH.read_text(encoding="utf-8"))
    val = zh["main_menu_root_8"]
    assert "Manage" not in val, f"Mixed English in main_menu_root_8: {val!r}"
    assert "管理" in val, f"Missing 管理 verb in main_menu_root_8: {val!r}"


def test_zh_explicit_sync_menu_strings():
    """zh_explicit.json must match zh_TW; otherwise precompute will revert."""
    explicit = json.loads(ZH_EXPLICIT.read_text(encoding="utf-8"))
    if "main_menu_root_7" in explicit:
        assert "Manage" not in explicit["main_menu_root_7"]
        assert "管理" in explicit["main_menu_root_7"]
    if "main_menu_root_8" in explicit:
        assert "Manage" not in explicit["main_menu_root_8"]
        assert "管理" in explicit["main_menu_root_8"]
