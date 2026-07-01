import json
import os
import tempfile

import pytest

from src.config import ConfigManager


@pytest.fixture
def client(tmp_path):
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        with open(path, "w") as f:
            json.dump({
                "web_gui": {
                    "username": "admin",
                    "password": "pw",
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
        "archive_enabled": True,
        "archive_dir": str(tmp_path / "archive"),
        "archive_interval_hours": 6,
        "archive_gzip_after_days": 3,
        "archive_retention_days": 90,
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


def test_put_cache_archive_roundtrip(client):
    """archive 四欄能透過既有 /api/cache/settings round-trip（UI 表單依賴此契約）。"""
    resp = client.put("/api/cache/settings", json={
        "archive_enabled": True,
        "archive_dir": "/mnt/wormstore/illumio",
        "archive_interval_hours": 6,
        "archive_gzip_after_days": 3,
        "archive_retention_days": 365,
    }, environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    got = client.get("/api/cache/settings",
                     environ_overrides={"REMOTE_ADDR": "127.0.0.1"}).get_json()
    assert got["archive_enabled"] is True
    assert got["archive_dir"] == "/mnt/wormstore/illumio"
    assert got["archive_interval_hours"] == 6
    assert got["archive_gzip_after_days"] == 3
    assert got["archive_retention_days"] == 365


def test_put_cache_archive_invalid(client):
    """archive_interval_hours 有 ge=1 下限，0 應驗證失敗回 422。"""
    resp = client.put("/api/cache/settings",
                      json={"archive_interval_hours": 0},
                      environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 422
    assert resp.get_json()["ok"] is False


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


def test_retention_run_returns_counts(client):
    resp = client.post("/api/cache/retention/run",
                       environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert set(body.keys()) >= {"events", "traffic_raw", "traffic_agg", "dead_letter"}
    for v in body.values():
        assert isinstance(v, int)


def test_retention_run_requires_login(tmp_path):
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        with open(path, "w") as f:
            json.dump({
                "web_gui": {
                    "username": "admin",
                    "password": "pw",
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
            resp = c.post("/api/cache/retention/run",
                          environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
            assert resp.status_code in (302, 401)
    finally:
        os.unlink(path)


def test_retention_run_passes_archive_enabled(tmp_path):
    """手動入口（Web GUI）必須把設定的 archive_enabled 傳給 RetentionWorker.run_once，
    否則客戶啟用 archive 後，這個入口會用預設的 False 靜默刪除未 archive 的列。"""
    from unittest.mock import patch
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        with open(path, "w") as f:
            json.dump({
                "web_gui": {
                    "username": "admin",
                    "password": "pw",
                    "secret_key": "s",
                    "allowed_ips": ["127.0.0.1"],
                },
                "pce_cache": {
                    "enabled": False,
                    "db_path": str(tmp_path / "cache.sqlite"),
                    "archive_enabled": True,
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
            with patch("src.pce_cache.retention.RetentionWorker") as MockWorker:
                MockWorker.return_value.run_once.return_value = {}
                resp = c.post("/api/cache/retention/run",
                              environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
            assert resp.status_code == 200
            _, kwargs = MockWorker.return_value.run_once.call_args
            assert kwargs.get("archive_enabled") is True
    finally:
        os.unlink(path)


def test_cache_lag_empty(client):
    resp = client.get("/api/cache/lag",
                      environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert isinstance(body.get("sources"), list)
    assert body["sources"] == []  # no watermarks synced yet


def test_cache_lag_reports_level(client, tmp_path):
    from datetime import datetime, timezone
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src.pce_cache.schema import init_schema
    from src.pce_cache.models import IngestionWatermark

    engine = create_engine(f"sqlite:///{tmp_path / 'cache.sqlite'}")
    init_schema(engine)
    with sessionmaker(engine)() as s:
        s.add(IngestionWatermark(source="events",
                                 last_sync_at=datetime.now(timezone.utc)))
        s.commit()

    resp = client.get("/api/cache/lag",
                      environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 200
    sources = resp.get_json()["sources"]
    assert len(sources) == 1
    row = sources[0]
    assert row["source"] == "events"
    assert row["level"] == "ok"            # just synced → within threshold
    assert row["lag_seconds"] < 60
    assert row["last_sync_at"]             # iso timestamp present
    assert "last_status" in row and "last_error" in row   # surfaced for the UI


def test_cache_lag_surfaces_error(client, tmp_path):
    # A failed ingest bumps last_sync_at (small lag) but sets last_status='error'.
    # The route must surface status + reason so the UI can flag it despite low lag.
    from datetime import datetime, timezone
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src.pce_cache.schema import init_schema
    from src.pce_cache.models import IngestionWatermark

    engine = create_engine(f"sqlite:///{tmp_path / 'cache.sqlite'}")
    init_schema(engine)
    with sessionmaker(engine)() as s:
        s.add(IngestionWatermark(source="traffic",
                                 last_sync_at=datetime.now(timezone.utc),
                                 last_status="error",
                                 last_error="boom: 503 from PCE"))
        s.commit()

    resp = client.get("/api/cache/lag",
                      environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 200
    row = resp.get_json()["sources"][0]
    assert row["source"] == "traffic"
    assert row["last_status"] == "error"
    assert "boom" in (row["last_error"] or "")


def test_cache_lag_requires_login(tmp_path):
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        with open(path, "w") as f:
            json.dump({
                "web_gui": {"username": "admin", "password": "pw",
                            "secret_key": "s", "allowed_ips": ["127.0.0.1"]},
                "pce_cache": {"enabled": False,
                              "db_path": str(tmp_path / "cache.sqlite")},
            }, f)
        cm = ConfigManager(config_file=path)
        from src.gui import _create_app
        app = _create_app(cm, persistent_mode=True)
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        with app.test_client() as c:
            resp = c.get("/api/cache/lag",
                         environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
            assert resp.status_code in (302, 401)
    finally:
        os.unlink(path)
