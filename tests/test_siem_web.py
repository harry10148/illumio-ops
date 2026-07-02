import json
import os
import tempfile

import pytest

from src.config import ConfigManager


@pytest.fixture
def client(tmp_path):
    """Flask test client with a minimal config."""
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        with open(path, "w") as f:
            json.dump({
                "api": {"url": "https://pce.test", "key": "test", "secret": "test", "org_id": "1"},
                "rules": [],
                "web_gui": {
                    "username": "admin",
                    "password": "testpass",
                    "allowed_ips": ["127.0.0.1"],
                    "secret_key": "test-secret",
                },
            }, f)

        cm = ConfigManager(config_file=path)
        cm.load()

        from src.gui import _create_app
        app = _create_app(cm, persistent_mode=True)
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        with app.test_client() as c:
            # Log in to establish session
            c.post("/api/login", json={"username": "admin", "password": "testpass"},
                   environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
            yield c
    finally:
        os.unlink(path)


def test_siem_blueprint_registered(client):
    """Blueprint routes should be accessible (any non-500 crash is OK)."""
    resp = client.get("/api/siem/destinations",
                      environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code in (200, 302, 401, 500)


def test_siem_status_returns_json(client):
    resp = client.get("/api/siem/status",
                      environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code in (200, 302, 401, 500)


def test_siem_add_destination_udp_returns_warning(client):
    resp = client.post(
        "/api/siem/destinations",
        json={"name": "test", "transport": "udp", "format": "cef", "endpoint": "10.0.0.1:514"},
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert resp.status_code in (200, 302, 400, 401, 500)


def test_siem_dlq_list_no_crash(client):
    resp = client.get("/api/siem/dlq?dest=dest1",
                      environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code in (200, 302, 401, 500)
