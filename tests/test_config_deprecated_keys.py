"""A config.json carrying a removed key (report.attack_surface) must still load.

The schema uses extra="forbid", so older deployed configs that still contain
keys removed in newer versions would otherwise fail validation. ConfigManager
strips known-deprecated keys before validation.
"""
from __future__ import annotations

import json

from src.config import _strip_deprecated_keys
from src.config_models import ConfigSchema


def test_strip_removes_attack_surface_in_place():
    merged = {"report": {"schedule": "daily",
                         "attack_surface": {"enabled": False, "max_workloads": 500}}}
    dropped = _strip_deprecated_keys(merged)
    assert dropped == ["report.attack_surface"]
    assert "attack_surface" not in merged["report"]
    assert merged["report"]["schedule"] == "daily"  # sibling keys preserved


def test_strip_noop_when_absent():
    merged = {"report": {"schedule": "weekly"}}
    assert _strip_deprecated_keys(merged) == []
    assert merged == {"report": {"schedule": "weekly"}}


def test_config_manager_loads_legacy_attack_surface(tmp_path):
    from src.config import ConfigManager

    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "report": {"schedule": "daily",
                   "attack_surface": {"enabled": False, "max_workloads": 500,
                                      "cache_ttl_hours": 24}},
    }), encoding="utf-8")

    cm = ConfigManager(config_file=str(cfg))

    # Validation succeeded (not the fallback-to-defaults path): the typed model
    # reflects the file value, which differs from the schema default ("weekly").
    assert cm.models.report.schedule == "daily"
    # The deprecated key was dropped from the loaded config.
    assert "attack_surface" not in cm.config.get("report", {})


def test_strip_removes_pce_profile_keys_in_place():
    """設備曾支援多組 PCE profile；欄位已移除，舊 config.json 仍須能載入。"""
    merged = {
        "api": {"url": "https://pce.example.com:8443"},
        "pce_profiles": [{"id": 1, "name": "lab", "url": "https://a:8443"}],
        "active_pce_id": 1,
    }
    dropped = _strip_deprecated_keys(merged)
    assert sorted(dropped) == ["active_pce_id", "pce_profiles"]
    assert "pce_profiles" not in merged
    assert "active_pce_id" not in merged
    assert merged["api"]["url"] == "https://pce.example.com:8443"


def test_strip_removes_archive_review_max_days_in_place():
    """封存查閱改成直接串流封存日檔（Task 1-6），不再匯入 review DB，
    這個上限鍵也隨之移除；舊 config.json 仍須能載入。"""
    merged = {
        "pce_cache": {"enabled": True, "archive_review_max_days": 31},
    }
    dropped = _strip_deprecated_keys(merged)
    assert dropped == ["pce_cache.archive_review_max_days"]
    assert "archive_review_max_days" not in merged["pce_cache"]
    assert merged["pce_cache"]["enabled"] is True


def test_config_manager_loads_legacy_archive_review_max_days(tmp_path):
    from src.config import ConfigManager

    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "pce_cache": {"enabled": True, "archive_review_max_days": 31},
    }), encoding="utf-8")

    cm = ConfigManager(config_file=str(cfg))

    assert cm.models.pce_cache.enabled is True
    assert "archive_review_max_days" not in cm.config.get("pce_cache", {})


def test_archive_review_max_days_only_referenced_by_the_retirement_path():
    """`archive_review_max_days` 已從 schema 移除（見 test_config_models.py
    對 PceCacheSettings.model_fields 的欄位集合斷言），此處只確認字串本身
    在整個 repo 只剩兩處合法引用：讓舊 config.json 還能載入的
    `_DEPRECATED_KEY_PATHS`（src/config.py），與斷言它被丟棄的這個檔。
    集合相等（而非「非空即失敗」）——多一處遺漏或少一處都要現形。"""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    hits = set()
    for sub in ("src", "tests"):
        for p in (root / sub).rglob("*.py"):
            if "archive_review_max_days" in p.read_text(encoding="utf-8", errors="ignore"):
                hits.add(str(p.relative_to(root)))
    expected = {"src/config.py", "tests/test_config_deprecated_keys.py"}
    assert hits == expected, hits
