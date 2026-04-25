import json
import os
import tempfile
from unittest.mock import MagicMock

import pytest

import src.gui as gui_module
from src.config import ConfigManager, hash_password


@pytest.fixture
def client():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        salt = "testsalt"
        h = hash_password(salt, "pw")
        with open(path, "w") as f:
            json.dump({
                "web_gui": {
                    "username": "admin",
                    "password_hash": h,
                    "password_salt": salt,
                    "secret_key": "s",
                    "allowed_ips": ["127.0.0.1"],
                },
                "pce_cache": {"enabled": False},
                "siem": {"enabled": False, "destinations": []},
            }, f)
        cm = ConfigManager(config_file=path)
        from src.gui import _create_app
        app = _create_app(cm, persistent_mode=True)
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        with app.test_client() as c:
            c.post("/api/login", json={"username": "admin", "password": "pw"},
                   environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
            yield c, path
    finally:
        os.unlink(path)
        gui_module._GUI_OWNS_DAEMON = False
        gui_module._DAEMON_SCHEDULER = None
        gui_module._DAEMON_RESTART_FN = None


def test_save_then_restart_roundtrip(client, tmp_path):
    c, path = client
    resp = c.put("/api/cache/settings", json={
        "enabled": True,
        "events_retention_days": 42,
        "db_path": str(tmp_path / "cache.sqlite"),
    }, environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 200
    b = resp.get_json()
    assert b["ok"] is True
    assert b["requires_restart"] is True

    with open(path) as f:
        cfg = json.load(f)
    assert cfg["pce_cache"]["enabled"] is True
    assert cfg["pce_cache"]["events_retention_days"] == 42

    fn = MagicMock(return_value=MagicMock())
    gui_module._GUI_OWNS_DAEMON = True
    gui_module._DAEMON_RESTART_FN = fn
    try:
        resp = c.post("/api/daemon/restart",
                      environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
        b2 = resp.get_json()
        assert resp.status_code == 200
        assert b2 is not None
        assert b2["ok"] is True
        fn.assert_called_once()
    finally:
        gui_module._GUI_OWNS_DAEMON = False
        gui_module._DAEMON_RESTART_FN = None
