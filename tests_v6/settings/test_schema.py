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
    assert s.schema_version == 1 and s.revision == 0
    assert s.pce.url == "" and s.pce.deployment_type is DeploymentType.ON_PREM
    assert s.web.port == 5443 and s.web.username == "illumio" and s.web.must_change_password is False
    assert s.web.session_lifetime_seconds == 28800 and s.web.allowed_ips == ()
    assert s.web.tls.validity_days == 397 and s.web.tls.auto_renew_days == 30
    assert s.web.tls.key_algorithm == "ecdsa-p256" and s.web.tls.min_version == "TLSv1.2"
    assert s.display.language is Language.EN and s.display.timezone == "local"
    assert s.logging.level == "INFO"


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
