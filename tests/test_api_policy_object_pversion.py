"""pversion 參數化：物件 getter 可切換 draft/active 端點。

Task 1 (API layer hardening)：這些 getter 改走 _get_collection（固定 500
上限 + 截斷偵測），故 mock 對象改為 _get_collection；max_results 斷言改由
_get_collection 自己的測試（tests/test_api_collection_truncation.py）覆蓋。
"""

import pytest
from unittest.mock import MagicMock

from src.api_client import ApiClient


@pytest.fixture
def api():
    client = ApiClient.__new__(ApiClient)
    client.api_cfg = {"url": "https://pce.example.com:8443", "org_id": 1}
    client._get_collection = MagicMock(return_value=(200, [{"href": "/orgs/1/sec_policy/draft/ip_lists/5", "name": "L"}], None))
    return client


@pytest.mark.parametrize("method,segment", [
    ("get_ip_lists", "ip_lists"),
    ("get_services", "services"),
    ("get_label_groups", "label_groups"),
])
def test_default_pversion_hits_active(api, method, segment):
    getattr(api, method)()
    endpoint = api._get_collection.call_args[0][0]
    assert f"/sec_policy/active/{segment}" in endpoint


@pytest.mark.parametrize("method,segment", [
    ("get_ip_lists", "ip_lists"),
    ("get_services", "services"),
    ("get_label_groups", "label_groups"),
])
def test_draft_pversion_hits_draft(api, method, segment):
    result = getattr(api, method)(pversion="draft")
    endpoint = api._get_collection.call_args[0][0]
    assert f"/sec_policy/draft/{segment}" in endpoint
    assert isinstance(result, list)


@pytest.mark.parametrize("method", ["get_ip_lists", "get_services", "get_label_groups"])
def test_invalid_pversion_raises(api, method):
    with pytest.raises(ValueError):
        getattr(api, method)(pversion="prod")
