"""Tests for M-1: POST /api/security must verify old_password before changing password.

Audit reference: docs/security-audit-2026-05-22.md M-1.
"""
import json
import os
import tempfile

import pytest

from src.config import ConfigManager, hash_password
from src.gui import build_app
from tests._helpers import _csrf


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sec_client():
    """Minimal app with a known password hash; no rate-limit side effects."""
    tmpdir = tempfile.mkdtemp(prefix="illumio_sec_test_")
    path = os.path.join(tmpdir, "config.json")
    known_hash = hash_password("correct-old-password-here")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "api": {"url": "https://pce.test", "org_id": "1", "key": "k", "secret": "s"},
                "rules": [],
                "web_gui": {
                    "username": "admin",
                    "password": known_hash,
                    "allowed_ips": ["127.0.0.1"],
                    "secret_key": "test-secret",
                },
            },
            f,
        )

    cm = ConfigManager(config_file=path)
    cm.load()
    app = build_app(cm, persistent_mode=True)
    app.config.update({"TESTING": True, "WTF_CSRF_ENABLED": False})

    client = app.test_client()

    # Log in so the session is authenticated
    login = client.post(
        "/api/login",
        json={"username": "admin", "password": "correct-old-password-here"},
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert login.status_code == 200, f"Login failed: {login.get_json()}"

    yield client, cm

    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def must_change_client():
    """App with must_change_password=True set (initial-login flow)."""
    tmpdir = tempfile.mkdtemp(prefix="illumio_mustchange_test_")
    path = os.path.join(tmpdir, "config.json")
    known_hash = hash_password("some-initial-password")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "api": {"url": "https://pce.test", "org_id": "1", "key": "k", "secret": "s"},
                "rules": [],
                "web_gui": {
                    "username": "admin",
                    "password": known_hash,
                    "allowed_ips": ["127.0.0.1"],
                    "secret_key": "test-secret",
                    "must_change_password": True,
                },
            },
            f,
        )

    cm = ConfigManager(config_file=path)
    cm.load()
    app = build_app(cm, persistent_mode=True)
    app.config.update({"TESTING": True, "WTF_CSRF_ENABLED": False})

    client = app.test_client()

    login = client.post(
        "/api/login",
        json={"username": "admin", "password": "some-initial-password"},
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert login.status_code == 200, f"Login failed: {login.get_json()}"

    yield client, cm

    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_change_password_requires_old(sec_client):
    """No old_password field → 400."""
    client, _ = sec_client
    resp = client.post(
        "/api/security",
        json={"new_password": "brandnewpassword12"},
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["ok"] is False
    assert "old_password" in data["error"].lower() or "current password" in data["error"].lower()


def test_change_password_wrong_old(sec_client):
    """Wrong old_password → 400."""
    client, _ = sec_client
    resp = client.post(
        "/api/security",
        json={"new_password": "brandnewpassword12", "old_password": "wrong-password"},
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["ok"] is False
    assert "incorrect" in data["error"].lower() or "current password" in data["error"].lower()


def test_change_password_correct_old(sec_client):
    """Correct old_password → 200, password actually updated in config."""
    client, cm = sec_client
    resp = client.post(
        "/api/security",
        json={
            "new_password": "brandnewpassword12",
            "old_password": "correct-old-password-here",
        },
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True

    # Verify the stored hash actually changed
    cm.load()
    from src.config import verify_password
    assert verify_password("brandnewpassword12", cm.config["web_gui"]["password"])


def test_must_change_password_bypass(must_change_client):
    """When must_change_password=True, old_password is not required; flag removed after success."""
    client, cm = must_change_client
    resp = client.post(
        "/api/security",
        json={"new_password": "completelynewpass12"},
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True

    cm.load()
    # cm.load() injects must_change_password=False as a default even when the
    # key is absent on disk; asserting falsy covers both "absent" and "False".
    assert not cm.config.get("web_gui", {}).get("must_change_password")
    from src.config import verify_password
    assert verify_password("completelynewpass12", cm.config["web_gui"]["password"])


def test_min_password_length_12(sec_client):
    """11-char new_password (below min of 12) → 400."""
    client, _ = sec_client
    resp = client.post(
        "/api/security",
        json={
            "new_password": "short1234AB",   # exactly 11 chars
            "old_password": "correct-old-password-here",
        },
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["ok"] is False
