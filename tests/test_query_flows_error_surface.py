"""Task 2 (deferred minors hardening, spec §B)：Analyzer.query_flows must
distinguish "the PCE-side query failed" from "0 flows matched" for
interactive callers (GUI quarantine search, dashboard top10).

Contract: after the traffic stream (api/mixed source) is exhausted, if
ApiClient.last_fetch_error is non-empty, that means submit/poll/download/
stream-exception failed on the PCE side this call — it must not be
returned as an empty list indistinguishable from a genuine 0-match query.
cache-only source never talks to the PCE, so it is not checked (a stale
last_fetch_error from an earlier api call must not leak into a cache hit).
"""
import pytest
from unittest.mock import MagicMock

from src.analyzer import Analyzer
from src.exceptions import TrafficQueryError


def _analyzer():
    mock_cm = MagicMock()
    mock_cm.config = {"rules": []}
    az = Analyzer(mock_cm, MagicMock(), MagicMock())
    az.load_state = MagicMock()
    az.save_state = MagicMock()
    return az


def _params(**extra):
    p = {
        "start_time": "2026-01-01T00:00:00Z",
        "end_time": "2026-01-02T00:00:00Z",
    }
    p.update(extra)
    return p


def test_query_flows_raises_on_api_fetch_error(monkeypatch):
    ana = _analyzer()
    monkeypatch.setattr(ana, "_fetch_query_flows",
                        lambda *a, **kw: (iter([]), "api"))
    ana.api.last_fetch_error = "submit failed: 406 - unsupported payload"
    with pytest.raises(TrafficQueryError, match="406"):
        ana.query_flows(_params())


def test_query_flows_empty_without_error_returns_list(monkeypatch):
    ana = _analyzer()
    monkeypatch.setattr(ana, "_fetch_query_flows",
                        lambda *a, **kw: (iter([]), "api"))
    ana.api.last_fetch_error = None
    assert ana.query_flows(_params()) == []


def test_query_flows_mixed_source_raises_on_fetch_error(monkeypatch):
    ana = _analyzer()
    monkeypatch.setattr(ana, "_fetch_query_flows",
                        lambda *a, **kw: (iter([]), "mixed"))
    ana.api.last_fetch_error = "download failed: HTTP 500"
    with pytest.raises(TrafficQueryError, match="500"):
        ana.query_flows(_params())


def test_query_flows_cache_source_ignores_stale_fetch_error(monkeypatch):
    """Pin: cache-only reads never hit the PCE, so a stale
    last_fetch_error left over from an earlier, unrelated api call must
    not cause a spurious raise."""
    ana = _analyzer()
    monkeypatch.setattr(ana, "_fetch_query_flows",
                        lambda *a, **kw: (iter([]), "cache"))
    ana.api.last_fetch_error = "stale error from a previous api call"
    assert ana.query_flows(_params()) == []
