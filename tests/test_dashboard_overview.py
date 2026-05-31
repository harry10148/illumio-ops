import json, os, tempfile
import pytest
from src.config import ConfigManager


@pytest.fixture
def client(tmp_path):
    fd, path = tempfile.mkstemp(suffix=".json"); os.close(fd)
    with open(path, "w") as f:
        json.dump({"web_gui": {"username": "admin", "password": "pw",
                               "secret_key": "s", "allowed_ips": ["127.0.0.1"]},
                   "pce_cache": {"enabled": False, "db_path": str(tmp_path / "c.sqlite")}}, f)
    cm = ConfigManager(config_file=path)
    from src.gui import _create_app
    app = _create_app(cm, persistent_mode=True)
    app.config["TESTING"] = True; app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        c.post("/api/login", json={"username": "admin", "password": "pw"},
               environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
        yield c
    os.unlink(path)


def test_overview_ven_verdict_from_state(client, tmp_path, monkeypatch):
    from src.gui import _helpers
    sf = str(tmp_path / "state.json")
    json.dump({"ven_summary": {"total": 21, "online": 19, "offline": 2,
                               "degraded": 0, "oldest_heartbeat_age_s": 147600,
                               "attention": [{"host": "x", "reason": "41h no heartbeat"}]}},
              open(sf, "w"))
    monkeypatch.setattr(_helpers, "_resolve_state_file", lambda: sf)
    r = client.get("/api/dashboard/overview", environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert r.status_code == 200
    ven = r.get_json()["ven"]
    assert ven["online"] == 19 and ven["offline"] == 2
    assert ven["verdict"] == "warn"           # offline>=1, not over 10% of 21 (=3)
    assert "as_of" in r.get_json()


def test_overview_ven_unknown_when_missing(client, tmp_path, monkeypatch):
    from src.gui import _helpers
    sf = str(tmp_path / "state.json"); json.dump({}, open(sf, "w"))
    monkeypatch.setattr(_helpers, "_resolve_state_file", lambda: sf)
    r = client.get("/api/dashboard/overview", environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert r.get_json()["ven"]["verdict"] == "unknown"
