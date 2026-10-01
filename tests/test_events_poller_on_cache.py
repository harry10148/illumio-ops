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


def test_parse_event_timestamp_accepts_datetime():
    """raw_json 損毀時退回欄位投影，timestamp 是 datetime：不得丟 TypeError。"""
    import datetime as _dt
    from src.events.poller import parse_event_timestamp
    naive = _dt.datetime(2026, 9, 11, 3, 4, 5)
    assert parse_event_timestamp(naive) == naive.replace(tzinfo=_dt.timezone.utc)


def test_projection_fallback_serialises_datetimes():
    import datetime as _dt
    from types import SimpleNamespace
    from src.pce_cache.subscriber import _row_to_dict

    cols = [SimpleNamespace(name="id"), SimpleNamespace(name="timestamp")]
    row = SimpleNamespace(raw_json="{corrupt", id=7,
                          timestamp=_dt.datetime(2026, 9, 11, 3, 4, 5),
                          __table__=SimpleNamespace(columns=cols))
    assert _row_to_dict(row) == {"id": 7, "timestamp": "2026-09-11T03:04:05Z"}


def test_malformed_event_is_skipped_not_fatal(monkeypatch):
    """一筆格式異常的事件不得讓整批失敗（cache 部署上 cursor 會永遠卡住）。"""
    import src.analyzer as analyzer_mod
    from unittest.mock import MagicMock

    real = analyzer_mod.normalize_event

    def _normalize(event):
        if event.get("href") == "/bad":
            raise ValueError("malformed")
        return real(event)
    monkeypatch.setattr(analyzer_mod, "normalize_event", _normalize)
    ana = analyzer_mod.Analyzer.__new__(analyzer_mod.Analyzer)
    ana.state = {}
    ana.stats = MagicMock()
    ana._update_parser_observability = lambda *_: None
    ana._select_rules = lambda pred: []
    good = {"href": "/good", "event_type": "user.sign_in",
            "timestamp": "2026-09-11T03:04:05Z", "status": "success", "severity": "info"}
    ana._analyze_event_batch([{"href": "/bad"}, good], None)
    recorded = ana.stats.record_event_batch.call_args.args[0]
    assert [e["href"] for e in recorded] == ["/good"]
