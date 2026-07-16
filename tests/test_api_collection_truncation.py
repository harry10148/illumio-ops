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
