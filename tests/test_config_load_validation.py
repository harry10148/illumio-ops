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
    """api.url is an api-block field, so an invalid scheme now fails hard
    (see test_load_fails_hard_on_invalid_api_block) rather than falling back."""
    from src.config import ConfigManager
    from src.exceptions import ConfigError
    cfg_file = _write(tmp_path, {
        "api": {"url": "ftp://wrong", "org_id": "1", "key": "k", "secret": "s"},
    })
    caplog.set_level(logging.ERROR)
    with pytest.raises(ConfigError):
        ConfigManager(cfg_file)
    # Must surface url error
    msgs = " ".join(r.message for r in caplog.records).lower()
    assert "url" in msgs or "http" in msgs


def test_load_fails_hard_on_invalid_api_block(tmp_path, caplog):
    """api-block validation failures must raise ConfigError, not fall back.

    verify_ssl=False + profile='production' trips ApiSettings' TLS guard.
    Falling back here would keep the unvalidated dict (verify_ssl=False) in
    cm.config while cm.models silently reset to safe defaults — the guard
    would become a no-op. Must refuse to start instead.
    """
    from src.config import ConfigManager
    from src.exceptions import ConfigError
    cfg_file = _write(tmp_path, {
        "api": {"url": "https://pce.test", "org_id": "1", "key": "k", "secret": "s",
                "verify_ssl": False, "profile": "production"},
    })
    caplog.set_level(logging.ERROR)
    with pytest.raises(ConfigError) as exc_info:
        ConfigManager(cfg_file)
    msg = str(exc_info.value)
    # Actionable: names the violating field and how to fix it
    assert "api" in msg
    assert "verify_ssl" in msg
    assert "profile" in msg.lower()


def test_load_other_block_failure_still_falls_back(tmp_path, caplog):
    """Non-api block validation failures keep the existing fallback behavior
    (this task narrows fail-hard to the api block only)."""
    from src.config import ConfigManager
    cfg_file = _write(tmp_path, {
        "api": {"url": "https://pce.test", "org_id": "1", "key": "k", "secret": "s"},
        "smtp": {"host": "x", "port": 99999},
    })
    caplog.set_level(logging.ERROR)
    cm = ConfigManager(cfg_file)  # must NOT raise
    # Fallback semantics unchanged: models reset to defaults, dict keeps merged data
    assert cm.config["smtp"]["port"] == 99999
    assert cm.models.smtp.port == 25


def test_load_empty_config_file_does_not_raise(tmp_path):
    """No config.json on disk at all → pure defaults, no ValidationError path."""
    from src.config import ConfigManager
    cfg_file = str(tmp_path / "config.json")  # does not exist
    cm = ConfigManager(cfg_file)
    assert cm.config["api"]["verify_ssl"] is True
    assert cm.models.api.verify_ssl is True


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
    """ValidationError logs must NEVER include raw secret values.

    api.secret is an api-block field, so this now fails hard (see
    test_load_fails_hard_on_invalid_api_block); the redaction requirement
    applies to both the logs and the raised ConfigError message.
    """
    from src.config import ConfigManager
    from src.exceptions import ConfigError
    cfg = tmp_path / "config.json"
    # Inject a secret with an invalid type that trips validation
    cfg.write_text(json.dumps({
        "api": {"url": "https://p.test", "org_id": "1",
                "key": "valid_key", "secret": 99999}  # int instead of str
    }), encoding="utf-8")
    caplog.set_level(logging.ERROR)
    with pytest.raises(ConfigError) as exc_info:
        ConfigManager(str(cfg))
    combined = " ".join(r.message for r in caplog.records)
    assert "99999" not in combined, "secret value leaked to logs"
    assert "[REDACTED]" in combined or "secret" in combined.lower()
    assert "99999" not in str(exc_info.value), "secret value leaked to raised error"


# ─── Split-file tests ───────────────────────────────────────────────────────
# Layout: config.json holds the ``alerts`` channel block (active list, line
# tokens, webhook URL); alerts.json holds the ``rules`` array as
# ``{"rules": [...]}``.

def test_rules_round_trip_persists_to_alerts_file(tmp_path):
    """rules persist to alerts.json, alerts (channel block) persist to config.json."""
    from src.config import ConfigManager
    cfg = tmp_path / "config.json"
    alerts = tmp_path / "alerts.json"
    cfg.write_text(json.dumps({
        "api": {"url": "https://p.test", "org_id": "1", "key": "k", "secret": "s"},
    }), encoding="utf-8")

    cm = ConfigManager(str(cfg), alerts_file=str(alerts))
    cm.config["rules"] = [
        {"id": 1, "type": "event", "name": "Auth failures",
         "filter_value": "request.authentication_failed"}
    ]
    cm.config["alerts"]["webhook_url"] = "https://hooks.example/abc"
    cm.config["alerts"]["line_channel_access_token"] = "secret-line-token"
    cm.save()

    # alerts.json now holds the rules as {"rules": [...]}
    assert alerts.exists()
    saved_alerts = json.loads(alerts.read_text(encoding="utf-8"))
    assert "rules" in saved_alerts
    assert saved_alerts["rules"][0]["name"] == "Auth failures"
    # Channel credentials must NOT leak into alerts.json
    assert "webhook_url" not in saved_alerts
    assert "line_channel_access_token" not in saved_alerts

    # config.json holds the alerts channel block but NOT rules
    saved_config = json.loads(cfg.read_text(encoding="utf-8"))
    assert "rules" not in saved_config, "rules must not be persisted in config.json"
    assert saved_config["alerts"]["webhook_url"] == "https://hooks.example/abc"
    assert saved_config["alerts"]["line_channel_access_token"] == "secret-line-token"

    # Reload through a fresh ConfigManager — both come back to the right places
    cm2 = ConfigManager(str(cfg), alerts_file=str(alerts))
    assert cm2.config["alerts"]["webhook_url"] == "https://hooks.example/abc"
    assert cm2.config["rules"][0]["name"] == "Auth failures"


