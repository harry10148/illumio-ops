import json, os, tempfile
import pytest
from src.config import ConfigManager, hash_password


@pytest.fixture
def client(tmp_path):
    fd, path = tempfile.mkstemp(suffix=".json"); os.close(fd)
    try:
        salt = "testsalt"
        h = hash_password(salt, "pw")
        with open(path, "w") as f:
            json.dump({"web_gui": {"username": "admin", "password_hash": h,
                                    "password_salt": salt, "secret_key": "s",
                                    "allowed_ips": ["127.0.0.1"]},
                       "siem": {"enabled": False, "dispatch_tick_seconds": 5,
                                "dlq_max_per_dest": 10000}}, f)
        cm = ConfigManager(config_file=path)
        from src.gui import _create_app
        app = _create_app(cm, persistent_mode=True)
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        with app.test_client() as c:
            c.post("/api/login", json={"username": "admin", "password": "pw"},
                   environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
            yield c
    finally:
        os.unlink(path)


def test_get_forwarder(client):
    resp = client.get("/api/siem/forwarder",
                      environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 200
    b = resp.get_json()
    assert b["enabled"] is False
    assert "destinations" not in b  # served via /api/siem/destinations


def test_put_forwarder_happy(client):
    resp = client.put("/api/siem/forwarder",
                      json={"enabled": True, "dispatch_tick_seconds": 10,
                            "dlq_max_per_dest": 5000},
                      environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 200
    b = resp.get_json()
    assert b["ok"] is True and b["requires_restart"] is True


def test_put_forwarder_invalid(client):
    resp = client.put("/api/siem/forwarder",
                      json={"dispatch_tick_seconds": 0},
                      environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 422
