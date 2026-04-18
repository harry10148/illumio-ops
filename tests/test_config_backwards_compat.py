"""Freeze the cm.config['section']['key'] dict-access patterns used across
the codebase before introducing pydantic validation layer.

Grep confirms these exact patterns appear in 10+ modules:
  cm.config["api"]["url"]
  cm.config.get("settings", {}).get("language", "en")
  cm.config["rules"]
  cm.config["web_gui"]["password_hash"]
  etc.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def fresh_config(tmp_path, monkeypatch):
    """Build a ConfigManager pointed at a temp file with a valid minimal config."""
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({
        "api": {
            "url": "https://pce.example.com:8443",
            "org_id": "1",
            "key": "kk",
            "secret": "ss",
            "verify_ssl": True,
        },
        "settings": {"language": "en", "theme": "dark"},
        "alerts": {"active": ["mail"]},
        "email": {"sender": "a@b.c", "recipients": ["d@e.f"]},
        "smtp": {"host": "localhost", "port": 25, "user": "", "password": ""},
        "rules": [],
        "report": {"enabled": False, "output_dir": "reports/"},
        "report_schedules": [],
        "pce_profiles": [],
        "active_pce_id": None,
        "rule_scheduler": {"enabled": True, "check_interval_seconds": 300},
        "web_gui": {"username": "illumio", "password_hash": "", "password_salt": "", "secret_key": "", "allowed_ips": []},
    }, indent=2), encoding="utf-8")
    from src.config import ConfigManager
    return ConfigManager(str(cfg_file))


def test_api_url_accessible_via_dict(fresh_config):
    assert fresh_config.config["api"]["url"] == "https://pce.example.com:8443"
    assert fresh_config.config["api"]["org_id"] == "1"


def test_settings_dict_get_with_default(fresh_config):
    """Pattern: cm.config.get('settings', {}).get('language', 'en')"""
    lang = fresh_config.config.get("settings", {}).get("language", "en")
    assert lang == "en"


def test_nested_web_gui_tls_defaults_applied(fresh_config):
    """Pattern: cm.config['web_gui']['tls'] may not be in user config — defaults fill."""
    tls = fresh_config.config.get("web_gui", {}).get("tls", {})
    # After validation, tls default must be present
    assert "enabled" in tls


def test_rules_is_a_list(fresh_config):
    assert isinstance(fresh_config.config["rules"], list)


def test_pce_profiles_is_a_list(fresh_config):
    assert isinstance(fresh_config.config["pce_profiles"], list)
