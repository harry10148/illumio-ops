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

    def fake_request(url, method="GET", data=None, timeout=None, rate_limit=False):
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

    def fake_request(url, method="GET", data=None, timeout=None, rate_limit=False):
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

    def fake_request(url, method="GET", data=None, timeout=None, rate_limit=False):
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


# ── Task F4: rate_limit wiring through submit/poll/download ────────────────


def test_submit_and_stream_async_query_threads_rate_limit_to_every_request():
    """rate_limit=True must reach every c._request call in the submit→poll→
    download chain — each is a real outbound PCE HTTP call and must count
    against the limiter, not just the initial submit."""
    c = _client()
    full_dl = _gzip_rows([{"src": {"ip": "a"}}])
    seen = []

    def fake_request(url, method="GET", data=None, timeout=None, rate_limit=False):
        seen.append(rate_limit)
        if url.endswith("/async_queries"):
            return 202, json.dumps({"href": "/orgs/1/traffic_flows/async_queries/q1"}).encode()
        if url.endswith("/download"):
            return 200, full_dl
        return 200, json.dumps({"status": "completed", "matches_count": 1}).encode()

    c._request.side_effect = fake_request
    b = TrafficQueryBuilder(c)
    with patch("src.api.traffic_query.time.sleep", lambda *a, **k: None):
        rows = list(b._submit_and_stream_async_query({}, rate_limit=True))

    assert len(rows) == 1
    assert len(seen) >= 3, f"expected submit+poll+download calls, got {seen}"
    assert all(seen), f"rate_limit=True must reach every _request call, got {seen}"


def test_submit_and_stream_async_query_default_rate_limit_false():
    """Default (no rate_limit passed) must preserve today's unlimited behaviour
    for callers that don't opt in."""
    c = _client()
    full_dl = _gzip_rows([{"src": {"ip": "a"}}])
    seen = []

    def fake_request(url, method="GET", data=None, timeout=None, rate_limit=False):
        seen.append(rate_limit)
        if url.endswith("/async_queries"):
            return 202, json.dumps({"href": "/orgs/1/traffic_flows/async_queries/q1"}).encode()
        if url.endswith("/download"):
            return 200, full_dl
        return 200, json.dumps({"status": "completed", "matches_count": 1}).encode()

    c._request.side_effect = fake_request
    b = TrafficQueryBuilder(c)
    with patch("src.api.traffic_query.time.sleep", lambda *a, **k: None):
        rows = list(b._submit_and_stream_async_query({}))

    assert len(rows) == 1
    assert not any(seen), f"default must not enable rate_limit, got {seen}"


def test_execute_traffic_query_stream_threads_rate_limit(monkeypatch):
    """execute_traffic_query_stream must forward rate_limit down to
    _submit_and_stream_async_query."""
    c = _client()
    b = TrafficQueryBuilder(c)
    captured = {}

    def fake_submit(payload, compute_draft=False, rate_limit=False):
        captured["rate_limit"] = rate_limit
        return iter([])

    monkeypatch.setattr(b, "_submit_and_stream_async_query", fake_submit)
    list(b.execute_traffic_query_stream(
        "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", ["allowed"], rate_limit=True
    ))
    assert captured.get("rate_limit") is True


def test_fetch_traffic_for_report_threads_rate_limit(monkeypatch):
    """fetch_traffic_for_report must forward rate_limit down to
    execute_traffic_query_stream."""
    c = _client()
    c.last_traffic_query_diagnostics = {}
    b = TrafficQueryBuilder(c)
    captured = {}

    def fake_stream(start_time_str, end_time_str, policy_decisions, filters=None,
                    compute_draft=False, rate_limit=False):
        captured["rate_limit"] = rate_limit
        return iter([])

    monkeypatch.setattr(b, "execute_traffic_query_stream", fake_stream)
    b.fetch_traffic_for_report("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", rate_limit=True)
    assert captured.get("rate_limit") is True
