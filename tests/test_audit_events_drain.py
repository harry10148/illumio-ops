"""稽核報表：事件超過單次上限時切窗抽乾；PCE 錯誤不得看起來像空的一週。"""
from __future__ import annotations

import datetime as dt

import pytest

from src.pce_cache.events_fetch import EventsFetchError
from src.report.audit_generator import AuditGenerator

UTC = dt.timezone.utc


class _Api:
    """PCE 語意：視窗內超過 max_results 時只回最新的 max_results 筆。"""

    def __init__(self, events, error=None):
        self.events = events
        self.error = error
        self.last_fetch_error = None
        self.calls = 0

    def fetch_events(self, start_iso, end_time_str=None, max_results=10000, rate_limit=False):
        self.calls += 1
        self.last_fetch_error = self.error
        if self.error:
            return []
        s = dt.datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
        e = dt.datetime.fromisoformat(end_time_str.replace("Z", "+00:00"))
        hit = [ev for ev in self.events if s <= ev["_ts"] <= e]
        hit.sort(key=lambda ev: ev["_ts"], reverse=True)
        return hit[:max_results]


def _events(n, start):
    return [{"href": f"/orgs/1/events/{i}", "_ts": start + dt.timedelta(seconds=i * 30),
             "timestamp": (start + dt.timedelta(seconds=i * 30)).isoformat()} for i in range(n)]


def test_busy_week_is_not_cut_at_the_cap(monkeypatch):
    start = dt.datetime(2026, 9, 1, tzinfo=UTC)
    end = start + dt.timedelta(days=7)
    api = _Api(_events(250, start))
    gen = AuditGenerator(api=api)
    monkeypatch.setattr(AuditGenerator, "_EVENTS_MAX_RESULTS", 100)
    gen._events_truncation = []
    got = gen._fetch_api_events(start, end)
    assert len({e["href"] for e in got}) == 250
    assert gen._events_truncation == []


def test_pce_error_raises_instead_of_empty_report():
    api = _Api([], error="503: Service Unavailable")
    gen = AuditGenerator(api=api)
    with pytest.raises(EventsFetchError):
        gen.generate_from_api("2026-09-01T00:00:00Z", "2026-09-08T00:00:00Z")
