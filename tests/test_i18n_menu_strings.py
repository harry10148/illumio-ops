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


def test_glossary_allows_manage_to_chinese_in_menu():
    """Glossary should not forbid 'Manage' → '管理' for top-level menu CTAs.

    Codifies the P0 Task 5 followup decision: the verb 'Manage' (in CTAs
    like 'Manage PCE Cache') naturally renders as 管理 in Traditional
    Chinese menus/buttons. The product nouns 'Managed' / 'Unmanaged'
    (e.g. 'Managed Workload') remain glossary-protected because they are
    Illumio product state labels, but the verb form must not be.
    """
    glossary_path = ROOT / "src" / "i18n" / "data" / "glossary.json"
    g = json.loads(glossary_path.read_text(encoding="utf-8"))
    forbidden = g.get("forbidden_zh_substitutes", {})
    # The verb 'Manage' must NOT have 管理 listed as a forbidden substitute,
    # otherwise menu strings like 'main_menu_root_7' regress against Cat E.
    assert "Manage" not in forbidden or "管理" not in forbidden.get("Manage", []), (
        "Glossary forbids 'Manage' → '管理', but menu CTAs (main_menu_root_7/8) "
        "use 管理 as the natural Chinese verb. Either remove the rule or add a "
        "key-scoped exemption."
    )
    # Sanity: the product-noun forms stay protected.
    assert "管理" not in forbidden.get("Managed", []), (
        "Cross-check: 'Managed' (product noun) is allowed to keep its own "
        "forbidden_zh_substitutes — current entry should remain unchanged."
    )
