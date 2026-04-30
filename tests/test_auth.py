"""Tests for Phase 1 security hardening: argon2id password hashing."""
import os
import json
import stat
import tempfile
import pytest

from src.config import hash_password, verify_password, ConfigManager


def test_hash_and_verify_roundtrip():
    h = hash_password("secret")
    assert h.startswith("$argon2")
    assert verify_password("secret", h) is True
    assert verify_password("wrong", h) is False


def test_verify_empty_stored_returns_false():
    assert verify_password("x", "") is False


def test_default_config_no_default_password(tmp_path):
    config_file = str(tmp_path / "config.json")
    # Write minimal config with no web_gui password
    with open(config_file, "w") as f:
        json.dump({
            "api": {"url": "https://test.example.com", "key": "k", "secret": "s", "org_id": "1"},
            "rules": [],
        }, f)
    cm = ConfigManager(config_file=config_file)
    gui = cm.config.get("web_gui", {})
    assert gui["password"].startswith("$argon2"), "Password must be an argon2 hash"
    assert gui.get("must_change_password") is True, "must_change_password must be set on first boot"


def test_legacy_plaintext_migration(tmp_path):
    config_file = str(tmp_path / "config.json")
    # Write config with plaintext legacy password
    with open(config_file, "w") as f:
        json.dump({
            "api": {"url": "https://test.example.com", "key": "k", "secret": "s", "org_id": "1"},
            "rules": [],
            "web_gui": {
                "username": "admin",
                "password": "oldpassword",
                "secret_key": "test-secret",
                "allowed_ips": [],
            },
        }, f)
    cm = ConfigManager(config_file=config_file)
    gui = cm.config.get("web_gui", {})
    assert gui["password"].startswith("$argon2"), "Legacy plaintext password must be migrated to argon2"
    assert verify_password("oldpassword", gui["password"]) is True


def test_save_sets_file_permissions(tmp_path):
    config_file = str(tmp_path / "config.json")
    with open(config_file, "w") as f:
        json.dump({
            "api": {"url": "https://test.example.com", "key": "k", "secret": "s", "org_id": "1"},
            "rules": [],
        }, f)
    cm = ConfigManager(config_file=config_file)
    cm.save()
    file_stat = os.stat(config_file)
    mode = stat.S_IMODE(file_stat.st_mode)
    assert mode == 0o600, f"Config file must be mode 0o600, got {oct(mode)}"
