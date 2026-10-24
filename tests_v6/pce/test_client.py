import base64
import socket
from unittest.mock import MagicMock

import pytest
import requests
import responses

from illumio_ops.pce import client as client_mod
from illumio_ops.pce.client import (
    PceClient,
    PceNotConfigured,
    PceTransportError,
    client_from_settings,
)
from illumio_ops.pce.rate_limit import RateLimiter

from .conftest import BASE, pce_settings


@responses.activate
def test_org_scoped_and_global_paths(client):
    responses.add(responses.GET, f"{BASE}/api/v2/orgs/1/labels", json=[])
    responses.add(responses.GET, f"{BASE}/api/v2/noop", status=204)
    assert client.request("GET", "/labels").status == 200
    assert client.request("GET", "/noop", org_scoped=False).status == 204


@responses.activate
def test_basic_auth_and_json_body(client):
    responses.add(responses.POST, f"{BASE}/api/v2/orgs/1/x", status=201, json={"href": "/h"})
    r = client.request("POST", "/x", json={"name": "test"})
    req = responses.calls[0].request
    assert req.headers["Authorization"] == "Basic " + base64.b64encode(b"test-key:test-secret").decode()
    assert req.headers["Content-Type"] == "application/json"
    assert b'"name"' in req.body
    assert r.status == 201 and r.json() == {"href": "/h"}


@responses.activate
def test_non_2xx_is_returned_not_raised(client):
    responses.add(responses.GET, f"{BASE}/api/v2/orgs/1/x", status=404, body=b"nope")
    r = client.request("GET", "/x")
    assert (r.status, r.body) == (404, b"nope")


@pytest.mark.parametrize(("verify", "expected"), [(True, True), (False, False), ("/etc/ssl/ca.crt", "/etc/ssl/ca.crt")])
def test_verify_tls_three_modes(verify, expected, monkeypatch):
    monkeypatch.setattr(client_mod, "SYSTEM_CA_BUNDLES", ())
    c = PceClient(pce_settings(verify_tls=verify))
    assert c._session.verify == expected and c._bounded_session.verify == expected


def test_retry_adapter_parameters_match_5x(client):
    a = client._session.get_adapter(BASE)
    r = a.max_retries
    assert r.total == 3 and r.backoff_factor == 1.0
    assert set(r.status_forcelist) == {429, 502, 503, 504}
    assert r.allowed_methods == frozenset({"GET", "HEAD", "PUT", "DELETE"})
    assert "POST" not in r.allowed_methods
    assert r.respect_retry_after_header is True and r.raise_on_status is False
    assert a._pool_connections == 10 and a._pool_maxsize == 20
    b = client._bounded_session.get_adapter(BASE)
    assert b.max_retries.total == 0 and b._pool_connections == 2 and b._pool_maxsize == 4


@responses.activate
def test_get_429_retried_by_adapter(client):
    url = f"{BASE}/api/v2/health"
    responses.add(responses.GET, url, status=429, headers={"Retry-After": "0"})
    responses.add(responses.GET, url, status=429, headers={"Retry-After": "0"})
    responses.add(responses.GET, url, status=200, body=b'{"ok": true}')
    assert client.request("GET", "/health", org_scoped=False).status == 200
    assert len(responses.calls) == 3


@responses.activate
def test_persistent_503_returns_last_status(client):
    url = f"{BASE}/api/v2/health"
    for _ in range(4):
        responses.add(responses.GET, url, status=503, headers={"Retry-After": "0"})
    assert client.request("GET", "/health", org_scoped=False).status == 503


@responses.activate
def test_get_400_not_retried(client):
    responses.add(responses.GET, f"{BASE}/api/v2/orgs/1/w", status=400)
    assert client.request("GET", "/w").status == 400
    assert len(responses.calls) == 1


@responses.activate
def test_bounded_session_does_not_retry(client):
    url = f"{BASE}/api/v2/orgs/1/events"
    responses.add(responses.GET, url, status=503, headers={"Retry-After": "0"})
    responses.add(responses.GET, url, status=200)
    assert client.request("GET", "/events", bounded=True).status == 503
    assert len(responses.calls) == 1


def _closed_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_transport_failure_raises_not_empty():
    c = PceClient(pce_settings(url=f"http://127.0.0.1:{_closed_port()}"))
    with pytest.raises(PceTransportError) as e:
        c.request("GET", "/noop", org_scoped=False, timeout=3)
    assert e.value.kind == "refused" and e.value.path == "/noop"
    assert "test-secret" not in str(e.value)


@pytest.mark.parametrize(("exc", "kind"), [
    (requests.exceptions.ConnectTimeout(), "timeout"),
    (requests.exceptions.ReadTimeout(), "timeout"),
    (requests.exceptions.SSLError(), "tls"),
])
@responses.activate
def test_transport_error_kinds(client, exc, kind):
    responses.add(responses.GET, f"{BASE}/api/v2/noop", body=exc)
    with pytest.raises(PceTransportError) as e:
        client.request("GET", "/noop", org_scoped=False)
    assert e.value.kind == kind


