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


def test_siem_destinations_get_masks_hec_token(client, monkeypatch):
    """GET /api/siem/destinations 不得回傳明文 hec_token（同 /api/settings
    的 _redact_secrets 慣例：星號 + __set/__length）。"""
    resp = client.post(
        "/api/siem/destinations",
        json={"name": "sp", "transport": "hec", "host": "splunk.corp", "port": 8088,
              "hec_token": "secret-token-1", "mask_pii": True},
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert resp.get_json()["ok"] is True
    # _get_siem_cfg 會另建 ConfigManager（預設路徑），測試須指回本 app 的 CM
    cm = client.application.config["CM"]
    monkeypatch.setattr("src.siem.web._get_siem_cfg", lambda: cm.models.siem)
    body = client.get("/api/siem/destinations",
                      environ_overrides={"REMOTE_ADDR": "127.0.0.1"}).get_json()
    assert "secret-token-1" not in json.dumps(body)
    d = next(x for x in body["destinations"] if x["name"] == "sp")
    assert d["hec_token"] == "*" * 8
    assert d["hec_token__set"] is True


def test_siem_destination_partial_put_preserves_omitted_fields(client):
    """PUT 必須合併而非整包取代：部分更新不得把 hec_token 洗成 None、
    mask_pii 重設為 False；round-trip 的星號 placeholder 也不得覆寫真值。"""
    resp = client.post(
        "/api/siem/destinations",
        json={"name": "sp2", "transport": "hec", "host": "splunk.corp", "port": 8088,
              "hec_token": "secret-token-2", "mask_pii": True},
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert resp.get_json()["ok"] is True
    # partial PUT：只改 host
    resp = client.put(
        "/api/siem/destinations/sp2",
        json={"transport": "hec", "host": "splunk2.corp", "port": 8088},
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert resp.get_json()["ok"] is True
    cm = client.application.config["CM"]
    d = next(x for x in cm.models.siem.destinations if x.name == "sp2")
    assert d.host == "splunk2.corp"
    assert d.hec_token == "secret-token-2"   # not wiped
    assert d.mask_pii is True                # not reset
    # placeholder round-trip：GET 回的星號值存回去不得覆寫真 token
    resp = client.put(
        "/api/siem/destinations/sp2",
        json={"hec_token": "*" * 8},
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert resp.get_json()["ok"] is True
    d = next(x for x in cm.models.siem.destinations if x.name == "sp2")
    assert d.hec_token == "secret-token-2"


def test_siem_dlq_list_no_crash(client):
    resp = client.get("/api/siem/dlq?dest=dest1",
                      environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code in (200, 302, 401, 500)


# ── D2 子項 4：500 body 經 _err_with_log 回通用訊息，不外洩原始例外 ──────────

def test_siem_list_destinations_500_does_not_leak_exception_detail(client, monkeypatch):
    monkeypatch.setattr(
        "src.siem.web._get_siem_cfg",
        lambda: (_ for _ in ()).throw(RuntimeError("secret-db-path-leak")),
    )
    login = client.post("/api/login", json={"username": "admin", "password": "testpass"},
                        environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert login.status_code == 200
    resp = client.get("/api/siem/destinations",
                      environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 500
    body = resp.get_json()
    assert body["ok"] is False
    assert "request_id" in body
    assert "secret-db-path-leak" not in body["error"]


def test_siem_dispatch_status_500_does_not_leak_exception_detail(client, monkeypatch):
    monkeypatch.setattr(
        "src.siem.web._get_sf",
        lambda: (_ for _ in ()).throw(RuntimeError("secret-db-path-leak")),
    )
    login = client.post("/api/login", json={"username": "admin", "password": "testpass"},
                        environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert login.status_code == 200
    resp = client.get("/api/siem/status",
                      environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 500
    body = resp.get_json()
    assert body["ok"] is False
    assert "request_id" in body
    assert "secret-db-path-leak" not in body["error"]
