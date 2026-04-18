"""Verify urllib3.Retry on ApiClient._session retries 429/5xx automatically."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import responses


@pytest.fixture
def api():
    from src.api_client import ApiClient
    cm = MagicMock()
    cm.config = {
        "api": {"url": "https://pce.test", "org_id": "1", "key": "k",
                "secret": "s", "verify_ssl": False},
    }
    return ApiClient(cm)


@responses.activate
def test_retry_on_429_eventually_succeeds(api):
    """After 2x 429 we should see a final 200."""
    url = "https://pce.test/api/v2/health"
    responses.add(responses.GET, url, status=429, headers={"Retry-After": "0"})
    responses.add(responses.GET, url, status=429, headers={"Retry-After": "0"})
    responses.add(responses.GET, url, status=200, body=b'{"ok": true}')

    status, body = api._request(url)
    assert status == 200
    assert b'"ok"' in body
    assert len(responses.calls) == 3


@responses.activate
def test_retry_exhausts_on_persistent_503(api):
    """After MAX_RETRIES of 503 the final 503 is returned."""
    url = "https://pce.test/api/v2/health"
    for _ in range(4):   # MAX_RETRIES + 1 to be safe
        responses.add(responses.GET, url, status=503)

    status, body = api._request(url)
    # Final status is 503 (not 0) — urllib3 returned last response, not an exception
    assert status == 503


@responses.activate
def test_no_retry_on_400(api):
    """4xx other than 429 must NOT be retried (client error, not transient)."""
    url = "https://pce.test/api/v2/workloads/bad"
    responses.add(responses.GET, url, status=400, body=b'{"error":"bad"}')

    status, body = api._request(url)
    assert status == 400
    assert len(responses.calls) == 1   # exactly one call
