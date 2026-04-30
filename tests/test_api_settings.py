"""Tests for Phase 4 security hardening: secrets redaction, settings allowlist, URL validation."""
import json
import os
import tempfile

import pytest

from src.config import ConfigManager, hash_password
from src.gui import build_app as _create_app


def _csrf(login_response) -> str:
    return (login_response.get_json() or {}).get("csrf_token", "")


@pytest.fixture
def temp_config_file():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    with open(path, "w") as f:
        json.dump(
            {
                "api": {
                    "url": "https://pce.example.com:8443",
                    "key": "myapikey",
                    "secret": "mysecret",
                    "org_id": "1",
                },
                "smtp": {
                    "host": "smtp.example.com",
                    "port": 587,
                    "password": "smtppassword",
                },
                "alerts": {
                    "line_channel_access_token": "mytoken123",
                    "webhook_url": "https://hooks.example.com/abc",
                },
                "rules": [],
            },
            f,
        )
    yield path
    os.unlink(path)


@pytest.fixture
def app(temp_config_file):
    cm = ConfigManager(config_file=temp_config_file)
    cm.load()
    cm.config["web_gui"] = {
        "username": "admin",
        "password": hash_password("testpass"),
        "allowed_ips": [],
        "secret_key": "test-secret",
    }
    cm.save()
    application = _create_app(cm, persistent_mode=True)
    application.config.update({"TESTING": True})
    yield application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def authed_client(client):
    login = client.post("/api/login", json={"username": "admin", "password": "testpass"})
    assert login.status_code == 200
    csrf = _csrf(login)
    return client, csrf


# ── Test 1: secrets are redacted in GET /api/settings ─────────────────────────

def test_redaction_response(authed_client):
    client, csrf = authed_client
    res = client.get("/api/settings")
    assert res.status_code == 200
    body = res.get_json()

    # api.key and api.secret must be redacted
    api = body.get("api", {})
    assert api.get("key") != "myapikey", "api.key should be redacted"
    assert api.get("secret") != "mysecret", "api.secret should be redacted"

    # smtp.password must be redacted
    smtp = body.get("smtp", {})
    assert smtp.get("password") != "smtppassword", "smtp.password should be redacted"

    # alerts token and webhook should be redacted
    alerts = body.get("alerts", {})
    assert alerts.get("line_channel_access_token") != "mytoken123", (
        "line_channel_access_token should be redacted"
    )
    assert alerts.get("webhook_url") != "https://hooks.example.com/abc", (
        "webhook_url should be redacted"
    )

    # Non-secret fields must still be present
    assert api.get("url") == "https://pce.example.com:8443"
    assert smtp.get("host") == "smtp.example.com"


# ── Test 2: mass-assignment via __proto__ or unknown keys is rejected ──────────

def test_mass_assignment_rejected(authed_client, app):
    client, csrf = authed_client
    res = client.post(
        "/api/settings",
        json={"smtp": {"__proto__": "x", "host": "test.host"}},
        headers={"X-CSRF-Token": csrf},
    )
    assert res.status_code == 200

    cm = app.config["CM"]
    cm.load()
    smtp_cfg = cm.config.get("smtp", {})
    assert "__proto__" not in smtp_cfg, "__proto__ should be filtered out by allowlist"
    assert smtp_cfg.get("host") == "test.host", "Allowed key 'host' should be saved"


# ── Test 3: api.url with ftp:// scheme is rejected with 400 ───────────────────

def test_pce_url_scheme_validator(authed_client):
    client, csrf = authed_client
    res = client.post(
        "/api/settings",
        json={"api": {"url": "ftp://malicious.host"}},
        headers={"X-CSRF-Token": csrf},
    )
    assert res.status_code == 400
    body = res.get_json()
    assert body.get("ok") is False
