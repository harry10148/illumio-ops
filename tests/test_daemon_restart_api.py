import json, os, tempfile
from unittest.mock import MagicMock
import pytest
import src.gui as gui_module
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
                                    "allowed_ips": ["127.0.0.1"]}}, f)
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
        gui_module._GUI_OWNS_DAEMON = False
        gui_module._DAEMON_SCHEDULER = None
        gui_module._DAEMON_RESTART_FN = None


def test_restart_not_owned_returns_409(client):
    gui_module._GUI_OWNS_DAEMON = False
    resp = client.post("/api/daemon/restart",
                       environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 409
    assert "external" in resp.get_json()["error"].lower()


def test_restart_owned_calls_hook(client):
    gui_module._GUI_OWNS_DAEMON = True
    fn = MagicMock(return_value=MagicMock())
    gui_module._DAEMON_RESTART_FN = fn
    resp = client.post("/api/daemon/restart",
                       environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    fn.assert_called_once()
