"""source=archive 時，流量查詢改直接串流封存日檔（不再經 review DB／即時 PCE API）。"""
import json
import os
import tempfile

import orjson
import pytest

from src.config import ConfigManager


@pytest.fixture
def client(tmp_path):
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    arch = tmp_path / "arch"
    arch.mkdir()
    # 種一筆 archive traffic（事件日 2026-06-20）。raw 是原始 PCE flow dict，
    # 形狀須跟 Analyzer._match_flow_filters／check_flow_match 期待的一致
    # （src/dst 是巢狀物件、port 走 dst_port 或 service.port）——archive
    # 分支的比對器直接吃 raw，不是 review DB 那種攤平欄位。
    rec = orjson.dumps({
        "event_time": "2026-06-20T12:00:00+00:00",
        "ingested_at": "2026-06-20T12:00:00+00:00",
        "flow_hash": "src1", "src_ip": "10.0.0.9", "src_workload": "/w/a",
        "dst_ip": "10.0.0.8", "dst_workload": "/w/b",
        "port": 443, "protocol": "tcp", "action": "blocked", "flow_count": 1,
        "bytes_in": 1, "bytes_out": 1,
        "raw": {
            "src": {"ip": "10.0.0.9"}, "dst": {"ip": "10.0.0.8"},
            "dst_port": 443, "proto": 6, "policy_decision": "blocked",
        },
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


def test_quarantine_search_archive_source_streams_matching_rows(client):
    """Task 4：archive 分支不再讀 review DB，改直接串流封存日檔，用與 live
    相同的 Analyzer._match_flow_filters 比對 raw（見 actions.py 的
    query_filters/rule 建法，照抄 query_flows :2328 附近那段）。"""
    c, _cm = client
    resp = c.post("/api/quarantine/search",
                  json={"source": "archive", "port": 443,
                        "archive_start": "2026-06-20", "archive_end": "2026-06-20"},
                  environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["actual_source"] == "archive"
    assert len(body["rows"]) == 1
    assert "10.0.0.9" in resp.get_data(as_text=True)


def test_quarantine_search_archive_empty_outside_range(client):
    """沒有 review DB 這個概念了：查一個封存裡沒有日檔的日期區間就是回空
    （ok=True, rows=[]），不是特別的 not_loaded 狀態。"""
    c, _cm = client
    resp = c.post("/api/quarantine/search",
                  json={"source": "archive", "port": 443,
                        "archive_start": "2020-01-01", "archive_end": "2020-01-01"},
                  environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["rows"] == []


def test_archive_source_rejects_filters_it_cannot_evaluate(client):
    c, _cm = client
    resp = c.post("/api/quarantine/search",
                  json={"source": "archive", "src_label_groups": ["g1"],
                        "archive_start": "2026-05-01", "archive_end": "2026-05-01"},
                  environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["ok"] is False
    assert "src_label_groups" in body["unsupported"]


def test_archive_source_requires_a_date_range(client):
    c, _cm = client
    resp = c.post("/api/quarantine/search", json={"source": "archive", "port": 443},
                  environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 400


def test_archive_source_rejects_a_reversed_date_range(client):
    """archive_end < archive_start：day-file 迴圈（stream_query 的
    `while day <= end`）一次都不會跑，會靜默回 200 空結果——跟審查 F1
    （2026-07-24，live mins 反轉那個窗）同一類缺陷，這裡在解析後就擋掉。"""
    c, _cm = client
    resp = c.post("/api/quarantine/search",
                  json={"source": "archive", "port": 443,
                        "archive_start": "2026-06-30", "archive_end": "2026-06-01"},
                  environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 400


def test_archive_source_search_only_is_not_a_narrowing_filter(client):
    """search 的全文比對只存在於 query_flows 事後那道手動子字串掃描，不在
    _match_flow_filters 裡——archive 只共用 _match_flow_filters，不另建
    第二套比對器，所以評估不了 search。若讓它單獨滿足「有縮小範圍」的
    守門，一個只給 search 的查詢會通過守門卻拿到完全未過濾的結果，比
    直接拒絕還危險，所以這裡連同其他條件一起判定為「沒給窄化條件」。"""
    c, _cm = client
    resp = c.post("/api/quarantine/search",
                  json={"source": "archive", "search": "10.0.0.9",
                        "archive_start": "2026-06-20", "archive_end": "2026-06-20"},
                  environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 400


def test_archive_source_translates_bandwidth_sort_to_volume(client):
    """封存列沒有算速率（bandwidth）需要的 ddms/tdms 欄位；UI 預設送
    sort_by=bandwidth，這裡要轉成 volume 查詢，並在回應裡老實說用了什麼
    排序，而不是靜默换成別的意思。"""
    c, _cm = client
    resp = c.post("/api/quarantine/search",
                  json={"source": "archive", "port": 443,
                        "archive_start": "2026-06-20", "archive_end": "2026-06-20"},
                  environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["sort_by"] == "volume"
    assert body["sort_by_substituted"] is True
    assert len(body["rows"]) == 1


def test_archive_source_keeps_explicit_connections_sort(client):
    c, _cm = client
    resp = c.post("/api/quarantine/search",
                  json={"source": "archive", "port": 443, "sort_by": "connections",
                        "archive_start": "2026-06-20", "archive_end": "2026-06-20"},
                  environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["sort_by"] == "connections"
    assert body["sort_by_substituted"] is False


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
