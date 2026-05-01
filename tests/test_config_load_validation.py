"""ConfigManager.load() validates via pydantic and surfaces errors clearly."""
from __future__ import annotations

import json
import logging

import pytest


def _write(tmp_path, body: dict):
    p = tmp_path / "config.json"
    p.write_text(json.dumps(body), encoding="utf-8")
    return str(p)


def test_load_accepts_minimal_valid_config(tmp_path):
    from src.config import ConfigManager
    cfg_file = _write(tmp_path, {
        "api": {"url": "https://pce.test", "org_id": "1", "key": "k", "secret": "s"},
    })
    cm = ConfigManager(cfg_file)
    assert cm.config["api"]["url"].startswith("https://pce.test")
    # Defaults filled in
    assert cm.config["settings"]["language"] == "en"


def test_load_rejects_http_port_out_of_range(tmp_path, caplog):
    from src.config import ConfigManager
    cfg_file = _write(tmp_path, {
        "api": {"url": "https://pce.test", "org_id": "1", "key": "k", "secret": "s"},
        "smtp": {"host": "x", "port": 99999},
    })
    caplog.set_level(logging.ERROR)
    # Loading should log the error; config falls back to defaults
    cm = ConfigManager(cfg_file)
    # Error message mentions smtp.port
    errs = [r for r in caplog.records if "smtp" in r.message.lower() or "port" in r.message.lower()]
    assert errs, f"Expected SMTP port validation error; got {[r.message for r in caplog.records]}"


def test_load_rejects_non_http_url(tmp_path, caplog):
    from src.config import ConfigManager
    cfg_file = _write(tmp_path, {
        "api": {"url": "ftp://wrong", "org_id": "1", "key": "k", "secret": "s"},
    })
    caplog.set_level(logging.ERROR)
    ConfigManager(cfg_file)
    # Must surface url error
    msgs = " ".join(r.message for r in caplog.records).lower()
    assert "url" in msgs or "http" in msgs


def test_load_surfaces_typo_in_top_level_key(tmp_path, caplog):
    """'web_guy' typo instead of 'web_gui' should be rejected."""
    from src.config import ConfigManager
    cfg_file = _write(tmp_path, {
        "api": {"url": "https://pce.test", "org_id": "1", "key": "k", "secret": "s"},
        "web_guy": {"username": "x"},    # typo
    })
    caplog.set_level(logging.ERROR)
    ConfigManager(cfg_file)
    msgs = " ".join(r.message for r in caplog.records).lower()
    assert "web_guy" in msgs or "extra" in msgs or "forbidden" in msgs


def test_models_attribute_exposes_typed_schema(tmp_path):
    """New: cm.models gives typed access for new code that wants strong types."""
    from src.config import ConfigManager
    cfg_file = _write(tmp_path, {
        "api": {"url": "https://pce.test", "org_id": "1", "key": "k", "secret": "s"},
    })
    cm = ConfigManager(cfg_file)
    assert hasattr(cm, "models"), "cm.models must exist for typed access"
    assert cm.models.api.org_id == "1"
    assert cm.models.settings.language == "en"


def test_config_with_rule_backups_reloads_cleanly(tmp_path):
    """Regression: apply_best_practices writes rule_backups, which used to break pydantic validation."""
    from src.config import ConfigManager
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "api": {"url": "https://p.test", "org_id": "1", "key": "k", "secret": "s"},
        "rule_backups": [{"timestamp": "2026-01-01", "rules": [{"id": 1}]}],
    }), encoding="utf-8")
    cm = ConfigManager(str(cfg))
    # rule_backups must survive the round-trip
    assert cm.config["rule_backups"] == [{"timestamp": "2026-01-01", "rules": [{"id": 1}]}]
    # Reload should not emit validation errors
    cm2 = ConfigManager(str(cfg))
    assert cm2.config["rule_backups"] == cm.config["rule_backups"]


def test_load_redacts_secret_input_in_logs(tmp_path, caplog):
    """ValidationError logs must NEVER include raw secret values."""
    from src.config import ConfigManager
    cfg = tmp_path / "config.json"
    # Inject a secret with an invalid type that trips validation
    cfg.write_text(json.dumps({
        "api": {"url": "https://p.test", "org_id": "1",
                "key": "valid_key", "secret": 99999}  # int instead of str
    }), encoding="utf-8")
    caplog.set_level(logging.ERROR)
    ConfigManager(str(cfg))
    combined = " ".join(r.message for r in caplog.records)
    assert "99999" not in combined, "secret value leaked to logs"
    assert "[REDACTED]" in combined or "secret" in combined.lower()


