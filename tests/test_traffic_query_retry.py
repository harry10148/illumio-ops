"""Async traffic query resilience: re-download when the PCE reports a query
'completed' before its result file is materialized (intermittent 0-row downloads
seen only in the long-running --monitor-gui service)."""
import gzip
import io
import json

from unittest.mock import MagicMock, patch

from src.api.traffic_query import TrafficQueryBuilder


def _gzip_rows(rows):
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as f:
        f.write(json.dumps(rows).encode())
    return buf.getvalue()


def _client():
    c = MagicMock()
    c.base_url = "https://pce.test/api/v2/orgs/1"
    c.api_cfg = {"url": "https://pce.test", "org_id": "1"}
    return c


def test_async_query_retries_when_completed_but_download_empty():
    """completed + matches_count>0 but first download streams 0 rows -> re-download."""
    c = _client()
    empty_dl = _gzip_rows([])
    full_dl = _gzip_rows([{"src": {"ip": "a"}}, {"src": {"ip": "b"}}])
    state = {"dl": 0}

    def fake_request(url, method="GET", data=None, timeout=None):
        if url.endswith("/async_queries"):
            return 202, json.dumps({"href": "/orgs/1/traffic_flows/async_queries/q1"}).encode()
        if url.endswith("/download"):
            state["dl"] += 1
            return 200, (empty_dl if state["dl"] == 1 else full_dl)
        return 200, json.dumps({"status": "completed", "matches_count": 2}).encode()

    c._request.side_effect = fake_request
    b = TrafficQueryBuilder(c)
    with patch("src.api.traffic_query.time.sleep", lambda *a, **k: None):
        rows = list(b._submit_and_stream_async_query({}))
    assert len(rows) == 2, f"retry should recover 2 rows, got {len(rows)}"
    assert state["dl"] == 2, "should have re-downloaded once"


def test_async_query_no_retry_when_genuinely_empty():
    """matches_count == 0 (app with no traffic) must NOT retry — keeps it fast."""
    c = _client()
    empty_dl = _gzip_rows([])
    calls = {"dl": 0}

    def fake_request(url, method="GET", data=None, timeout=None):
        if url.endswith("/async_queries"):
            return 202, json.dumps({"href": "/orgs/1/traffic_flows/async_queries/q1"}).encode()
        if url.endswith("/download"):
            calls["dl"] += 1
            return 200, empty_dl
        return 200, json.dumps({"status": "completed", "matches_count": 0}).encode()

    c._request.side_effect = fake_request
    b = TrafficQueryBuilder(c)
    with patch("src.api.traffic_query.time.sleep", lambda *a, **k: None):
        rows = list(b._submit_and_stream_async_query({}))
    assert rows == []
    assert calls["dl"] == 1, "genuinely-empty query must not re-download"


def test_async_query_retry_gives_up_after_bound():
    """Persistent empty downloads stop after the bounded retries (no infinite loop)."""
    c = _client()
    empty_dl = _gzip_rows([])
    calls = {"dl": 0}

    def fake_request(url, method="GET", data=None, timeout=None):
        if url.endswith("/async_queries"):
            return 202, json.dumps({"href": "/orgs/1/traffic_flows/async_queries/q1"}).encode()
        if url.endswith("/download"):
            calls["dl"] += 1
            return 200, empty_dl
        return 200, json.dumps({"status": "completed", "matches_count": 7}).encode()

    c._request.side_effect = fake_request
    b = TrafficQueryBuilder(c)
    with patch("src.api.traffic_query.time.sleep", lambda *a, **k: None):
        rows = list(b._submit_and_stream_async_query({}))
    assert rows == []
    assert calls["dl"] == 4, "1 initial + 3 bounded retries"
