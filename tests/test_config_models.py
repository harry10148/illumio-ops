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


@pytest.mark.parametrize("deployment_type", ["saas", "on_prem"])
def test_api_settings_supports_explicit_deployment_and_console_url(deployment_type):
    """Deployment type and explicit console URLs are configuration contracts."""
    from src.config_models import ApiSettings
    cfg = ApiSettings(
        deployment_type=deployment_type,
        url="https://ap-scp45.illum.io",
        console_url="https://console.illum.io/",
    )
    assert cfg.deployment_type == deployment_type
    assert cfg.console_url == "https://console.illum.io"


def test_api_settings_rejects_unknown_deployment_type():
    from src.config_models import ApiSettings
    with pytest.raises(ValidationError, match="deployment_type"):
        ApiSettings(deployment_type="cloud")


def test_api_settings_accepts_empty_console_url_and_rejects_non_http_url():
    from src.config_models import ApiSettings
    assert ApiSettings(console_url="").console_url == ""
    with pytest.raises(ValidationError, match="console_url"):
        ApiSettings(console_url="ftp://console.illum.io")


@pytest.mark.parametrize(("field", "value"), [
    ("url", "https://fake-user:fake-pass@pce.example.com:8443"),
    ("console_url", "https://fake-user:fake-pass@console.illum.io"),
])
def test_api_settings_rejects_userinfo_in_pce_urls(field, value):
    from src.config_models import ApiSettings

    with pytest.raises(ValidationError, match=field):
        ApiSettings(**{field: value})


def test_api_settings_keeps_valid_ipv6_pce_urls():
    from src.config_models import ApiSettings

    cfg = ApiSettings(
        url="http://[2001:db8::1]:8443",
        console_url="https://[2001:db8::2]",
    )

    assert cfg.url == "http://[2001:db8::1]:8443"
    assert cfg.console_url == "https://[2001:db8::2]"


def test_web_gui_public_url_is_declared_and_validated():
    from src.config_models import WebGuiSettings
    assert WebGuiSettings(public_url="https://gui.example/").public_url == "https://gui.example"
    assert WebGuiSettings(public_url="").public_url == ""
    with pytest.raises(ValidationError, match="public_url"):
        WebGuiSettings(public_url="ftp://gui.example")


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
    assert cfg.web_gui.tls.enabled is True  # TLS enabled by default (Phase 2)


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
                      "report", "report_schedules",
                      "rule_scheduler", "web_gui"):
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
    assert cfg.dispatch_tick_seconds == 30


def test_report_snapshot_retention_default():
    from src.config_models import ReportSettings
    r = ReportSettings()
    assert r.snapshot_retention_days == 90
    assert r.draft_actions_enabled is True


def test_report_snapshot_retention_validates_range():
    import pytest
    from pydantic import ValidationError
    from src.config_models import ReportSettings
    with pytest.raises(ValidationError):
        ReportSettings(snapshot_retention_days=0)
    with pytest.raises(ValidationError):
        ReportSettings(snapshot_retention_days=3651)


def test_config_schema_has_no_pce_profile_fields():
    """Profile 概念已移除：schema 不得再宣告它，否則舊資料會被當成合法設定留著。"""
    from src.config_models import ConfigSchema
    fields = set(ConfigSchema.model_fields)
    assert "pce_profiles" not in fields
    assert "active_pce_id" not in fields


def test_config_manager_has_no_profile_methods():
    """Case-insensitive match on `pce` or `profile` anywhere in the name——原本只比對
    `pce_profile`/`active_profile` 這兩個子字串會漏掉 `get_active_pce_id`（沒有底線相接
    的 `pce_profile`），而 `sync_api_to_active_profile` 正是這樣從第一版盤點裡漏網的。"""
    from src.config import ConfigManager
    leftovers = [n for n in dir(ConfigManager)
                 if "pce" in n.lower() or "profile" in n.lower()]
    assert leftovers == [], f"still present: {leftovers}"
