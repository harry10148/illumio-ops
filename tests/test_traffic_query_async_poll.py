"""Async traffic-query polling: deadline-based wait (not a fixed 120s cap)."""
from __future__ import annotations

import gzip
import io
from unittest.mock import patch

import orjson

from src.api.traffic_query import TrafficQueryBuilder


class _FakeClient:
    """Minimal stand-in for ApiClient as seen by TrafficQueryBuilder."""

    def __init__(self, poll_states):
        self.base_url = "https://pce.test/api/v2/orgs/1"
        self.api_cfg = {"url": "https://pce.test"}
        self._poll_states = list(poll_states)
        self._poll_i = 0

    def _gz(self, records):
        buf = io.BytesIO()
        with gzip.GzipFile(fileobj=buf, mode="wb") as f:
            f.write(orjson.dumps(records))
        return buf.getvalue()

    def _request(self, url, method="GET", data=None, timeout=None, rate_limit=False):
        if method == "POST" and url.endswith("/async_queries"):
            return 202, orjson.dumps(
                {"href": "/orgs/1/traffic_flows/async_queries/1", "status": "queued"}
            )
        if url.endswith("/download"):
            return 200, self._gz([{"flow": 1}, {"flow": 2}])
        # poll
        state = self._poll_states[min(self._poll_i, len(self._poll_states) - 1)]
        self._poll_i += 1
        return 200, orjson.dumps({"status": state})


def test_slow_query_beyond_old_cap_still_completes():
    """A query that stays 'running' for many polls (past the old 60×2s=120s
    budget) must still complete, not be abandoned."""
    client = _FakeClient(["running"] * 100 + ["completed"])
    builder = TrafficQueryBuilder(client)
    with patch("time.sleep"):  # don't actually wait
        out = list(builder._submit_and_stream_async_query({"sources": {}}))
    assert out == [{"flow": 1}, {"flow": 2}]
    assert client._poll_i > 60  # polled well past the old fixed cap


def test_query_gives_up_at_deadline_not_fixed_count():
    """If the PCE never finishes, polling stops at the wall-clock deadline and
    yields nothing (rather than hanging or looping on a fixed counter)."""
    client = _FakeClient(["running"])  # never completes
    builder = TrafficQueryBuilder(client)
    # monotonic: first call sets deadline (t=0 → deadline=900); then a couple of
    # in-budget ticks; then jump past the deadline to force the loop to exit.
    times = iter([0.0, 1.0, 2.0, 10_000.0, 10_000.0])
    with patch("time.sleep"), patch(
        "src.api.traffic_query.time.monotonic", lambda: next(times)
    ):
        out = list(builder._submit_and_stream_async_query({"sources": {}}))
    assert out == []


class _DiagClient:
    """Client stub exposing the diagnostics attribute fetch_traffic_for_report reads."""

    def __init__(self):
        self.last_traffic_query_diagnostics = {}
        self.last_rule_usage_batch_stats = {}


def test_fetch_traffic_for_report_applies_unresolved_native_filters():
    """A native filter (dst_labels) that fails href resolution is demoted into the
    *effective* fallback set published on the client diagnostics. fetch_traffic_for_report
    must apply that set client-side, otherwise the report is silently widened with
    flows that do NOT match the requested filter (audit: over-broad report data)."""
    client = _DiagClient()
    builder = TrafficQueryBuilder(client)

    match = {"src": {}, "service": {},
             "dst": {"workload": {"labels": [{"key": "App", "value": "DB"}]}}}
    nomatch = {"src": {}, "service": {},
               "dst": {"workload": {"labels": [{"key": "App", "value": "WEB"}]}}}

    def fake_stream(start, end, pds, filters=None, compute_draft=False, rate_limit=False):
        # Simulate native dst_labels resolution failure -> demoted to fallback.
        client.last_traffic_query_diagnostics = {
            "fallback_filters": {"dst_labels": ["App=DB"]},
            "unresolved_native_filters": {"dst_labels": ["App=DB"]},
        }
        yield match
        yield nomatch

    builder.execute_traffic_query_stream = fake_stream
    out = builder.fetch_traffic_for_report(
        "2026-04-01T00:00:00Z", "2026-04-02T00:00:00Z",
        filters={"dst_labels": ["App=DB"]},
    )

    # dst_labels is a *native* filter, so query_spec.fallback_filters is empty;
    # only the diagnostics-published effective fallback re-applies the filter.
    assert out == [match]
