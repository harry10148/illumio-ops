import json
import os
import tempfile

import pytest

from src.config import ConfigManager, hash_password


@pytest.fixture
def client(tmp_path):
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        salt = "testsalt"
        pass_hash = hash_password(salt, "pw")
        with open(path, "w") as f:
            json.dump({
                "web_gui": {
                    "username": "admin",
                    "password_hash": pass_hash,
                    "password_salt": salt,
                    "secret_key": "s",
                    "allowed_ips": ["127.0.0.1"],
                },
                "pce_cache": {
                    "enabled": False,
                    "db_path": str(tmp_path / "cache.sqlite"),
                },
            }, f)

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


def test_get_cache_settings(client):
    resp = client.get("/api/cache/settings",
                      environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["enabled"] is False
    assert "traffic_filter" in body and "traffic_sampling" in body


def test_put_cache_settings_happy(client, tmp_path):
    resp = client.put("/api/cache/settings", json={
        "enabled": True,
        "db_path": str(tmp_path / "cache.sqlite"),
        "events_retention_days": 60,
        "traffic_raw_retention_days": 5,
        "traffic_agg_retention_days": 60,
        "events_poll_interval_seconds": 300,
        "traffic_poll_interval_seconds": 3600,
        "rate_limit_per_minute": 400,
        "async_threshold_events": 10000,
        "traffic_filter": {
            "actions": ["blocked"],
            "workload_label_env": ["prod"],
            "ports": [443],
            "protocols": ["TCP"],
            "exclude_src_ips": ["10.0.0.1"],
        },
        "traffic_sampling": {
            "sample_ratio_allowed": 1,
            "max_rows_per_batch": 10000,
        },
    }, environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 200
    b = resp.get_json()
    assert b["ok"] is True and b["requires_restart"] is True


def test_put_cache_invalid_ip(client):
    resp = client.put("/api/cache/settings",
                      json={"traffic_filter": {"exclude_src_ips": ["not-an-ip"]}},
                      environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 422
    assert resp.get_json()["ok"] is False


def test_put_cache_bad_poll_interval(client):
    resp = client.put("/api/cache/settings",
                      json={"events_poll_interval_seconds": 5},
                      environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 422