def test_legacy_alerts_file_migrates_channel_block_back_to_config(tmp_path):
    """Pre-flip installs have channel creds inside alerts.json; load() pulls
    them back into config.json's ``alerts`` block, then first save() rewrites
    alerts.json with the rules array."""
    from src.config import ConfigManager
    cfg = tmp_path / "config.json"
    alerts = tmp_path / "alerts.json"
    cfg.write_text(json.dumps({
        "api": {"url": "https://p.test", "org_id": "1", "key": "k", "secret": "s"},
        "rules": [{"id": 1, "type": "event", "name": "Old rule", "filter_value": "x"}],
    }), encoding="utf-8")
    # Legacy alerts.json — channel-config layout, no "rules" key
    alerts.write_text(json.dumps({
        "active": ["mail", "webhook"],
        "webhook_url": "https://legacy.example/hook",
        "line_channel_access_token": "legacy-token",
        "line_target_id": "C123",
    }), encoding="utf-8")

    cm = ConfigManager(str(cfg), alerts_file=str(alerts))
    # Legacy channel block migrated into in-memory alerts
    assert cm.config["alerts"]["webhook_url"] == "https://legacy.example/hook"
    assert cm.config["alerts"]["line_channel_access_token"] == "legacy-token"
    # Rules from config.json preserved
    assert cm.config["rules"][0]["name"] == "Old rule"

    cm.save()

    # alerts.json rewritten in new layout
    rewritten = json.loads(alerts.read_text(encoding="utf-8"))
    assert rewritten == {"rules": [{"id": 1, "type": "event", "name": "Old rule", "filter_value": "x"}]}

    # config.json regained the channel block; rules removed
    cleaned = json.loads(cfg.read_text(encoding="utf-8"))
    assert "rules" not in cleaned
    assert cleaned["alerts"]["webhook_url"] == "https://legacy.example/hook"
    assert cleaned["alerts"]["line_channel_access_token"] == "legacy-token"


def test_alerts_file_missing_falls_back_to_defaults(tmp_path):
    """If alerts.json is absent, both rules and the channel block use defaults."""
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
    assert cm.config["rules"] == []


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
    # rules list still exists (empty/defaults), no exception
    assert isinstance(cm.config.get("rules"), list)
    combined = " ".join(r.message for r in caplog.records)
    assert "alerts" in combined.lower() or "Error reading alerts" in combined


def test_first_run_uses_illumio_default_password_no_forced_change(tmp_path):
    """Default initial password is the well-known 'illumio'. Forced first-login
    password change is DISABLED by operator request, so must_change_password is
    NOT armed on first boot (the default stays valid until changed manually)."""
    from src.config import ConfigManager, hash_password
    cfg = tmp_path / "config.json"
    alerts = tmp_path / "alerts.json"
    cfg.write_text(json.dumps({
        "api": {"url": "https://p.test", "org_id": "1", "key": "k", "secret": "s"},
    }), encoding="utf-8")

    cm = ConfigManager(str(cfg), alerts_file=str(alerts))
    gui = cm.config["web_gui"]
    assert gui["_initial_password"] == "illumio"
    assert gui["must_change_password"] is False
    # password is argon2id-hashed, not stored in plaintext
    assert gui["password"].startswith("$argon2")
    # The hash verifies against "illumio"
    from src.config import verify_password
    assert verify_password("illumio", gui["password"]) is True


def test_minimal_config_enables_self_signed_tls_by_default(tmp_path):
    """Minimal config should match the shipped example: HTTPS comes up with
    generated self-signed TLS unless operators explicitly disable it."""
    from src.config import ConfigManager
    cfg = tmp_path / "config.json"
    alerts = tmp_path / "alerts.json"
    cfg.write_text(json.dumps({
        "api": {"url": "https://p.test", "org_id": "1", "key": "k", "secret": "s"},
    }), encoding="utf-8")

    cm = ConfigManager(str(cfg), alerts_file=str(alerts))
    tls = cm.config["web_gui"]["tls"]
    assert tls["enabled"] is True
    assert tls["self_signed"] is True
    assert tls["key_algorithm"] == "ecdsa-p256"
