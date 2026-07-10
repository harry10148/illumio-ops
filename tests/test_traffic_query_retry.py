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


# ── ingest-error-signal: submit-layer connection failure must not look like
# a genuinely-empty query (watchdog-live-reverify-report.md step 2 — traffic
# 鏈 "同構" bug: status=0 from a connection-layer failure was swallowed here
# exactly like fetch_events(), so TrafficIngestor never saw an error).


def test_async_query_connection_failure_sets_last_fetch_error():
    c = _client()
    c.last_fetch_error = None

    def fake_request(url, method="GET", data=None, timeout=None, rate_limit=False):
        return 0, b"Connection refused"  # mirrors ApiClient._request's connection-failure return

    c._request.side_effect = fake_request
    b = TrafficQueryBuilder(c)
    rows = list(b._submit_and_stream_async_query({}))

    assert rows == []  # graceful degrade for existing (report) consumers, unchanged
    assert c.last_fetch_error, \
        "connection failure must be recorded so TrafficIngestor can distinguish it from a genuinely empty query"


def test_async_query_success_clears_last_fetch_error():
    c = _client()
    c.last_fetch_error = "stale error from a previous failed poll"
    full_dl = _gzip_rows([{"src": {"ip": "a"}}])

    def fake_request(url, method="GET", data=None, timeout=None, rate_limit=False):
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
    assert c.last_fetch_error is None


def test_async_query_genuinely_empty_does_not_set_last_fetch_error():
    """Reverse pin: a real PCE response reporting 0 matches must not be
    mistaken for a connection failure."""
    c = _client()
    c.last_fetch_error = None
    empty_dl = _gzip_rows([])

    def fake_request(url, method="GET", data=None, timeout=None, rate_limit=False):
        if url.endswith("/async_queries"):
            return 202, json.dumps({"href": "/orgs/1/traffic_flows/async_queries/q1"}).encode()
        if url.endswith("/download"):
            return 200, empty_dl
        return 200, json.dumps({"status": "completed", "matches_count": 0}).encode()

    c._request.side_effect = fake_request
    b = TrafficQueryBuilder(c)
    with patch("src.api.traffic_query.time.sleep", lambda *a, **k: None):
        rows = list(b._submit_and_stream_async_query({}))

    assert rows == []
    assert c.last_fetch_error is None


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


# ── Task 1 (Hardening follow-ups): remaining three swallowed-error branches
# in _submit_and_stream_async_query (poll timeout, state=="failed", download
# failure) must also surface into last_fetch_error, same convention as the
# submit-failure / connection-failure fix above.


def test_poll_timeout_sets_last_fetch_error(monkeypatch):
    c = _client()
    c.last_fetch_error = None

    def fake_request(url, method="GET", data=None, timeout=None, rate_limit=False):
        if url.endswith("/async_queries"):
            return 202, json.dumps({"href": "/orgs/1/traffic_flows/async_queries/q1"}).encode()
        return 200, json.dumps({"status": "running"}).encode()

    c._request.side_effect = fake_request
    monkeypatch.setattr("src.api.traffic_query._ASYNC_QUERY_MAX_WAIT_SECONDS", 0)
    b = TrafficQueryBuilder(c)
    with patch("src.api.traffic_query.time.sleep", lambda *a, **k: None):
        rows = list(b._submit_and_stream_async_query({}))

    assert rows == []
    assert c.last_fetch_error is not None and "timeout" in c.last_fetch_error.lower()


def test_query_state_failed_sets_last_fetch_error():
    c = _client()
    c.last_fetch_error = None

    def fake_request(url, method="GET", data=None, timeout=None, rate_limit=False):
        if url.endswith("/async_queries"):
            return 202, json.dumps({"href": "/orgs/1/traffic_flows/async_queries/q1"}).encode()
        return 200, json.dumps({"status": "failed"}).encode()

    c._request.side_effect = fake_request
    b = TrafficQueryBuilder(c)
    with patch("src.api.traffic_query.time.sleep", lambda *a, **k: None):
        rows = list(b._submit_and_stream_async_query({}))

    assert rows == []
    assert c.last_fetch_error is not None and "failed" in c.last_fetch_error.lower()


def test_submit_accepted_but_no_href_sets_last_fetch_error():
    c = _client()
    c.last_fetch_error = None

    def fake_request(url, method="GET", data=None, timeout=None, rate_limit=False):
        if url.endswith("/async_queries"):
            return 202, json.dumps({"status": "queued"}).encode()
        return 200, json.dumps({"status": "completed", "matches_count": 1}).encode()

    c._request.side_effect = fake_request
    b = TrafficQueryBuilder(c)
    rows = list(b._submit_and_stream_async_query({}))

    assert rows == []
    assert c.last_fetch_error is not None and "href" in c.last_fetch_error.lower()


def test_download_failure_sets_last_fetch_error():
    c = _client()
    c.last_fetch_error = None

    def fake_request(url, method="GET", data=None, timeout=None, rate_limit=False):
        if url.endswith("/async_queries"):
            return 202, json.dumps({"href": "/orgs/1/traffic_flows/async_queries/q1"}).encode()
        if url.endswith("/download"):
            return 500, None
        return 200, json.dumps({"status": "completed", "matches_count": 1}).encode()

    c._request.side_effect = fake_request
    b = TrafficQueryBuilder(c)
    with patch("src.api.traffic_query.time.sleep", lambda *a, **k: None):
        rows = list(b._submit_and_stream_async_query({}))

    assert rows == []
    assert c.last_fetch_error is not None and "download" in c.last_fetch_error.lower()


def test_download_retry_failure_then_success_clears_error():
    """Critical: first download succeeds with 0 rows → retry 1 fails (HTTP 500,
    sets last_fetch_error) → retry 2 succeeds with real rows → error must be
    cleared so downstream ingestor doesn't discard the recovered rows."""
    c = _client()
    c.last_fetch_error = None
    full_dl = _gzip_rows([{"src": {"ip": "a"}}, {"src": {"ip": "b"}}])
    state = {"dl": 0}

    def fake_request(url, method="GET", data=None, timeout=None, rate_limit=False):
        if url.endswith("/async_queries"):
            return 202, json.dumps({"href": "/orgs/1/traffic_flows/async_queries/q1"}).encode()
        if url.endswith("/download"):
            state["dl"] += 1
            if state["dl"] == 1:
                return 200, _gzip_rows([])  # first: 0 rows, triggers retry
            elif state["dl"] == 2:
                return 500, None  # retry 1: HTTP 500 failure, sets error
            else:
                return 200, full_dl  # retry 2: succeeds with 2 rows
        return 200, json.dumps({"status": "completed", "matches_count": 2}).encode()

    c._request.side_effect = fake_request
    b = TrafficQueryBuilder(c)
    with patch("src.api.traffic_query.time.sleep", lambda *a, **k: None):
        rows = list(b._submit_and_stream_async_query({}))

    assert len(rows) == 2, f"retry should recover 2 rows, got {len(rows)}"
    assert c.last_fetch_error is None, \
        "error must be cleared when retry succeeds, else ingestor discards recovered rows"


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
