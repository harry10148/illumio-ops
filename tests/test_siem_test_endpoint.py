import json, os, tempfile
from unittest.mock import patch
import pytest
from src.config import ConfigManager, hash_password
from src.siem.tester import TestResult


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
                                "dlq_max_per_dest": 10000,
                                "destinations": [{"name": "demo", "transport": "udp",
                                                  "format": "cef",
                                                  "endpoint": "127.0.0.1:514"}]}}, f)
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


def test_test_endpoint_success(client):
    with patch("src.siem.web.send_test_event",
               return_value=TestResult(ok=True, latency_ms=12)):
        resp = client.post("/api/siem/destinations/demo/test",
                           environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 200
    b = resp.get_json()
    assert b["ok"] is True and b["latency_ms"] == 12


def test_test_endpoint_failure(client):
    with patch("src.siem.web.send_test_event",
               return_value=TestResult(ok=False, error="refused", latency_ms=5)):
        resp = client.post("/api/siem/destinations/demo/test",
                           environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 200
    b = resp.get_json()
    assert b["ok"] is False and b["error"] == "refused"


def test_test_endpoint_unknown(client):
    resp = client.post("/api/siem/destinations/nosuch/test",
                       environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 404
