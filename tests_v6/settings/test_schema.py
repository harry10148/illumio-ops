import pytest
from pydantic import ValidationError

from illumio_ops.domain.values import DeploymentType, Language
from illumio_ops.settings.schema import PceSettings, Settings, default_settings
from illumio_ops.settings.secrets import MASK, SECRET_FIELDS, redact

from .conftest import HASH, KEY


def _pce(**kw):
    base = {"url": "https://pce.example.com:8443", "org_id": "1", "api_key": "k", "api_secret": "s",
            "deployment_type": "on_prem", "console_url": None, "verify_tls": True,
            "events_timeout_seconds": None}
    return PceSettings(**(base | kw))


def test_default_settings_values():
    s = default_settings(password_hash=HASH, secret_key=KEY, port=5443)
    assert s.schema_version == 2 and s.revision == 0
    assert s.pce.url == "" and s.pce.deployment_type is DeploymentType.ON_PREM
    assert s.web.port == 5443 and s.web.username == "illumio" and s.web.must_change_password is False
    assert s.web.session_lifetime_seconds == 28800 and s.web.allowed_ips == ()
    assert s.web.tls.validity_days == 397 and s.web.tls.auto_renew_days == 30
    assert s.web.tls.key_algorithm == "ecdsa-p256" and s.web.tls.min_version == "TLSv1.2"
    assert s.display.language is Language.EN and s.display.timezone == "local"
    assert s.logging.level == "INFO"
    c = s.collection
    assert c.enabled is True and c.traffic_interval_seconds == 600 and c.events_interval_seconds == 300
    assert c.inventory_interval_seconds == 3600 and c.rate_limit_per_minute == 400
    assert c.backfill_days == 30 and c.disk_free_warn_gb == 10
    assert (c.retention.flow_days, c.retention.event_days, c.retention.rollup_days, c.retention.baseline_days) == (35, 90, 180, 30)
    assert c.archive.enabled is False and c.archive.retention_days == 0


def test_verify_tls_accepts_ca_bundle_path():
    assert _pce(verify_tls="/etc/pki/ca.pem").verify_tls == "/etc/pki/ca.pem"
    assert _pce(verify_tls=False).verify_tls is False


def test_verify_tls_rejects_relative_path():
    with pytest.raises(ValidationError):
        _pce(verify_tls="ca.pem")


def test_url_trailing_slash_stripped_and_scheme_required():
    assert _pce(url="https://pce.example.com:8443/").url == "https://pce.example.com:8443"
    assert _pce(url="").url == ""
    with pytest.raises(ValidationError):
        _pce(url="pce.example.com")


def test_org_id_must_be_digits_or_empty():
    assert _pce(org_id="").org_id == ""
    with pytest.raises(ValidationError):
        _pce(org_id="org1")


def test_password_hash_must_be_argon2():
    d = default_settings(password_hash=HASH, secret_key=KEY).model_dump(mode="json")
    d["web"]["password_hash"] = "plaintext"
    with pytest.raises(ValidationError):
        Settings.model_validate(d)


def test_secret_key_must_be_64_hex():
    with pytest.raises(ValidationError):
        default_settings(password_hash=HASH, secret_key="short")


def test_models_are_frozen(initial):
    with pytest.raises(ValidationError):
        initial.web.port = 1


def test_redact_masks_nonempty_secrets_only(initial):
    r = redact(initial)
    assert r["web"]["password_hash"] == MASK and r["web"]["secret_key"] == MASK
    assert r["pce"]["api_key"] == "" and r["pce"]["api_secret"] == ""  # empty stays empty: "not set"
    assert SECRET_FIELDS == {"pce.api_key", "pce.api_secret", "web.password_hash", "web.secret_key"}


def test_timezone_accepts_the_5x_formats():
    from illumio_ops.settings.schema import DisplaySettings

    for tz in ("local", "UTC", "UTC+8", "UTC-5", "UTC+5.5", "Asia/Taipei"):
        assert DisplaySettings(language="en", timezone=tz).timezone == tz
    for bad in ("UTC+24", "Mars/Base", "../etc/passwd", "GMT+8x", ""):
        with pytest.raises(ValidationError):
            DisplaySettings(language="en", timezone=bad)


# ── final review fixes ─────────────────────────────────────────────────────

def _with_web(**web):
    d = default_settings(password_hash=HASH, secret_key=KEY).model_dump(mode="json")
    d["web"].update(web)
    return d


def test_allowed_ips_entries_must_be_addresses():
    from illumio_ops.settings.store import SettingsInvalid, validate_settings

    validate_settings(_with_web(allowed_ips=["10.0.0.0/8", "::1", "192.168.1.7"]))
    with pytest.raises(SettingsInvalid) as e:
        validate_settings(_with_web(allowed_ips=["10.0.0.0/8", "10.0.0.0/33", "server.example"]))
    assert [loc for loc, _ in e.value.errors] == ["web.allowed_ips.1", "web.allowed_ips.2"]


def test_certificate_paths_must_be_absolute():
    from illumio_ops.settings.store import SettingsInvalid, validate_settings

    d = _with_web()
    d["web"]["tls"].update(cert_file="certs/c.pem", key_file="/etc/k.pem")
    with pytest.raises(SettingsInvalid) as e:
        validate_settings(d)
    assert [loc for loc, _ in e.value.errors] == ["web.tls.cert_file"]


def _with_collection(**changes):
    d = default_settings(password_hash=HASH, secret_key=KEY).model_dump(mode="json")
    for dotted, value in changes.items():
        node = d["collection"]
        *parents, leaf = dotted.split("__")
        for part in parents:
            node = node[part]
        node[leaf] = value
    return d


def test_retention_flow_days_below_baseline_is_invalid():
    from illumio_ops.settings.store import SettingsInvalid, validate_settings
    with pytest.raises(SettingsInvalid) as e:
        validate_settings(_with_collection(retention__flow_days=20))
    [(loc, msg)] = e.value.errors
    assert loc == "collection.retention" and "flow_days" in msg and "20" not in msg


def test_retention_rollup_below_flow_is_invalid():
    with pytest.raises(ValidationError):
        Settings.model_validate(_with_collection(retention__rollup_days=31))


def test_collection_unknown_key_is_invalid():
    d = _with_collection()
    d["collection"]["traffic_filter"] = {"actions": ["allowed"]}
    with pytest.raises(ValidationError):
        Settings.model_validate(d)


def test_collection_interval_bounds():
    with pytest.raises(ValidationError):
        Settings.model_validate(_with_collection(traffic_interval_seconds=60))
