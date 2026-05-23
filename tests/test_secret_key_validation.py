import json
import secrets
import pytest


@pytest.fixture
def short_key_config(tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({
        "web_gui": {
            "secret_key": "tooshort",  # 8 chars — below threshold
            "username": "illumio",
            "password": "$argon2id$dummy"  # dummy hash
        }
    }))
    return cfg_file


@pytest.fixture
def good_key_config(tmp_path):
    cfg_file = tmp_path / "config.json"
    good = secrets.token_hex(32)  # 64 chars
    cfg_file.write_text(json.dumps({
        "web_gui": {
            "secret_key": good,
            "username": "illumio",
            "password": "$argon2id$dummy"
        }
    }))
    return cfg_file, good


def test_short_secret_key_gets_regenerated(short_key_config):
    """secret_key 短於 64 chars 應被自動 regenerate."""
    from src.config import ConfigManager
    cm = ConfigManager(config_file=str(short_key_config))
    cm.load()
    sk = cm.config["web_gui"]["secret_key"]
    assert len(sk) >= 64, f"secret_key should be regenerated to ≥64 chars, got len={len(sk)}"
    # And the new key should be different from the original short value
    assert sk != "tooshort"


def test_short_secret_key_persists_to_disk(short_key_config):
    """Regenerated secret_key 應被寫回 config.json (不只記憶體更新)."""
    from src.config import ConfigManager
    cm = ConfigManager(config_file=str(short_key_config))
    cm.load()
    in_memory = cm.config["web_gui"]["secret_key"]
    # Read disk directly
    disk = json.loads(short_key_config.read_text())
    assert disk["web_gui"]["secret_key"] == in_memory, "regenerated key not saved to disk"
    assert len(disk["web_gui"]["secret_key"]) >= 64


def test_long_secret_key_preserved(good_key_config):
    """正常長度 secret_key 不應被改動."""
    cfg_file, good = good_key_config
    from src.config import ConfigManager
    cm = ConfigManager(config_file=str(cfg_file))
    cm.load()
    assert cm.config["web_gui"]["secret_key"] == good, "valid secret_key was unnecessarily regenerated"


def test_missing_secret_key_gets_generated(tmp_path):
    """完全缺失 secret_key 應被產生."""
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({
        "web_gui": {"username": "illumio", "password": "$argon2id$dummy"}
    }))
    from src.config import ConfigManager
    cm = ConfigManager(config_file=str(cfg_file))
    cm.load()
    assert len(cm.config["web_gui"].get("secret_key", "")) >= 64


def test_null_secret_key_treated_as_missing(tmp_path):
    """JSON null secret_key should not crash; should be regenerated like missing key."""
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({
        "web_gui": {
            "secret_key": None,  # JSON null
            "username": "illumio",
            "password": "$argon2id$dummy"
        }
    }))
    from src.config import ConfigManager
    cm = ConfigManager(config_file=str(cfg_file))
    cm.load()  # must not raise TypeError
    assert len(cm.config["web_gui"].get("secret_key", "")) >= 64
