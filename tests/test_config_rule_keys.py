"""Phase 4: rules persist desc_key/rec_key, render via t() at read time."""
from __future__ import annotations

import json
from pathlib import Path

from src.config import ConfigManager


def test_rule_with_desc_key_renders_translated(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({
        "rules": [
            {
                "id": "test_001",
                "type": "policy_provision",
                "desc_key": "rule_policy_provision_desc",
                "rec_key": "alert_rec_policy_provision",
            }
        ],
        "settings": {"language": "zh_TW"},
    }), encoding="utf-8")

    cm = ConfigManager(config_file=str(cfg_file))
    cm.load()
    rules = cm.config.get("rules", [])
    assert rules, "rules list should be populated"
    rule = rules[0]
    assert rule.get("desc"), "loader must populate desc from desc_key at read time"
    assert "[MISSING:" not in rule["desc"], "desc must resolve, not return MISSING"


def test_rule_legacy_format_still_works(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({
        "rules": [
            {"id": "old_001", "type": "custom", "desc": "Legacy description", "rec": "Legacy rec"}
        ],
        "settings": {"language": "en"},
    }), encoding="utf-8")

    cm = ConfigManager(config_file=str(cfg_file))
    cm.load()
    rules = cm.config.get("rules", [])
    assert rules, "rules list should be populated"
    assert rules[0]["desc"] == "Legacy description"
    assert rules[0]["rec"] == "Legacy rec"


def test_rule_desc_key_overrides_stale_desc(tmp_path: Path) -> None:
    """If both desc_key and stale desc text exist, key resolution wins."""
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({
        "rules": [
            {
                "id": "stale_001",
                "type": "policy_provision",
                "desc_key": "rule_policy_provision_desc",
                "desc": "[MISSING:rule_policy_provision_desc]",
            }
        ],
        "settings": {"language": "en"},
    }), encoding="utf-8")

    cm = ConfigManager(config_file=str(cfg_file))
    cm.load()
    rules = cm.config.get("rules", [])
    assert rules, "rules list should be populated"
    assert "[MISSING:" not in rules[0]["desc"]


def test_rule_save_strips_rendered_text_when_key_present(tmp_path: Path) -> None:
    """save() must persist desc_key/rec_key without redundant rendered text."""
    cfg_file = tmp_path / "config.json"
    alerts_file = tmp_path / "alerts.json"
    cfg_file.write_text(json.dumps({
        "rules": [{
            "id": "001",
            "event_type": "sec_policy.create",
            "desc_key": "rule_sec_policy.create_desc",
            "rec_key": "alert_rec_sec_policy_create",
        }],
        "settings": {"language": "en"},
    }), encoding="utf-8")

    cm = ConfigManager(config_file=str(cfg_file), alerts_file=str(alerts_file))
    cm.load()
    cm.save()

    saved = json.loads(alerts_file.read_text(encoding="utf-8"))
    rule = saved["rules"][0]
    # Keys remain (canonical)
    assert rule["desc_key"] == "rule_sec_policy.create_desc"
    assert rule["rec_key"] == "alert_rec_sec_policy_create"
    # Rendered text removed (was populated by load)
    assert "desc" not in rule, f"desc should be stripped: {rule}"
    assert "rec" not in rule, f"rec should be stripped: {rule}"


def test_rule_save_keeps_legacy_text_without_keys(tmp_path: Path) -> None:
    """Legacy rules without desc_key/rec_key must retain their text on save."""
    cfg_file = tmp_path / "config.json"
    alerts_file = tmp_path / "alerts.json"
    cfg_file.write_text(json.dumps({
        "rules": [
            {"id": "old_001", "desc": "Legacy desc", "rec": "Legacy rec"}
        ],
        "settings": {"language": "en"},
    }), encoding="utf-8")

    cm = ConfigManager(config_file=str(cfg_file), alerts_file=str(alerts_file))
    cm.load()
    cm.save()

    saved = json.loads(alerts_file.read_text(encoding="utf-8"))
    rule = saved["rules"][0]
    assert rule.get("desc") == "Legacy desc"
    assert rule.get("rec") == "Legacy rec"