# ─── Alerts split-file tests ────────────────────────────────────────────────

def test_alerts_round_trip_uses_separate_file(tmp_path):
    """alerts persists to alerts.json, not config.json."""
    from src.config import ConfigManager
    cfg = tmp_path / "config.json"
    alerts = tmp_path / "alerts.json"
    cfg.write_text(json.dumps({
        "api": {"url": "https://p.test", "org_id": "1", "key": "k", "secret": "s"},
    }), encoding="utf-8")

    cm = ConfigManager(str(cfg), alerts_file=str(alerts))
    cm.config["alerts"]["webhook_url"] = "https://hooks.example/abc"
    cm.config["alerts"]["line_channel_access_token"] = "secret-line-token"
    cm.save()

    # alerts.json now exists with the alert values
    assert alerts.exists()
    saved_alerts = json.loads(alerts.read_text(encoding="utf-8"))
    assert saved_alerts["webhook_url"] == "https://hooks.example/abc"
    assert saved_alerts["line_channel_access_token"] == "secret-line-token"

    # config.json must NOT contain alerts
    saved_config = json.loads(cfg.read_text(encoding="utf-8"))
    assert "alerts" not in saved_config, "alerts must not be persisted in config.json"

    # Reload through a fresh ConfigManager — alerts come back from alerts.json
    cm2 = ConfigManager(str(cfg), alerts_file=str(alerts))
    assert cm2.config["alerts"]["webhook_url"] == "https://hooks.example/abc"
    assert cm2.config["alerts"]["line_channel_access_token"] == "secret-line-token"


def test_alerts_migration_from_legacy_single_file(tmp_path):
    """Pre-split installs have alerts inside config.json; first save() splits them out."""
    from src.config import ConfigManager
    cfg = tmp_path / "config.json"
    alerts = tmp_path / "alerts.json"
    cfg.write_text(json.dumps({
        "api": {"url": "https://p.test", "org_id": "1", "key": "k", "secret": "s"},
        "alerts": {
            "active": ["mail", "webhook"],
            "webhook_url": "https://legacy.example/hook",
            "line_channel_access_token": "legacy-token",
            "line_target_id": "C123",
        },
    }), encoding="utf-8")
    assert not alerts.exists()

    cm = ConfigManager(str(cfg), alerts_file=str(alerts))
    # In-memory alerts inherited from config.json
    assert cm.config["alerts"]["webhook_url"] == "https://legacy.example/hook"
    assert cm.config["alerts"]["line_channel_access_token"] == "legacy-token"

    cm.save()

    # alerts.json now exists with the migrated values
    assert alerts.exists()
    migrated = json.loads(alerts.read_text(encoding="utf-8"))
    assert migrated["webhook_url"] == "https://legacy.example/hook"
    assert migrated["line_channel_access_token"] == "legacy-token"
    assert migrated["active"] == ["mail", "webhook"]

    # config.json no longer carries alerts
    cleaned = json.loads(cfg.read_text(encoding="utf-8"))
    assert "alerts" not in cleaned


def test_alerts_file_missing_falls_back_to_defaults(tmp_path):
    """If both config.json and alerts.json lack alerts, defaults are used."""
    from src.config import ConfigManager
    cfg = tmp_path / "config.json"
    alerts = tmp_path / "alerts.json"
    cfg.write_text(json.dumps({
        "api": {"url": "https://p.test", "org_id": "1", "key": "k", "secret": "s"},
    }), encoding="utf-8")

    cm = ConfigManager(str(cfg), alerts_file=str(alerts))
    # Defaults from _DEFAULT_CONFIG
    assert cm.config["alerts"]["active"] == ["mail"]
    assert cm.config["alerts"]["webhook_url"] == ""


def test_alerts_corrupt_file_keeps_app_running(tmp_path, caplog):
    """A corrupt alerts.json must not crash startup — it's logged and treated as empty."""
    import logging
    from src.config import ConfigManager
    cfg = tmp_path / "config.json"
    alerts = tmp_path / "alerts.json"
    cfg.write_text(json.dumps({
        "api": {"url": "https://p.test", "org_id": "1", "key": "k", "secret": "s"},
    }), encoding="utf-8")
    alerts.write_text("{ this is not valid json", encoding="utf-8")

    caplog.set_level(logging.ERROR)
    cm = ConfigManager(str(cfg), alerts_file=str(alerts))
    # alerts dict still exists (empty/defaults), no exception
    assert isinstance(cm.config["alerts"], dict)
    combined = " ".join(r.message for r in caplog.records)
    assert "alerts" in combined.lower() or "Error reading alerts" in combined
