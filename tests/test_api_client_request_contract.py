"""Contract tests for ApiClient._request() — exercises the REAL method via responses.

Freezes the (status_code: int, body: bytes) return contract so the 50+ methods
that call _request() don't break if the HTTP internals change again.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import responses


@pytest.fixture
def api_client():
    from src.api_client import ApiClient
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
def test_request_returns_int_status_and_bytes_body_on_200(api_client):
    """Real _request() with 200 OK returns (200, bytes_body)."""
    url = "https://pce.example.com:8443/api/v2/test"
    responses.add(responses.GET, url, status=200, body=b'{"ok": true}')

    status, body = api_client._request(url)

    assert isinstance(status, int), f"status must be int, got {type(status)}"
    assert status == 200
    assert isinstance(body, bytes), f"body must be bytes, got {type(body)}"
    assert body == b'{"ok": true}'


@responses.activate
def test_request_returns_status_and_body_on_http_error(api_client):
    """4xx responses must return (status, error_body) not raise."""
    url = "https://pce.example.com:8443/api/v2/missing"
    responses.add(responses.GET, url, status=404, body=b'{"error":"not found"}')

    status, body = api_client._request(url)

    assert status == 404
    assert b"not found" in body


@responses.activate
def test_request_returns_zero_status_on_connection_failure(api_client):
    """When the session can't even reach the host, return (0, error_bytes)."""
    url = "https://unreachable.example.com/api/v2/test"
    # responses library raises ConnectionError for unregistered URLs if passthrough off
    responses.add(responses.GET, url, body=ConnectionError("no route to host"))

    status, body = api_client._request(url)

    assert status == 0, f"unreachable host should return 0 status; got {status}"
    assert isinstance(body, bytes)


@responses.activate
def test_request_post_with_json_body_serializes_correctly(api_client):
    """POST data=dict argument must be JSON-serialized to request body."""
    url = "https://pce.example.com:8443/api/v2/workloads"
    responses.add(responses.POST, url, status=201, body=b'{"href":"/orgs/1/w/123"}')

    status, body = api_client._request(url, method="POST", data={"name": "test"})

    assert status == 201
    assert b"href" in body
    # Verify Content-Type header was added
    assert len(responses.calls) == 1
    req = responses.calls[0].request
    assert req.headers.get("Content-Type") == "application/json"
    assert b'"name": "test"' in req.body or b'"name":"test"' in req.body


def test_verify_ssl_string_path_preserved_as_ca_bundle():
    """verify_ssl: '/path/to/ca.crt' must set Session.verify to the path string, not True."""
    from src.api_client import ApiClient
    cm = MagicMock()
    cm.config = {"api": {"url": "https://p", "org_id": "1", "key": "k", "secret": "s",
                         "verify_ssl": "/etc/ssl/custom_ca.crt"}}
    api = ApiClient(cm)
    assert api._session.verify == "/etc/ssl/custom_ca.crt"


def test_verify_ssl_false_disables_verification():
    from src.api_client import ApiClient
    cm = MagicMock()
    cm.config = {"api": {"url": "https://p", "org_id": "1", "key": "k", "secret": "s",
                         "verify_ssl": False}}
    api = ApiClient(cm)
    assert api._session.verify is False


def test_verify_ssl_true_uses_system_ca():
    from src.api_client import ApiClient
    cm = MagicMock()
    cm.config = {"api": {"url": "https://p", "org_id": "1", "key": "k", "secret": "s",
                         "verify_ssl": True}}
    api = ApiClient(cm)
    assert api._session.verify is True


# ── Task C1: rate-limit hot path + dead-parameter wiring ──────────────────


@responses.activate
def test_request_rate_limit_does_not_construct_config_manager(api_client, monkeypatch):
    """_request(rate_limit=True) must use the cached rpm from __init__, never
    rebuild a ConfigManager per request (full config.json read + pydantic
    validation on every rate-limited call)."""
    from src.pce_cache.rate_limiter import reset_for_tests
    reset_for_tests()
    api_client._rate_limit_per_minute = 6000  # large bucket so acquire() never blocks

    spy = MagicMock(side_effect=lambda *a, **kw: MagicMock(
        models=MagicMock(pce_cache=MagicMock(rate_limit_per_minute=400))
    ))
    monkeypatch.setattr("src.config.ConfigManager", spy)

    url = "https://pce.example.com:8443/api/v2/test"
    responses.add(responses.GET, url, status=200, body=b'{"ok": true}')

    status, _ = api_client._request(url, rate_limit=True)

    assert status == 200
    spy.assert_not_called()


def test_get_events_rate_limit_true_reaches_request(api_client):
    """get_events(rate_limit=True) must actually flow into _request's
    rate-limit gate, not silently drop the flag."""
    calls = []

    def fake_request(url, **kwargs):
        calls.append(kwargs.get("rate_limit"))
        return 200, b"[]"

    api_client._request = fake_request

    api_client.get_events(max_results=10, since="2026-01-01T00:00:00Z", rate_limit=True)

    assert calls == [True]


def test_get_traffic_flows_async_enforces_max_results(api_client):
    """get_traffic_flows_async(max_results=N) must actually cap the returned
    flows, since fetch_traffic_for_report has no max_results parameter of
    its own to forward the cap to."""
    fake_flows = [{"i": i} for i in range(10)]
    api_client.fetch_traffic_for_report = MagicMock(return_value=fake_flows)

    result = api_client.get_traffic_flows_async(max_results=3, since="2026-01-01T00:00:00Z")

    assert result == fake_flows[:3]
