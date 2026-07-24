"""source=archive 時，流量查詢與趨勢圖應改讀 archive review DB（不打即時 PCE API）。"""
import json
import os
import tempfile
from datetime import date

import orjson
import pytest

from src.config import ConfigManager


@pytest.fixture
def client(tmp_path):
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    arch = tmp_path / "arch"
    arch.mkdir()
    # 種一筆 archive traffic（事件日 2026-06-20），raw 為原始 flow dict。
    rec = orjson.dumps({
        "event_time": "2026-06-20T12:00:00+00:00",
        "ingested_at": "2026-06-20T12:00:00+00:00",
        "flow_hash": "src1", "src_ip": "10.0.0.9", "src_workload": "/w/a",
        "dst_ip": "10.0.0.8", "dst_workload": "/w/b",
        "port": 443, "protocol": "tcp", "action": "blocked", "flow_count": 1,
        "bytes_in": 1, "bytes_out": 1,
        "raw": {"src_ip": "10.0.0.9", "dst_ip": "10.0.0.8", "port": 443,
                "action": "blocked", "policy_decision": "blocked"},
    })
    with open(arch / "traffic-2026-06-20.jsonl", "wb") as fh:
        fh.write(rec + b"\n")
    with open(path, "w") as f:
        json.dump({
            "web_gui": {"username": "admin", "password": "pw", "secret_key": "s",
                        "allowed_ips": ["127.0.0.1"]},
            "pce_cache": {"enabled": True, "db_path": str(tmp_path / "cache.sqlite"),
                          "archive_dir": str(arch)},
        }, f)
    cm = ConfigManager(config_file=path)
    from src.gui import _create_app
    app = _create_app(cm, persistent_mode=True)
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        c.post("/api/login", json={"username": "admin", "password": "pw"},
               environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
        yield c, cm
    os.unlink(path)


def test_quarantine_search_archive_source_reads_review_db(client):
    c, cm = client
    from src.pce_cache.archive_import import load_archive_review
    load_archive_review(cm.models.pce_cache, date(2026, 6, 1), date(2026, 6, 30))
    # source=archive：查詢窗自動設為 [review 最早資料, now]，只讀 review DB。
    resp = c.post("/api/quarantine/search", json={"source": "archive"},
                  environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert len(body["data"]) >= 1               # 讀到 archive 的 flow（live cache 為空）
    assert "10.0.0.9" in resp.get_data(as_text=True)


def test_quarantine_search_archive_empty_when_not_loaded(client):
    c, cm = client
    # 未載入 archive（review DB 空）→ 回空，不打 API、不報錯。
    resp = c.post("/api/quarantine/search", json={"source": "archive"},
                  environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 200
    # F3（2026-07-24 審查）：not_loaded 旗標區分「未載入 review DB」與「查無流量」
    body = resp.get_json()
    assert body["ok"] is True and body["data"] == [] and body.get("not_loaded") is True


def test_quarantine_search_mins_clamped(client):
    """F1：live 分支 mins 須夾限（同 debug/events 端點基線 5..10080）——
    攔截 query_flows 驗證送進去的查詢窗不超過 10080 分鐘。"""
    import datetime
    from unittest.mock import patch
    c, _cm = client
    captured = {}

    def _fake_query_flows(self, params):
        captured["params"] = params
        return []

    with patch("src.analyzer.Analyzer.query_flows", _fake_query_flows):
        resp = c.post("/api/quarantine/search", json={"source": "live", "mins": 99999999},
                      environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 200
    st = datetime.datetime.strptime(captured["params"]["start_time"], "%Y-%m-%dT%H:%M:%SZ")
    et = datetime.datetime.strptime(captured["params"]["end_time"], "%Y-%m-%dT%H:%M:%SZ")
    assert (et - st).total_seconds() <= 10080 * 60 + 1


def test_quarantine_search_mins_non_numeric_400(client):
    """F2：非數字 mins 回 typed 400，非 generic 500。"""
    c, _cm = client
    resp = c.post("/api/quarantine/search", json={"source": "live", "mins": "abc"},
                  environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 400
