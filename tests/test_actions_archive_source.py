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
    # 第二筆：同一天、同 proto，但 port 與 policy_decision 都跟第一筆不同
    # ——port 8443 避免影響既有 port=443 斷言，proto=6 給 policy_decision
    # 過濾測試一個兩筆都會命中的窄化條件，好驗證 rule["pd"] 真的有把
    # allowed 那筆濾掉。
    rec2 = orjson.dumps({
        "event_time": "2026-06-20T12:05:00+00:00",
        "ingested_at": "2026-06-20T12:05:00+00:00",
        "flow_hash": "src2", "src_ip": "10.0.0.5", "src_workload": "/w/c",
        "dst_ip": "10.0.0.4", "dst_workload": "/w/d",
        "port": 8443, "protocol": "tcp", "action": "allowed", "flow_count": 1,
        "bytes_in": 1, "bytes_out": 1,
        "raw": {
            "src": {"ip": "10.0.0.5"}, "dst": {"ip": "10.0.0.4"},
            "dst_port": 8443, "proto": 6, "policy_decision": "allowed",
        },
    })
    with open(arch / "traffic-2026-06-20.jsonl", "wb") as fh:
        fh.write(rec + b"\n")
        fh.write(rec2 + b"\n")
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


def test_quarantine_search_archive_reports_skipped_rows_and_stop_reason(client, tmp_path):
    """終審 F3：略過的列數要到得了端點回應，不能只留在伺服器 log 裡。
    這裡在既有 fixture 的封存檔多加一行壞掉的 JSON，斷言 body["skipped"]
    真的反映出來；掃描本身完整跑完（沒有逾時或撞到大小上限），
    stop_reason 應為 None（終審 F5）。"""
    c, cm = client
    arch_dir = cm.models.pce_cache.archive_dir
    with open(os.path.join(arch_dir, "traffic-2026-06-20.jsonl"), "a") as fh:
        fh.write("not json at all\n")
    resp = c.post("/api/quarantine/search",
                  json={"source": "archive", "port": 443,
                        "archive_start": "2026-06-20", "archive_end": "2026-06-20"},
                  environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["skipped"] == 1
    assert body["files_incomplete"] == 0
    assert body["stop_reason"] is None


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


@pytest.fixture
def client_with_duplicate_exports(tmp_path):
    """同一個 flow_hash 的兩次匯出：較新那次快照的 bytes/連線數刻意比較
    舊那次低——長壽 flow 若真的先長大再萎縮，或只是重拉時碰上取樣抖動，
    merge_row() 的 MAX 語意都要留住較大值；若渲染時偷懶去 `raw`（單一、
    最新那次快照）自己的欄位重算，會算出這裡刻意做小的新值而不是合併後
    的正確值——這是終審 F1/F6 那個接縫的判別測試。"""
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    arch = tmp_path / "arch"
    arch.mkdir()
    older = orjson.dumps({
        "event_time": "2026-06-20T10:00:00+00:00",
        "ingested_at": "2026-06-20T10:00:00+00:00",
        "first_detected": "2026-06-20T09:00:00+00:00",
        "flow_hash": "dup1", "src_ip": "10.0.0.20", "src_workload": None,
        "dst_ip": "10.0.0.21", "dst_workload": None,
        "port": 443, "protocol": "tcp", "action": "allowed",
        "flow_count": 50, "bytes_in": 9000, "bytes_out": 9000,
        "raw": {
            "src": {"ip": "10.0.0.20"}, "dst": {"ip": "10.0.0.21"},
            "service": {"port": 443, "proto": 6},
            "dst_port": 443, "proto": 6, "policy_decision": "allowed",
            "num_connections": 50,
            "timestamp_range": {"first_detected": "2026-06-20T09:00:00+00:00",
                                 "last_detected": "2026-06-20T10:00:00+00:00"},
        },
    })
    newer = orjson.dumps({
        "event_time": "2026-06-20T14:00:00+00:00",
        "ingested_at": "2026-06-20T14:00:00+00:00",
        "first_detected": "2026-06-20T09:00:00+00:00",
        "flow_hash": "dup1", "src_ip": "10.0.0.20", "src_workload": None,
        "dst_ip": "10.0.0.21", "dst_workload": None,
        "port": 443, "protocol": "tcp", "action": "blocked",
        "flow_count": 3, "bytes_in": 100, "bytes_out": 100,
        "raw": {
            "src": {"ip": "10.0.0.20"}, "dst": {"ip": "10.0.0.21"},
            "service": {"port": 443, "proto": 6},
            "dst_port": 443, "proto": 6, "policy_decision": "blocked",
            "num_connections": 3,
            "timestamp_range": {"first_detected": "2026-06-20T09:00:00+00:00",
                                 "last_detected": "2026-06-20T14:00:00+00:00"},
        },
    })
    with open(arch / "traffic-2026-06-20.jsonl", "wb") as fh:
        fh.write(older + b"\n")
        fh.write(newer + b"\n")
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


def test_archive_row_is_shaped_like_a_live_row_and_metrics_come_from_the_merge_not_raw(
        client_with_duplicate_exports):
    """終審 F1：端點必須把封存列投影成前端讀的 live 形狀（item.source/
    destination/service/formatted_volume/num_connections/policy_decision），
    不能原樣回傳攤平的封存欄位——否則整張表格每一格都是空白（這條測試
    對照修復前的程式碼必須是紅的）。

    同時是終審 F6/F1 那個接縫的判別測試：指標必須來自 merge_row() 合併後
    的頂層計數器（MAX across 重複快照），不能從 `raw`（單一、最新那次
    快照）自己的欄位重算——fixture 讓「較新」那筆 bytes/flow_count 刻意
    比「較舊」那筆低，用 raw 重算會得到錯的小值。"""
    c, _cm = client_with_duplicate_exports
    resp = c.post("/api/quarantine/search",
                  json={"source": "archive", "port": 443,
                        "archive_start": "2026-06-20", "archive_end": "2026-06-20"},
                  environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert len(body["rows"]) == 1
    row = body["rows"][0]

    # shaped like a live row: identity/service objects, not flat archive fields
    assert row["source"]["ip"] == "10.0.0.20"
    assert row["destination"]["ip"] == "10.0.0.21"
    assert row["service"]["port"] == 443
    assert row["service"]["proto"] == "TCP"
    assert row["timestamp_range"]["last_detected"] == "2026-06-20T14:00:00+00:00"

    # metrics come from the merge (MAX), not from raw's own (newer, smaller) snapshot
    assert row["num_connections"] == 50
    assert row["total_connections"] == 50
    assert row["total_volume_mb"] == pytest.approx((9000 + 9000) / 1024 / 1024)

    # policy decision reads the newest raw snapshot (F6): the fresher one is "blocked"
    assert row["policy_decision"] == "blocked"


@pytest.fixture
def client_with_zero_byte_row(tmp_path):
    """終審 Finding 2 的原始重現場景（appendix C.3(2)）：封存查詢對沒有
    byte counter 的 flow 印出 '0.00 MB (Total)'，把『沒量』講成『量到零』。"""
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    arch = tmp_path / "arch"
    arch.mkdir()
    rec = orjson.dumps({
        "event_time": "2026-06-20T12:00:00+00:00",
        "ingested_at": "2026-06-20T12:00:00+00:00",
        "flow_hash": "src1", "src_ip": "10.0.0.9", "src_workload": "/w/a",
        "dst_ip": "10.0.0.8", "dst_workload": "/w/b",
        "port": 443, "protocol": "tcp", "action": "blocked", "flow_count": 1,
        "bytes_in": 0, "bytes_out": 0,
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


def test_archive_row_with_no_bytes_omits_volume_instead_of_reporting_zero(
        client_with_zero_byte_row):
    """終審 Finding 2：merge_row() 合併後的 bytes_in+bytes_out 為 0 時，
    actions.py 的 archive 分支必須跟 calculate_volume_mb 同一套規則——不寫
    total_volume_mb／formatted_volume，而不是把 0 傳給 _shape_traffic_row
    印成 '0.00 MB (Total)'。"""
    c, _cm = client_with_zero_byte_row
    resp = c.post("/api/quarantine/search",
                  json={"source": "archive", "port": 443,
                        "archive_start": "2026-06-20", "archive_end": "2026-06-20"},
                  environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert len(body["rows"]) == 1
    row = body["rows"][0]
    assert "total_volume_mb" not in row
    assert "formatted_volume" not in row


def test_archive_source_rejects_port_range_filters(client):
    """Final review F4: port_range/ex_port_range are PCE-native (execution
    "native" in _TRAFFIC_FILTER_CAPABILITIES) — the archive has no PCE to
    fall back to and neither client-side matcher evaluates them. Both are
    also in _NARROWING_FILTER_KEYS, so without this rejection the request
    would pass the "needs a narrowing filter" guard and silently return the
    whole unfiltered range."""
    c, _cm = client
    resp = c.post("/api/quarantine/search",
                  json={"source": "archive", "port_range": "8000-9000",
                        "archive_start": "2026-06-20", "archive_end": "2026-06-20"},
                  environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["ok"] is False
    assert "port_range" in body["unsupported"]


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
    第二套比對器，所以評估不了 search，比照 unsupported filter 明講拒絕
    （而不是靜默忽略掉 search 條件、回一個看似有過濾但其實沒有的結果）。"""
    c, _cm = client
    resp = c.post("/api/quarantine/search",
                  json={"source": "archive", "search": "10.0.0.9",
                        "archive_start": "2026-06-20", "archive_end": "2026-06-20"},
                  environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["ok"] is False
    assert "search" in body["unsupported"]


def test_archive_source_rejects_search_combined_with_another_filter(client):
    """search 跟一個真的能評估的條件（port）一起送——這裡曾經是個洞：
    只有 search-only 被擋，search 搭別的條件時會悄悄回 port 過濾過、
    但 search 被忽略的結果（ok:true），操作者以為文字有搜到，其實根本
    沒搜。任何非空 search 都要拒絕，不只 search-only。"""
    c, _cm = client
    resp = c.post("/api/quarantine/search",
                  json={"source": "archive", "port": 443, "search": "foo",
                        "archive_start": "2026-06-20", "archive_end": "2026-06-20"},
                  environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["ok"] is False
    assert "search" in body["unsupported"]


def test_archive_source_filters_by_policy_decision(client):
    """rule["pd"] 曾經照抄 query_flows 固定成 -1（等於不過濾）——那份
    照抄少了 query_flows 自己在送 API 查詢前先按 pds 縮小範圍那個階段，
    archive 沒有這個階段，於是 policy_decision 被靜默丟在地上。兩筆
    fixture 資料同 proto，一筆 blocked 一筆 allowed；只挑 blocked 時
    allowed 那筆不該出現。"""
    c, _cm = client
    resp = c.post("/api/quarantine/search",
                  json={"source": "archive", "proto": 6, "policy_decision": "blocked",
                        "archive_start": "2026-06-20", "archive_end": "2026-06-20"},
                  environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert len(body["rows"]) == 1
    text = resp.get_data(as_text=True)
    assert "10.0.0.9" in text
    assert "10.0.0.5" not in text


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
