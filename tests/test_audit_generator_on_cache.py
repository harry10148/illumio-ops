"""Tests for AuditGenerator cache-first data sourcing."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
import pytest


def _make_mock_api():
    api = MagicMock()
    api.get_events.return_value = []
    return api


def _make_cache_reader(cover_state="full", events=None, earliest=None):
    cr = MagicMock()
    cr.cover_state.return_value = cover_state
    cr.read_events.return_value = events or [{"event_type": "policy.update", "timestamp": "2026-01-01T00:00:00Z"}]
    cr.earliest_ingested_at.return_value = earliest
    cr.earliest_data_timestamp.return_value = earliest
    return cr


def test_audit_generator_uses_cache_when_full(tmp_path):
    """When cover_state=full, AuditGenerator reads from cache and does NOT call api.get_events."""
    from src.report.audit_generator import AuditGenerator
    api = _make_mock_api()
    cache = _make_cache_reader(cover_state="full")
    gen = AuditGenerator(api=api, cache_reader=cache)
    start = datetime.now(timezone.utc) - timedelta(days=1)
    end = datetime.now(timezone.utc)
    events, source = gen._fetch_events(start, end)
    cache.read_events.assert_called_once()
    api.get_events.assert_not_called()
    assert source == "cache"


def test_audit_generator_bypasses_cache_when_none(tmp_path):
    """When cache_reader=None, AuditGenerator falls through to api.get_events."""
    from src.report.audit_generator import AuditGenerator
    api = _make_mock_api()
    api.fetch_events.return_value = []
    gen = AuditGenerator(api=api, cache_reader=None)
    start = datetime.now(timezone.utc) - timedelta(days=1)
    end = datetime.now(timezone.utc)
    events, source = gen._fetch_events(start, end)
    api.fetch_events.assert_called_once()
    api.get_events.assert_not_called()
    assert source == "api"


def test_audit_generator_partial_no_earliest_falls_back(tmp_path):
    """When cover_state=partial but earliest_ingested_at returns None
    (cache empty / inconsistent), AuditGenerator falls back to api.get_events
    (no hybrid possible)."""
    from src.report.audit_generator import AuditGenerator
    api = _make_mock_api()
    api.fetch_events.return_value = []
    cache = _make_cache_reader(cover_state="partial", earliest=None)
    gen = AuditGenerator(api=api, cache_reader=cache)
    start = datetime.now(timezone.utc) - timedelta(days=1)
    end = datetime.now(timezone.utc)
    events, source = gen._fetch_events(start, end)
    api.fetch_events.assert_called_once()
    api.get_events.assert_not_called()
    assert source == "api"


def test_audit_generator_partial_uses_hybrid(tmp_path):
    """When cover_state=partial AND earliest > start, AuditGenerator runs the
    hybrid path: api.fetch_events fills the gap, cache.read_events covers the
    rest. Returns source='mixed'."""
    from src.report.audit_generator import AuditGenerator
    api = _make_mock_api()
    api.fetch_events.return_value = [{"event_type": "gap_event", "timestamp": "2026-01-01T00:00:00Z"}]
    start = datetime.now(timezone.utc) - timedelta(days=2)
    end = datetime.now(timezone.utc)
    cache_start = datetime.now(timezone.utc) - timedelta(days=1)
    cache = _make_cache_reader(cover_state="partial", earliest=cache_start)
    gen = AuditGenerator(api=api, cache_reader=cache)
    events, source = gen._fetch_events(start, end)
    api.fetch_events.assert_called_once()
    cache.read_events.assert_called_once()
    api.get_events.assert_not_called()
    assert source == "mixed"
    # Hybrid result should contain BOTH gap events and cached events.
    assert len(events) == 2


def test_audit_generator_falls_back_on_miss(tmp_path):
    """When cover_state=miss, AuditGenerator falls back to api.get_events."""
    from src.report.audit_generator import AuditGenerator
    api = _make_mock_api()
    api.fetch_events.return_value = []
    cache = _make_cache_reader(cover_state="miss")
    gen = AuditGenerator(api=api, cache_reader=cache)
    start = datetime.now(timezone.utc) - timedelta(days=1)
    end = datetime.now(timezone.utc)
    events, source = gen._fetch_events(start, end)
    api.fetch_events.assert_called_once()
    api.get_events.assert_not_called()
    assert source == "api"


def test_fetch_events_partial_with_empty_api_gap_tags_as_cache(tmp_path):
    """Audit hybrid: when PCE returns 0 events for the gap, source must
    be 'cache' (not 'mixed' or 'api')."""
    from src.report.audit_generator import AuditGenerator
    api = _make_mock_api()
    api.fetch_events.return_value = []  # API gap is empty
    start = datetime.now(timezone.utc) - timedelta(days=7)
    end = datetime.now(timezone.utc)
    cache_start = datetime.now(timezone.utc) - timedelta(days=3)
    cache = _make_cache_reader(cover_state="partial", earliest=cache_start)
    cache.earliest_data_timestamp.return_value = cache_start
    gen = AuditGenerator(api=api, cache_reader=cache)
    events, source = gen._fetch_events(start, end)
    api.fetch_events.assert_called_once()
    cache.read_events.assert_called_once()
    api.get_events.assert_not_called()
    assert source == "cache"


def test_fetch_events_partial_with_api_error_falls_back_to_api(tmp_path):
    """Audit hybrid: when the API gap call raises, the partial branch must NOT
    retag as 'cache' — it must fall through to the full API path. Otherwise
    transient PCE errors silently masquerade as full cache hits."""
    from src.report.audit_generator import AuditGenerator
    api = _make_mock_api()
    # First fetch_events call (gap) raises; second (full fallthrough) succeeds.
    api.fetch_events.side_effect = [
        Exception("PCE timeout"),
        [{"event_type": "user.login", "timestamp": "2026-01-01T00:00:00Z"}],
    ]
    start = datetime.now(timezone.utc) - timedelta(days=7)
    end = datetime.now(timezone.utc)
    cache_start = datetime.now(timezone.utc) - timedelta(days=3)
    cache = _make_cache_reader(cover_state="partial", earliest=cache_start)
    cache.earliest_data_timestamp.return_value = cache_start
    gen = AuditGenerator(api=api, cache_reader=cache)
    events, source = gen._fetch_events(start, end)
    # Must fall through to the full API window, not silently return cache data.
    assert api.fetch_events.call_count == 2
    api.get_events.assert_not_called()
    assert source == "api"


def test_fetch_events_hybrid_boundary_event_counted_exactly_once(tmp_path):
    """資料層行為鎖（Task F3，C6 同型 follow-up）：timestamp 恰好等於
    cache_start 的 event，在合併結果中必須恰好出現一次。

    兩個 mock 資料來源皆忠實模擬「兩端皆含端點」的查詢語意：
    - PCE events API 以 timestamp[gte]/timestamp[lte] 建構查詢（見
      src/api_client.py._build_events_url），兩個運算子皆為 inclusive，
      比 analyzer 的 traffic API 假設更明確（gte/lte 直接寫在參數名中）。
    - cache.read_events 依 timestamp >= start AND <= end 過濾（見
      src/pce_cache/reader.py read_events）。
    修正前 API gap 以 cache_start 結束、cache 亦含 cache_start 端點，
    合併後邊界 event 出現兩次；修正後 gap 結束於 cache_start 前 1 秒，
    只有 cache 側回傳它 → 一次。
    """
    from src.report.audit_generator import AuditGenerator

    # 秒解析度截斷：_fetch_events 直接用 start.isoformat() 組 URL 參數，
    # 若帶微秒會與測試模擬的 '%Y-%m-%dT%H:%M:%SZ' 格式對不上。
    now = datetime.now(timezone.utc).replace(microsecond=0)
    cache_start = now - timedelta(days=1)
    start = now - timedelta(days=2)

    def _parse(ts):
        return datetime.strptime(ts, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)

    boundary_event = {"event_type": "boundary",
                      "timestamp": cache_start.strftime('%Y-%m-%dT%H:%M:%SZ')}
    gap_event = {"event_type": "gap-only",
                "timestamp": (cache_start - timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ')}
    all_events = [gap_event, boundary_event]

    api = _make_mock_api()

    def _api_fetch(start_str, end_str):
        # 模擬 PCE events API：timestamp[gte]=start_str, timestamp[lte]=end_str
        s, e = _parse(start_str), _parse(end_str)
        return [ev for ev in all_events if s <= _parse(ev["timestamp"]) <= e]
    api.fetch_events.side_effect = _api_fetch

    cache = _make_cache_reader(cover_state="partial", earliest=cache_start)

    def _cache_read(start_dt, end_dt):
        # 模擬 read_events：timestamp >= start AND <= end（皆含端點）
        return [ev for ev in all_events if start_dt <= _parse(ev["timestamp"]) <= end_dt]
    cache.read_events.side_effect = _cache_read

    gen = AuditGenerator(api=api, cache_reader=cache)
    events, source = gen._fetch_events(start, now)

    types = [ev["event_type"] for ev in events]
    assert types.count("boundary") == 1  # 端點 event 恰好一次
    assert types.count("gap-only") == 1  # gap 段 event 不受影響
    assert source == "mixed"
