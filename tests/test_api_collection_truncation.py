"""集合 GET header 感知 + 截斷偵測（API layer hardening Task 1）。

PCE 對同步集合 GET 硬上限 500 且回 X-Total-Count（vendor 已驗證）。既有 getter
帶 max_results=10000 無效、且會掩蓋截斷。這裡驗證 `_get_collection` 讀
X-Total-Count、偵測截斷，以及 7 個 getter 全部改走 `_get_collection`（修類不修點）。
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import responses

from src.api_client import ApiClient


@pytest.fixture
def api_client():
    cm = MagicMock()
    cm.config = {
        "api": {
            "url": "https://pce.example.com:8443",
            "org_id": "1",
            "key": "test-key",
            "secret": "test-secret",
            "verify_ssl": False,
        },
    }
    return ApiClient(cm)


@responses.activate
def test_get_collection_reads_total_count(api_client):
    body = [{"href": f"/orgs/1/labels/{i}"} for i in range(3)]
    responses.add(
        responses.GET,
        "https://pce.example.com:8443/api/v2/orgs/1/labels",
        json=body,
        status=200,
        headers={"X-Total-Count": "3"},
    )
    status, data, total = api_client._get_collection("/orgs/1/labels")
    assert status == 200
    assert data == body
    assert total == 3
    assert api_client.last_truncated_collections == []
    # max_results 一律用 PCE 硬上限 500（不是無效的 10000）
    assert "max_results=500" in responses.calls[0].request.url


@responses.activate
def test_get_collection_detects_truncation(api_client):
    body = [{"href": f"/orgs/1/workloads/{i}"} for i in range(500)]
    responses.add(
        responses.GET,
        "https://pce.example.com:8443/api/v2/orgs/1/workloads",
        json=body,
        status=200,
        headers={"X-Total-Count": "700"},
    )
    status, data, total = api_client._get_collection("/orgs/1/workloads")
    assert status == 200
    assert total == 700
    assert len(data) == 500
    assert api_client.last_truncated_collections == ["/orgs/1/workloads"]


@responses.activate
def test_get_collection_no_header(api_client):
    body = [{"href": "/orgs/1/labels/1"}]
    responses.add(
        responses.GET,
        "https://pce.example.com:8443/api/v2/orgs/1/labels",
        json=body,
        status=200,
        # 故意不帶 X-Total-Count
    )
    status, data, total = api_client._get_collection("/orgs/1/labels")
    assert status == 200
    assert data == body
    assert total is None
    assert api_client.last_truncated_collections == []  # 不誤報截斷


@pytest.mark.parametrize("method,args", [
    ("get_ip_lists", ()),
    ("get_services", ()),
    ("get_label_groups", ()),
    ("get_active_rulesets", ()),
    ("get_all_labels", ()),
    ("fetch_managed_workloads", ()),
])
def test_getters_route_through_get_collection(api_client, method, args):
    """修類不修點的守門：brief 指名的 getter 全部要走 _get_collection。"""
    api_client._get_collection = MagicMock(return_value=(200, [], None))
    getattr(api_client, method)(*args)
    api_client._get_collection.assert_called_once()


def test_get_all_rulesets_routes_through_get_collection(api_client):
    api_client._get_collection = MagicMock(return_value=(200, [{"href": "/rs/1"}], None))
    out = api_client.get_all_rulesets()
    api_client._get_collection.assert_called_once()
    assert out == [{"href": "/rs/1"}]


@responses.activate
def test_get_with_headers_non_json_200_returns_error_tuple(api_client):
    """200 但 body 非 JSON：_api_get_with_headers 須回 (0, None, {})，
    不可讓 JSONDecodeError 炸穿到 getter 呼叫端（打破「Returns [] on error」契約）。"""
    responses.add(
        responses.GET,
        "https://pce.example.com:8443/api/v2/orgs/1/sec_policy/active/services",
        body=b"<html>oops",
        status=200,
    )
    status, data, headers = api_client._api_get_with_headers(
        "/orgs/1/sec_policy/active/services"
    )
    assert (status, data, headers) == (0, None, {})
    # 經由 getter 呼叫也不應拋例外，且維持「錯誤回 []」的契約
    assert api_client.get_services() == []


@responses.activate
def test_no_truncation_flag_on_error_status(api_client):
    """非 200（如 503）即使意外帶 X-Total-Count 也不可誤判為截斷。"""
    responses.add(
        responses.GET,
        "https://pce.example.com:8443/api/v2/orgs/1/labels",
        json={"error": "unavailable"},
        status=503,
        headers={"X-Total-Count": "700"},
    )
    status, data, total = api_client._get_collection("/orgs/1/labels")
    assert status == 503
    assert api_client.last_truncated_collections == []


# ═══════════════════════════════════════════════════════════════════════════
# Task 2: 截斷時 async GET fallback（官方 async GET 流程：
# Prefer: respond-async → 202+Location+Retry-After → 輪詢 job 直到 done
# → 從 result.href 下載完整 datafile）
# ═══════════════════════════════════════════════════════════════════════════

def test_async_fallback_returns_full_collection(api_client, monkeypatch):
    """截斷觸發 fallback，最終回完整 700 筆，且不留截斷紀錄。"""
    monkeypatch.setattr("src.api_client.time.sleep", lambda *_a, **_kw: None)
    truncated = [{"href": f"/orgs/1/workloads/{i}"} for i in range(500)]
    full = [{"href": f"/orgs/1/workloads/{i}"} for i in range(700)]
    api_client._api_get_with_headers = MagicMock(side_effect=[
        (200, truncated, {"X-Total-Count": "700"}),  # 原本的截斷集合 GET
        (202, None, {"Location": "/orgs/1/jobs/abc123", "Retry-After": "1"}),  # async GET 觸發
        (200, {"status": "running"}, {}),  # 輪詢中
        (200, {"status": "done", "result": {"href": "/orgs/1/workloads_datafile_xyz"}}, {}),  # 完成
        (200, full, {}),  # 下載 datafile
    ])
    status, data, total = api_client._get_collection("/orgs/1/workloads")
    assert status == 200
    assert data == full
    assert total == 700
    assert api_client.last_truncated_collections == []
    assert api_client._api_get_with_headers.call_count == 5
    # 輪詢呼叫要打 Location 抽出的 job href，下載呼叫要打 result.href
    calls = api_client._api_get_with_headers.call_args_list
    assert calls[2].args[0] == "/orgs/1/jobs/abc123"  # 輪詢中
    assert calls[3].args[0] == "/orgs/1/jobs/abc123"  # 輪詢到 done
    assert calls[4].args[0] == "/orgs/1/workloads_datafile_xyz"  # 下載 datafile


def test_async_fallback_cancelled_treated_as_terminal(api_client, monkeypatch):
    """輪詢回 cancelled → 視為失敗終態立即結束（不空轉到 300s deadline），
    回截斷資料（與 failed 同型，修類不修點）。"""
    monkeypatch.setattr("src.api_client.time.sleep", lambda *_a, **_kw: None)
    truncated = [{"href": f"/orgs/1/workloads/{i}"} for i in range(500)]
    api_client._api_get_with_headers = MagicMock(side_effect=[
        (200, truncated, {"X-Total-Count": "700"}),
        (202, None, {"Location": "/orgs/1/jobs/abc123", "Retry-After": "1"}),
        (200, {"status": "cancelled"}, {}),
    ])
    status, data, total = api_client._get_collection("/orgs/1/workloads")
    assert status == 200
    assert data == truncated
    # cancelled 後不得再輪詢：總共恰 3 次呼叫（初始 GET、202 提交、單次輪詢）
    assert api_client._api_get_with_headers.call_count == 3
    assert api_client.last_truncated_collections == ["/orgs/1/workloads"]


def test_async_fallback_failure_keeps_truncated_data(api_client, monkeypatch):
    """輪詢回 failed → 回 500 筆截斷資料、error log 仍在（last_truncated_collections 有記錄）。"""
    monkeypatch.setattr("src.api_client.time.sleep", lambda *_a, **_kw: None)
    truncated = [{"href": f"/orgs/1/workloads/{i}"} for i in range(500)]
    api_client._api_get_with_headers = MagicMock(side_effect=[
        (200, truncated, {"X-Total-Count": "700"}),
        (202, None, {"Location": "/orgs/1/jobs/abc123", "Retry-After": "1"}),
        (200, {"status": "failed"}, {}),
    ])
    status, data, total = api_client._get_collection("/orgs/1/workloads")
    assert status == 200
    assert data == truncated
    assert len(data) == 500
    assert total == 700
    assert api_client.last_truncated_collections == ["/orgs/1/workloads"]
    # 輪詢呼叫要打 Location 抽出的 job href
    calls = api_client._api_get_with_headers.call_args_list
    assert calls[2].args[0] == "/orgs/1/jobs/abc123"


def test_truncation_record_cleared_after_successful_fallback(api_client, monkeypatch):
    """跨呼叫「先失敗後成功」：第一次 fallback 失敗留下截斷紀錄，
    第二次 fallback 成功恢復完整資料時，該紀錄必須被清除，否則永久殘留假陽性。"""
    monkeypatch.setattr("src.api_client.time.sleep", lambda *_a, **_kw: None)
    truncated = [{"href": f"/orgs/1/workloads/{i}"} for i in range(500)]
    full = [{"href": f"/orgs/1/workloads/{i}"} for i in range(700)]

    # 第一次呼叫：fallback 失敗，記錄存在
    api_client._api_get_with_headers = MagicMock(side_effect=[
        (200, truncated, {"X-Total-Count": "700"}),
        (202, None, {"Location": "/orgs/1/jobs/abc123", "Retry-After": "1"}),
        (200, {"status": "failed"}, {}),
    ])
    api_client._get_collection("/orgs/1/workloads")
    assert api_client.last_truncated_collections == ["/orgs/1/workloads"]

    # 第二次呼叫：fallback 成功，記錄必須被清除
    api_client._api_get_with_headers = MagicMock(side_effect=[
        (200, truncated, {"X-Total-Count": "700"}),
        (202, None, {"Location": "/orgs/1/jobs/abc123", "Retry-After": "1"}),
        (200, {"status": "done", "result": {"href": "/orgs/1/workloads_datafile_xyz"}}, {}),
        (200, full, {}),
    ])
    status, data, total = api_client._get_collection("/orgs/1/workloads")
    assert status == 200
    assert data == full
    assert total == 700
    assert api_client.last_truncated_collections == []


@responses.activate
def test_no_truncation_below_cap_on_filtered_query(api_client):
    """帶 query filter 的集合 GET，X-Total-Count 回的是未過濾總數（PCE 25.2.40
    真機實測：workloads?managed=true 回 20 列、header 30）。actual < 500 上限
    且 total > actual 是 filter 語意差異、不是截斷——不得觸發 async fallback、
    不得留截斷紀錄（否則每次呼叫多打一個 PCE async job、多等 2s、永久假陽性）。"""
    body = [{"href": f"/orgs/1/workloads/{i}"} for i in range(20)]
    responses.add(
        responses.GET,
        "https://pce.example.com:8443/api/v2/orgs/1/workloads",
        json=body,
        status=200,
        headers={"X-Total-Count": "30"},
    )
    status, data, total = api_client._get_collection("/orgs/1/workloads?managed=true")
    assert status == 200
    assert len(data) == 20
    assert total == 30
    assert api_client.last_truncated_collections == []
    assert len(responses.calls) == 1
    assert "Prefer" not in responses.calls[0].request.headers


@responses.activate
def test_no_fallback_when_not_truncated(api_client):
    """未截斷（X-Total-Count == 實收筆數）不應發 Prefer: respond-async 請求。"""
    body = [{"href": "/orgs/1/labels/1"}]
    responses.add(
        responses.GET,
        "https://pce.example.com:8443/api/v2/orgs/1/labels",
        json=body,
        status=200,
        headers={"X-Total-Count": "1"},
    )
    status, data, total = api_client._get_collection("/orgs/1/labels")
    assert status == 200
    assert total == 1
    assert api_client.last_truncated_collections == []
    # 只有一次真實 HTTP 呼叫（原本的集合 GET），沒有額外的 async GET 觸發請求
    assert len(responses.calls) == 1
    assert "Prefer" not in responses.calls[0].request.headers
