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
