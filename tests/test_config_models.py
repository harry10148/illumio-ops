"""Pydantic schema validation for illumio_ops config."""
from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_api_settings_valid():
    from src.config_models import ApiSettings
    a = ApiSettings(url="https://pce.test:8443", org_id="1", key="k", secret="s")
    assert str(a.url).startswith("https://pce.test")
    assert a.verify_ssl is True  # default


def test_api_settings_rejects_non_http_url():
    from src.config_models import ApiSettings
    with pytest.raises(ValidationError) as exc:
        ApiSettings(url="ftp://wrong.test", org_id="1", key="k", secret="s")
    assert "http or https" in str(exc.value).lower()


def test_smtp_settings_port_range():
    from src.config_models import SmtpSettings
    # Valid
    s = SmtpSettings(host="mail.test", port=587)
    assert s.port == 587
    # Invalid (negative)
    with pytest.raises(ValidationError):
        SmtpSettings(host="mail.test", port=-1)
    # Invalid (too large)
    with pytest.raises(ValidationError):
        SmtpSettings(host="mail.test", port=99999)


def test_rule_scheduler_settings_check_interval_lower_bound():
    from src.config_models import RuleSchedulerSettings
    s = RuleSchedulerSettings(enabled=True, check_interval_seconds=60)
    assert s.check_interval_seconds == 60
    # Sub-minute polling would hammer the PCE; reject
    with pytest.raises(ValidationError):
        RuleSchedulerSettings(enabled=True, check_interval_seconds=10)


def test_config_schema_fills_defaults_for_missing_sections():
    """When config.json omits an entire section, pydantic must fill from defaults."""
    from src.config_models import ConfigSchema
    minimal = {
        "api": {"url": "https://p.test", "org_id": "1", "key": "k", "secret": "s"},
    }
    cfg = ConfigSchema.model_validate(minimal)
    # settings defaults must be present
    assert cfg.settings.language == "en"
    assert cfg.web_gui.tls.enabled is False


def test_config_schema_rejects_unknown_top_level_keys():
    """Typos in config.json (e.g. 'aps' instead of 'api') must surface as error."""
    from src.config_models import ConfigSchema
    with pytest.raises(ValidationError):
        ConfigSchema.model_validate({
            "api": {"url": "https://p.test", "org_id": "1", "key": "k", "secret": "s"},
            "unknown_section": {"foo": "bar"},
        })


def test_config_example_file_validates():
    """config/config.json.example must always pass validation (regression guard)."""
    import json
    from pathlib import Path
    from src.config_models import ConfigSchema
    example = Path(__file__).parent.parent / "config" / "config.json.example"
    with open(example, "r", encoding="utf-8") as f:
        data = json.load(f)
    ConfigSchema.model_validate(data)  # must not raise


def test_dumped_model_has_all_legacy_dict_keys():
    """model_dump() output must include every key that the legacy
    _DEFAULT_CONFIG dict had, so cm.config[...] access patterns survive."""
    from src.config_models import ConfigSchema
    cfg = ConfigSchema.model_validate({
        "api": {"url": "https://p.test", "org_id": "1", "key": "k", "secret": "s"},
    })
    dumped = cfg.model_dump()
    for top_level in ("api", "alerts", "email", "smtp", "settings", "rules",
                      "report", "report_schedules", "pce_profiles",
                      "active_pce_id", "rule_scheduler", "web_gui"):
        assert top_level in dumped, f"missing {top_level} in model_dump()"


def test_pce_cache_settings_defaults():
    from src.config_models import PceCacheSettings
    cfg = PceCacheSettings()
    assert cfg.enabled is False
    assert cfg.rate_limit_per_minute == 400
    assert cfg.events_retention_days == 90


def test_pce_cache_settings_validation():
    from src.config_models import PceCacheSettings
    import pytest
    with pytest.raises(Exception):
        PceCacheSettings(rate_limit_per_minute=600)  # > 500 should fail


def test_siem_forwarder_settings_defaults():
    from src.config_models import SiemForwarderSettings
    cfg = SiemForwarderSettings()
    assert cfg.enabled is False
    assert cfg.destinations == []
    assert cfg.dispatch_tick_seconds == 5
