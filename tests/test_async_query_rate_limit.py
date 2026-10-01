"""Rule usage 會一次送出數百個 async query；PCE 每個 API key 每分鐘上限 500 次，
超過回 429。送出／輪詢／下載都要走全域限速器，限速器逾時則記為失敗，
不得讓例外中斷整批。"""
from __future__ import annotations

from unittest.mock import MagicMock


def _mgr(request_side_effect):
    from src.api.async_jobs import AsyncJobManager
    client = MagicMock()
    client.base_url = "https://pce.test/api/v2/orgs/1"
    client.api_cfg = {"url": "https://pce.test"}
    client._request.side_effect = request_side_effect
    mgr = AsyncJobManager.__new__(AsyncJobManager)
    mgr._client = client
    mgr._save_async_job_state = MagicMock()
    mgr._make_query_signature = MagicMock(return_value="sig")
    return mgr, client


def test_submit_goes_through_rate_limiter():
    mgr, client = _mgr(lambda *a, **kw: (202, b'{"href": "/orgs/1/traffic_flows/async_queries/x"}'))
    assert mgr.submit_async_query({"query_name": "q"}) == "/orgs/1/traffic_flows/async_queries/x"
    assert client._request.call_args.kwargs.get("rate_limit") is True


def test_submit_returns_none_when_rate_limiter_times_out():
    from src.exceptions import APIError

    def _raise(*a, **kw):
        raise APIError("Global rate limiter timeout")
    mgr, _ = _mgr(_raise)
    assert mgr.submit_async_query({"query_name": "q"}) is None
