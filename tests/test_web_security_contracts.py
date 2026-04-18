"""Freeze Web GUI security contracts before migrating to Flask extensions.

Phase 4 migrates to flask-wtf/flask-limiter/flask-talisman/flask-login/argon2-cffi.
These tests lock down behavior that MUST survive: login success/failure,
CSRF rejection, rate limit 429, session persistence, logout.
"""
from __future__ import annotations

import json
import pytest


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    """Build a test Flask app against a temp config."""
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "api": {"url": "https://pce.test", "org_id": "1", "key": "k", "secret": "s"},
        "web_gui": {
            "username": "illumio",
            "password_hash": "",  # let _ensure_web_gui_secret default to 'illumio'
            "password_salt": "",
            "secret_key": "",
            "allowed_ips": [],
        },
    }), encoding="utf-8")
    from src.config import ConfigManager
    from src.gui import build_app  # factory introduced in Task 3
    # flask-limiter uses per-app memory storage, so each app instance starts fresh.
    cm = ConfigManager(str(cfg))
    app = build_app(cm)
    app.config["TESTING"] = True
    return app.test_client(), cm


def test_login_valid_credentials_sets_session(app_client):
    client, _cm = app_client
    r = client.post("/api/login", json={"username": "illumio", "password": "illumio"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert "csrf_token" in body


def test_login_invalid_credentials_rejected(app_client):
    client, _cm = app_client
    r = client.post("/api/login", json={"username": "illumio", "password": "wrong"})
    assert r.status_code in (401, 403)


def test_rate_limit_triggers_429_after_5_failures(app_client):
    client, _cm = app_client
    for _ in range(5):
        client.post("/api/login", json={"username": "x", "password": "y"})
    r = client.post("/api/login", json={"username": "x", "password": "y"})
    assert r.status_code == 429


def test_csrf_required_on_post_after_login(app_client):
    client, _cm = app_client
    # Login first
    client.post("/api/login", json={"username": "illumio", "password": "illumio"})
    # POST without csrf header should be rejected
    r = client.post("/api/security", json={"allowed_ips": ["192.168.1.1"]})
    assert r.status_code in (400, 403), f"CSRF should block; got {r.status_code}"


def test_logout_clears_session(app_client):
    client, _cm = app_client
    client.post("/api/login", json={"username": "illumio", "password": "illumio"})
    client.get("/logout")
    # After logout, protected endpoint should be unauthorized
    r = client.get("/api/dashboard")
    assert r.status_code in (302, 401), f"Logout must unauth; got {r.status_code}"


def test_ip_allowlist_blocks_non_matching_client(app_client):
    client, cm = app_client
    cm.config["web_gui"]["allowed_ips"] = ["10.0.0.0/8"]
    cm.save()
    # Client is 127.0.0.1 (flask test); should be blocked.
    # Current behavior: TCP RST drop (returns empty 200 in test context via _RstDrop handler).
    # Post-migration target: returns 403. Accept both.
    r = client.get("/")
    assert r.status_code in (200, 403), f"Blocked IP should be rejected; got {r.status_code}"


def test_rate_limit_429_returns_json_not_html(app_client):
    """Regression: 429 must return JSON error body so API clients can parse it."""
    client, _cm = app_client
    # Exhaust the limit
    for _ in range(6):
        r = client.post("/api/login", json={"username": "x", "password": "y"})
    assert r.status_code == 429
    body = r.get_json(silent=True)
    assert body is not None, f"429 body must be JSON, got: {r.data[:200]!r}"
    assert body.get("ok") is False