def test_dns_failure_kind():
    c = PceClient(pce_settings(url="https://no-such-host.invalid"))
    with pytest.raises(PceTransportError) as e:
        c.request("GET", "/noop", org_scoped=False, timeout=5)
    assert e.value.kind == "dns"


def test_deadline_already_passed_raises_timeout(client):
    with pytest.raises(PceTransportError) as e:
        client.request("GET", "/x", deadline=0.0)
    assert e.value.kind == "timeout"


def _resp(status, content=b"{}", headers=None):
    r = MagicMock()
    r.status_code, r.content, r.headers = status, content, headers or {}
    return r


@pytest.fixture
def sleeps(monkeypatch):
    calls = []
    monkeypatch.setattr(client_mod, "_sleep", calls.append)
    return calls


def test_post_429_single_retry(client, sleeps):
    client._session.request = MagicMock(side_effect=[_resp(429, headers={"Retry-After": "0"}), _resp(200, b'{"ok":true}')])
    r = client.request("POST", "/traffic_flows/async_queries", json={"a": 1})
    assert (r.status, r.body) == (200, b'{"ok":true}')
    assert client._session.request.call_count == 2 and sleeps == [0.0]


def test_post_429_second_429_not_retried_again(client, sleeps):
    client._session.request = MagicMock(side_effect=[_resp(429), _resp(429, b"still limited")])
    r = client.request("POST", "/sec_policy", json={"a": 1})
    assert (r.status, r.body) == (429, b"still limited")
    assert client._session.request.call_count == 2


def test_post_429_retry_sends_same_body_and_headers(client, sleeps):
    client._session.request = MagicMock(side_effect=[_resp(429), _resp(200)])
    client.request("POST", "/sec_policy", json={"a": 1})
    first, second = client._session.request.call_args_list
    assert first.kwargs["data"] == second.kwargs["data"]
    assert first.kwargs["headers"] == second.kwargs["headers"]


@pytest.mark.parametrize(("header", "expected"), [
    ("0", 0.0), ("3600", 30.0), ("99", 30.0), ("-5", 0.0), ("inf", 2.0), ("nan", 2.0),
    ("Wed, 21 Oct 2026 07:28:00 GMT", 2.0), (None, 2.0),
])
def test_post_429_retry_after_clamped(client, sleeps, header, expected):
    headers = {} if header is None else {"Retry-After": header}
    client._session.request = MagicMock(side_effect=[_resp(429, headers=headers), _resp(200)])
    assert client.request("POST", "/sec_policy", json={}).status == 200
    assert sleeps == [expected]


def test_get_429_not_retried_in_request_layer(client, sleeps):
    client._session.request = MagicMock(return_value=_resp(429, headers={"Retry-After": "0"}))
    assert client.request("GET", "/health", org_scoped=False).status == 429
    assert client._session.request.call_count == 1 and sleeps == []


def test_post_429_retry_reacquires_budget(sleeps):
    rl = RateLimiter(rate_per_minute=6, burst=1)
    c = PceClient(pce_settings(), rate_limiter=rl)
    c._session.request = MagicMock(side_effect=[_resp(429, b"limited"), _resp(200)])
    r = c.request("POST", "/sec_policy", json={}, deadline=None, budget_timeout=0.01)
    assert (r.status, r.body) == (429, b"limited")
    assert c._session.request.call_count == 1


def test_client_from_unconfigured_settings_raises():
    for kw in ({"url": ""}, {"org_id": ""}, {"api_key": ""}, {"api_secret": ""}):
        with pytest.raises(PceNotConfigured):
            client_from_settings(pce_settings(**kw))
    client_from_settings(pce_settings()).close()


def test_closed_client_refuses_requests():
    c = PceClient(pce_settings())
    c.close()
    with pytest.raises(RuntimeError):
        c.request("GET", "/x")


def test_verify_true_uses_the_os_trust_store(tmp_path, monkeypatch):
    bundle = tmp_path / "ca-certificates.crt"
    bundle.write_text("-----BEGIN CERTIFICATE-----\n")
    monkeypatch.setattr(client_mod, "SYSTEM_CA_BUNDLES", (str(tmp_path / "missing.pem"), str(bundle)))
    c = PceClient(pce_settings(verify_tls=True))
    assert c._session.verify == str(bundle) and c._bounded_session.verify == str(bundle)


def test_verify_true_falls_back_to_bundled_cas_without_an_os_store(tmp_path, monkeypatch):
    monkeypatch.setattr(client_mod, "SYSTEM_CA_BUNDLES", (str(tmp_path / "missing.pem"),))
    assert PceClient(pce_settings(verify_tls=True))._session.verify is True


def test_unreadable_ca_bundle_is_a_transport_error():
    c = PceClient(pce_settings(verify_tls="/nonexistent/ca.pem"))
    with pytest.raises(PceTransportError) as e:
        c.request("GET", "/noop", org_scoped=False)
    assert e.value.kind == "ca_bundle"
