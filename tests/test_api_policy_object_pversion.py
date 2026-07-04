"""pversion 參數化：物件 getter 可切換 draft/active 端點。"""

import pytest
from unittest.mock import MagicMock

from src.api_client import ApiClient


@pytest.fixture
def api():
    client = ApiClient.__new__(ApiClient)
    client.api_cfg = {"url": "https://pce.example.com:8443", "org_id": 1}
    client._api_get = MagicMock(return_value=(200, [{"href": "/orgs/1/sec_policy/draft/ip_lists/5", "name": "L"}]))
    return client


@pytest.mark.parametrize("method,segment", [
    ("get_ip_lists", "ip_lists"),
    ("get_services", "services"),
    ("get_label_groups", "label_groups"),
])
def test_default_pversion_hits_active(api, method, segment):
    getattr(api, method)()
    endpoint = api._api_get.call_args[0][0]
    assert f"/sec_policy/active/{segment}" in endpoint
    assert "max_results=10000" in endpoint


@pytest.mark.parametrize("method,segment", [
    ("get_ip_lists", "ip_lists"),
    ("get_services", "services"),
    ("get_label_groups", "label_groups"),
])
def test_draft_pversion_hits_draft(api, method, segment):
    result = getattr(api, method)(pversion="draft")
    endpoint = api._api_get.call_args[0][0]
    assert f"/sec_policy/draft/{segment}" in endpoint
    assert isinstance(result, list)


@pytest.mark.parametrize("method", ["get_ip_lists", "get_services", "get_label_groups"])
def test_invalid_pversion_raises(api, method):
    with pytest.raises(ValueError):
        getattr(api, method)(pversion="prod")
