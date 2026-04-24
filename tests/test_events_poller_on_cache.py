"""Tests for EventPoller delegating to CacheSubscriber when provided."""

from unittest.mock import MagicMock, patch

from src.events.poller import EventPoller


class FakeApi:
    def fetch_events_strict(self, start_time_str, end_time_str=None, max_results=5000):
        return []


def test_poller_delegates_to_subscriber_when_set():
    """When subscriber is provided, poll() calls subscriber.poll_new_rows() and returns its result."""
    mock_sub = MagicMock()
    expected = [{"href": "/orgs/1/events/1", "event_type": "user.login"}]
    mock_sub.poll_new_rows.return_value = expected

    poller = EventPoller(FakeApi(), subscriber=mock_sub)
    result = poller.poll()

    mock_sub.poll_new_rows.assert_called_once()
    assert result == expected


def test_poller_uses_legacy_path_when_no_subscriber():
    """When subscriber=None, poll() uses the legacy fetch path."""
    poller = EventPoller(FakeApi(), subscriber=None)

    with patch.object(poller, "_legacy_poll", return_value=[]) as mock_legacy:
        result = poller.poll()

    mock_legacy.assert_called_once()
    assert result == []


def test_poller_subscriber_result_is_returned_unchanged():
    """poll() returns the subscriber result list unchanged (no transformation)."""
    mock_sub = MagicMock()
    events = [
        {"href": "/orgs/1/events/2", "event_type": "user.logout"},
        {"href": "/orgs/1/events/3", "event_type": "user.login"},
    ]
    mock_sub.poll_new_rows.return_value = events

    poller = EventPoller(FakeApi(), subscriber=mock_sub)
    result = poller.poll()

    assert result is events
