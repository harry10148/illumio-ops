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

    def _request(self, url, method="GET", data=None, timeout=None):
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
