"""Self-heal: ConfigManager.load() rewrites [MISSING:key] in rules[].desc/rec.

Reproduces the user-visible regression where alerts displayed
"[MISSING:rule_policy_provision_desc]" because the rule was persisted into
config.json before the i18n key was added (commit e0ac1fb, 2026-05-03).
"""
from __future__ import annotations

import json

from src.config import ConfigManager


def _write_min_cfg(cfg_dir, rules, language="zh_TW"):
    cfg_dir.mkdir(exist_ok=True)
    cfg_file = cfg_dir / "config.json"
    alerts_file = cfg_dir / "alerts.json"
    cfg = {
        "settings": {"language": language},
        "api": {"url": "https://test.local", "key": "k", "secret": "s", "org_id": "1"},
    }
    cfg_file.write_text(json.dumps(cfg), encoding="utf-8")
    alerts_file.write_text(json.dumps({"rules": rules}), encoding="utf-8")
    return str(cfg_file)


def test_heal_stale_missing_marker_in_rule_desc(tmp_path):
    """Stale `[MISSING:rule_policy_provision_desc]` is re-resolved on load."""
    rules = [{
        "id": 1, "type": "event", "name": "Policy Provision",
        "filter_key": "event_type", "filter_value": "sec_policy.create",
        "filter_status": "all", "filter_severity": "all",
        "match_fields": {}, "throttle": "",
        "desc": "[MISSING:rule_policy_provision_desc]",
        "rec": "[MISSING:rule_policy_provision_rec]",
        "threshold_type": "immediate", "threshold_count": 1,
        "threshold_window": 10, "cooldown_minutes": 60,
    }]
    cfg_path = _write_min_cfg(tmp_path, rules, language="zh_TW")
    cm = ConfigManager(cfg_path)
    healed = cm.config["rules"][0]
    assert not healed["desc"].startswith("[MISSING:"), f"desc still stale: {healed['desc']!r}"
    assert not healed["rec"].startswith("[MISSING:"), f"rec still stale: {healed['rec']!r}"
    # zh translation contains some Chinese — confirm we hit the dict, not just removed the marker
    assert any("一" <= ch <= "鿿" for ch in healed["desc"]), healed["desc"]


def test_heal_idempotent_when_no_stale_markers(tmp_path):
    """Rules without `[MISSING:...]` markers pass through untouched."""
    rules = [{
        "id": 1, "type": "event", "name": "Custom rule",
        "filter_key": "event_type", "filter_value": "x.y",
        "filter_status": "all", "filter_severity": "all",
        "match_fields": {}, "throttle": "",
        "desc": "Custom description",
        "rec": "Custom recommendation",
        "threshold_type": "immediate", "threshold_count": 1,
        "threshold_window": 10, "cooldown_minutes": 60,
    }]
    cfg_path = _write_min_cfg(tmp_path, rules)
    cm = ConfigManager(cfg_path)
    healed = cm.config["rules"][0]
    assert healed["desc"] == "Custom description"
    assert healed["rec"] == "Custom recommendation"


def test_heal_leaves_unknown_marker_alone(tmp_path):
    """`[MISSING:nonexistent_key]` (no current i18n entry) stays as-is.

    Avoids replacing one bad marker with an empty string when t() also returns
    no value for the key. The rule is still broken but at least the marker
    keeps the diagnostic visible to the operator.
    """
    rules = [{
        "id": 1, "type": "event", "name": "Mystery",
        "filter_key": "event_type", "filter_value": "x.y",
        "filter_status": "all", "filter_severity": "all",
        "match_fields": {}, "throttle": "",
        "desc": "[MISSING:nonexistent_made_up_key_xyz]",
        "rec": "Custom rec",
        "threshold_type": "immediate", "threshold_count": 1,
        "threshold_window": 10, "cooldown_minutes": 60,
    }]
    cfg_path = _write_min_cfg(tmp_path, rules)
    cm = ConfigManager(cfg_path)
    healed = cm.config["rules"][0]
    assert healed["desc"] == "[MISSING:nonexistent_made_up_key_xyz]"
