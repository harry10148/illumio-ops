"""Tests for the flag-gated /v2 preview route (Phase 2A Task 1 scaffold).

`client` (built on `app_persistent`) comes from tests/conftest.py and leaves
`web_gui.enable_v2_preview` at its default (False), so it doubles as the
flag-off fixture. The flag-on fixture below mirrors conftest.py's
`app_persistent`/`client` construction (tests/conftest.py:97-127) verbatim,
only adding `enable_v2_preview: True` to the web_gui block.
"""
import pytest

from src.config import ConfigManager, hash_password
from src.gui import build_app as _create_app


@pytest.fixture
def app_v2_enabled(temp_config_file):
    cm = ConfigManager(config_file=temp_config_file)
    cm.load()

    cm.config["web_gui"] = {
        "username": "admin",
        "password": hash_password("testpass"),
        "allowed_ips": ["127.0.0.1", "192.168.1.0/24"],
        "secret_key": "x" * 64,
        "enable_v2_preview": True,
    }
    cm.save()

    app = _create_app(cm, persistent_mode=True)
    app.config.update({"TESTING": True})
    yield app


@pytest.fixture
def client_v2_enabled(app_v2_enabled):
    return app_v2_enabled.test_client()


def test_v2_route_404_when_flag_off(client):
    """Default config leaves enable_v2_preview False — /v2 must not exist.

    Logs in first: unauthenticated requests to *any* unmatched path are
    redirected to /login by the app-wide `security_check` before_request
    hook (src/gui/__init__.py) before Flask ever raises a 404 for the
    missing route, so an unauthenticated probe can't distinguish "route
    absent" from "route present but requires login".
    """
    login = client.post("/api/login", json={"username": "admin", "password": "testpass"})
    assert login.status_code == 200

    resp = client.get("/v2")
    assert resp.status_code == 404


def test_v2_route_requires_login_when_flag_on(client_v2_enabled):
    """Route exists once the flag is on, but is still login_required."""
    resp = client_v2_enabled.get("/v2")
    assert resp.status_code in (302, 401)
    assert resp.status_code != 404


def test_v2_route_serves_shell_when_flag_on(client_v2_enabled):
    login = client_v2_enabled.post(
        "/api/login", json={"username": "admin", "password": "testpass"}
    )
    assert login.status_code == 200

    resp = client_v2_enabled.get("/v2")
    assert resp.status_code == 200
    assert b"css/v2/tokens.css" in resp.data
    assert b"js/v2/app.mjs" in resp.data
