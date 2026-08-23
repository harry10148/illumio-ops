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


# ── D2 子項 4：500 body 經 _err_with_log 回通用訊息，不外洩原始例外 ──────────

class _BoomSessionFactory:
    """__call__ 會拋例外的 session factory，用來觸發 route 內層的
    try/except（包住實際查詢的那層，而非 `_get_sf()` 本身）。"""

    def __call__(self):
        raise RuntimeError("secret-db-path-leak")


def test_cache_status_500_does_not_leak_exception_detail(client, monkeypatch):
    monkeypatch.setattr("src.pce_cache.web._get_sf", lambda: _BoomSessionFactory())
    resp = client.get("/api/cache/status",
                      environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 500
    body = resp.get_json()
    assert body["ok"] is False
    assert "request_id" in body
    assert "secret-db-path-leak" not in body["error"]


def test_cache_health_500_does_not_leak_exception_detail(client, monkeypatch):
    monkeypatch.setattr("src.pce_cache.web._get_sf", lambda: _BoomSessionFactory())
    resp = client.get("/api/cache/health",
                      environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 500
    body = resp.get_json()
    assert body["ok"] is False
    assert "request_id" in body
    assert "secret-db-path-leak" not in body["error"]


def test_cache_health_capacity_failure_isolated(client, monkeypatch):
    """capacity_snapshot 例外不可讓整個 /api/cache/health 變成錯誤回應——
    verdict/lag/siem/dlq 等既有欄位須照常回傳，capacity 降級為 None。"""
    def _boom(*args, **kwargs):
        raise RuntimeError("capacity blew up")

    monkeypatch.setattr("src.pce_cache.capacity.capacity_snapshot", _boom)
    resp = client.get("/api/cache/health",
                      environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["capacity"] is None
    assert "verdict" in body
    assert "lag_levels" in body
    assert "cache_lag" in body
    assert "siem_success_1h" in body
    assert "dlq" in body


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


def _seed_archive(tmp_path):
    import orjson
    d = tmp_path / "arch"
    d.mkdir()
    rec = orjson.dumps({
        "event_time": "2026-06-20T12:00:00+00:00",
        "ingested_at": "2026-06-20T12:00:00+00:00",
        "flow_hash": "aw1", "src_ip": "10.0.0.1", "dst_ip": "10.0.0.2",
        "port": 443, "protocol": "tcp", "action": "blocked",
        "flow_count": 1, "bytes_in": 1, "bytes_out": 1,
        "raw": {"src_ip": "10.0.0.1", "dst_ip": "10.0.0.2", "port": 443, "action": "blocked"},
    })
    with open(d / "traffic-2026-06-20.jsonl", "wb") as fh:
        fh.write(rec + b"\n")
    return str(d)


def test_archive_status_reports_file_facts(client, tmp_path):
    """封存查閱自 Task 4 起直接串流封存日檔，不再有 review DB「已載入」
    可回報——/archive/status 改回報 archive_dir 底下真的有什麼檔案。"""
    arch = _seed_archive(tmp_path)  # 種了單一天 2026-06-20
    client.put("/api/cache/settings", json={"archive_dir": arch},
               environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    resp = client.get("/api/cache/archive/status",
                      environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body == {"exists": True, "files": 1,
                     "earliest": "2026-06-20", "latest": "2026-06-20"}


def test_archive_status_missing_dir_is_not_500(client, tmp_path):
    """archive_dir 指向不存在的路徑不可讓端點 500，要老實回報「沒有這個目錄」。"""
    client.put("/api/cache/settings", json={"archive_dir": str(tmp_path / "no-such-dir")},
               environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    resp = client.get("/api/cache/archive/status",
                      environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body == {"exists": False, "files": 0, "earliest": None, "latest": None}


def test_archive_status_requires_login(tmp_path):
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
            resp = c.get("/api/cache/archive/status",
                         environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
            assert resp.status_code in (302, 401)
    finally:
        os.unlink(path)


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


def test_backfill_returns_409_when_busy(client):
    """backfill 是長跑寫入：第二個併發 POST 必須立即拿 409（non-blocking
    lock），不可並行互搶 SQLite 寫鎖、重複灌列。"""
    from src.pce_cache import web as cache_web
    assert cache_web._BACKFILL_LOCK.acquire(blocking=False)
    try:
        resp = client.post("/api/cache/backfill",
                           json={"source": "events", "since": "2026-06-01",
                                 "until": "2026-06-02"},
                           environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
        assert resp.status_code == 409
        assert resp.get_json()["error"]
    finally:
        cache_web._BACKFILL_LOCK.release()


def test_backfill_until_date_is_inclusive(client):
    """GUI 的 End date 是含端點語意（同封存查閱的 archive_end）：until=6/10 必須把
    6/10 整天納入查詢窗（上界 6/11 00:00 排他），不可靜默丟掉最後一天。"""
    from unittest.mock import patch
    from datetime import datetime, timezone

    class _R:
        total_rows = 0
        inserted = 0
        duplicates = 0
        elapsed_seconds = 0.0

    with patch("src.pce_cache.web._get_api"), \
         patch("src.pce_cache.backfill.BackfillRunner") as MockRunner:
        MockRunner.return_value.run_events.return_value = _R()
        resp = client.post("/api/cache/backfill",
                           json={"source": "events", "since": "2026-06-01",
                                 "until": "2026-06-10"},
                           environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 200
    args, _ = MockRunner.return_value.run_events.call_args
    assert args[0] == datetime(2026, 6, 1, tzinfo=timezone.utc)
    assert args[1] == datetime(2026, 6, 11, tzinfo=timezone.utc)


def test_backfill_get_sf_failure_does_not_leak_exception_detail(client, monkeypatch):
    """_get_sf 失敗（cache 未設定/DB 壞）回 503 時不可外洩原始例外文字
    （SQL/engine/路徑細節）；經 _err_with_log 回通用訊息 + request_id。"""
    def _boom():
        raise RuntimeError("secret-engine-detail-leak")

    monkeypatch.setattr("src.pce_cache.web._get_sf", _boom)
    resp = client.post("/api/cache/backfill",
                       json={"source": "events", "since": "2026-06-01"},
                       environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 503
    body = resp.get_json()
    assert "request_id" in body
    assert "secret-engine-detail-leak" not in body["error"]
