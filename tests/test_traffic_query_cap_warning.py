"""Cap-hit visibility for the live traffic query fallback path.

Task 6's OOM guardrail falls back to live PCE queries when the cache window is
too large. That fallback (execute_traffic_query_stream / fetch_traffic_for_report)
sends max_results=MAX_TRAFFIC_RESULTS (200000) to the PCE, but silently returned no
signal when the response actually hit that cap — the same silent-truncation bug
class this repo's CLAUDE.md calls out (already fixed once in
ApiClient.get_traffic_flows_async). Assert a visible log warning, mirroring that
existing warning's style, when the PCE-returned flow count reaches the cap.

MAX_TRAFFIC_RESULTS is monkeypatched down to a small number so tests stay fast;
the module-level name is looked up fresh at call time, so patching the module
attribute is sufficient (no need to build 200000 fake flows).
"""
from unittest.mock import MagicMock

from loguru import logger

from src.api.traffic_query import TrafficQueryBuilder


def _client():
    c = MagicMock()
    c.base_url = "https://pce.test/api/v2/orgs/1"
    c.api_cfg = {"url": "https://pce.test", "org_id": "1"}
    c.last_traffic_query_diagnostics = {}
    return c


def _capture_warnings():
    msgs = []
    sink = logger.add(lambda m: msgs.append(str(m)), level="WARNING")
    return msgs, sink


def test_execute_traffic_query_stream_warns_on_cap_hit(monkeypatch):
    """PCE-returned flow count reaching MAX_TRAFFIC_RESULTS must log a warning
    naming both the count and the cap (mirrors get_traffic_flows_async's
    'truncating {n} flows to max_results={cap}' style)."""
    monkeypatch.setattr("src.api.traffic_query.MAX_TRAFFIC_RESULTS", 3)
    c = _client()
    b = TrafficQueryBuilder(c)
    monkeypatch.setattr(b, "_submit_and_stream_async_query",
                        lambda *a, **k: iter([{"flow": i} for i in range(3)]))

    msgs, sink = _capture_warnings()
    try:
        out = list(b.execute_traffic_query_stream(
            "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", ["allowed"]
        ))
    finally:
        logger.remove(sink)

    assert len(out) == 3
    assert any("3" in m and "200000" not in m and "max_results" in m for m in msgs), msgs


def test_execute_traffic_query_stream_quiet_under_cap(monkeypatch):
    """Fewer flows than the cap must not trigger the cap-hit warning."""
    monkeypatch.setattr("src.api.traffic_query.MAX_TRAFFIC_RESULTS", 3)
    c = _client()
    b = TrafficQueryBuilder(c)
    monkeypatch.setattr(b, "_submit_and_stream_async_query",
                        lambda *a, **k: iter([{"flow": i} for i in range(2)]))

    msgs, sink = _capture_warnings()
    try:
        out = list(b.execute_traffic_query_stream(
            "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", ["allowed"]
        ))
    finally:
        logger.remove(sink)

    assert len(out) == 2
    assert not any("max_results" in m for m in msgs), msgs


def test_fetch_traffic_for_report_warns_on_cap_hit(monkeypatch):
    """fetch_traffic_for_report must independently warn on cap-hit — it is
    exercised in isolation (execute_traffic_query_stream monkeypatched away,
    per this repo's existing test_fetch_traffic_for_report_* convention), so
    the warning cannot only live inside execute_traffic_query_stream."""
    monkeypatch.setattr("src.api.traffic_query.MAX_TRAFFIC_RESULTS", 3)
    c = _client()
    b = TrafficQueryBuilder(c)

    def fake_stream(start, end, pds, filters=None, compute_draft=False, rate_limit=False):
        return iter([{"src": {}, "dst": {}, "service": {}} for _ in range(3)])

    monkeypatch.setattr(b, "execute_traffic_query_stream", fake_stream)

    msgs, sink = _capture_warnings()
    try:
        out = b.fetch_traffic_for_report("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")
    finally:
        logger.remove(sink)

    assert len(out) == 3
    assert any("3" in m and "max_results" in m for m in msgs), msgs


def test_fetch_traffic_for_report_quiet_under_cap(monkeypatch):
    monkeypatch.setattr("src.api.traffic_query.MAX_TRAFFIC_RESULTS", 3)
    c = _client()
    b = TrafficQueryBuilder(c)

    def fake_stream(start, end, pds, filters=None, compute_draft=False, rate_limit=False):
        return iter([{"src": {}, "dst": {}, "service": {}} for _ in range(2)])

    monkeypatch.setattr(b, "execute_traffic_query_stream", fake_stream)

    msgs, sink = _capture_warnings()
    try:
        out = b.fetch_traffic_for_report("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")
    finally:
        logger.remove(sink)

    assert len(out) == 2
    assert not any("max_results" in m for m in msgs), msgs
