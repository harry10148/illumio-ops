"""Audit report must fall back to live API when the cache window doesn't cover the request.

Root cause: CacheReader.cover_state() judges coverage by the *earliest* cached event
timestamp only. A stale cache whose newest event predates the request `start` still
reports "full", so read_events(start, end) returns an empty list marked source="cache"
and the audit report shows "no data" even though the live PCE has events for the window.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from src.report.audit_generator import AuditGenerator


def test_stale_cache_falls_back_to_api():
    """cover_state='full' but cache yields 0 events (stale window) → fall back to live API."""
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=7)
    end = now

    cache = MagicMock()
    cache.cover_state.return_value = "full"
    # Stale cache: newest event is far older than `start`; the windowed read is empty.
    cache.read_events.return_value = []

    api = MagicMock()
    # Fallback uses the windowed fetch_events(start, end) (not the 500-capped
    # get_events(since=...)); it must honor both ends of the window.
    api.fetch_events.return_value = [
        {"event_type": "policy.update", "href": "/orgs/1/events/a"},
        {"event_type": "policy.update", "href": "/orgs/1/events/b"},
        {"event_type": "policy.update", "href": "/orgs/1/events/c"},
    ]

    gen = AuditGenerator(api=api, cache_reader=cache)
    events, source = gen._fetch_events(start, end)

    assert len(events) == 3
    assert source == "api"
    api.fetch_events.assert_called_once()
    api.get_events.assert_not_called()


def test_empty_partial_hybrid_falls_back_to_api():
    """Partial coverage where both the API gap and cache read are empty → fall back to API."""
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=7)
    end = now

    cache = MagicMock()
    cache.cover_state.return_value = "partial"
    cache.earliest_data_timestamp.return_value = now - timedelta(days=3)
    cache.read_events.return_value = []  # cache portion empty

    api = MagicMock()
    # First fetch_events call = the (empty) hybrid gap; second = the full-window
    # fallback after both hybrid halves come back empty.
    api.fetch_events.side_effect = [
        [],
        [
            {"event_type": "policy.update", "href": "/orgs/1/events/x"},
            {"event_type": "policy.update", "href": "/orgs/1/events/y"},
            {"event_type": "policy.update", "href": "/orgs/1/events/z"},
        ],
    ]

    gen = AuditGenerator(api=api, cache_reader=cache)
    events, source = gen._fetch_events(start, end)

    assert len(events) == 3
    assert source == "api"
    assert api.fetch_events.call_count == 2
    api.get_events.assert_not_called()


def test_cache_with_data_still_uses_cache():
    """Regression guard: a healthy cache that returns events is still preferred over API."""
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=7)
    end = now

    cache = MagicMock()
    cache.cover_state.return_value = "full"
    cache.read_events.return_value = [{"event_type": "policy.update", "href": "/orgs/1/events/cached"}]

    api = MagicMock()
    api.get_events.return_value = []

    gen = AuditGenerator(api=api, cache_reader=cache)
    events, source = gen._fetch_events(start, end)

    assert len(events) == 1
    assert source == "cache"
    api.get_events.assert_not_called()
