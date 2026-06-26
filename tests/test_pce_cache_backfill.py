"""Tests for BackfillRunner — bypasses watermark, inserts by date range."""
from datetime import datetime, timedelta, timezone
import json
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import PceEvent, PceTrafficFlowRaw


@pytest.fixture
def session_factory(tmp_path):
    from src.pce_cache.schema import init_schema
    engine = create_engine(f"sqlite:///{tmp_path / 'bf.sqlite'}")
    init_schema(engine)
    return sessionmaker(engine)


def _make_mock_api_events(events):
    from unittest.mock import MagicMock
    api = MagicMock()
    api.get_events.return_value = events
    return api


def _make_mock_api_traffic(flows):
    from unittest.mock import MagicMock
    api = MagicMock()
    api.fetch_traffic_for_report.return_value = flows
    return api


def _event(n):
    ts = (datetime.now(timezone.utc) - timedelta(days=n)).isoformat()
    return {
        "href": f"/orgs/1/events/e{n}",
        "event_type": "policy.update",
        "severity": "info",
        "status": "success",
        "pce_fqdn": "pce.example.com",
        "timestamp": ts,
        "notifications": [{"notification_type": "policy.update"}],
    }


def _flow(n):
    # Use a fixed timestamp to ensure two _flow(n) calls produce identical hashes
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc) - timedelta(days=n)
    ts_str = ts.isoformat()
    return {
        "src": {"workload": {"href": f"/orgs/1/workloads/src{n}"}},
        "dst": {"workload": {"href": f"/orgs/1/workloads/dst{n}"}},
        "service": {"port": 443, "proto": 6},
        "policy_decision": "allowed",
        "first_detected": ts_str,
        "last_detected": ts_str,
        "num_connections": 1,
        "flow_direction": "outbound",
    }


def test_backfill_events_inserts_rows(session_factory, tmp_path):
    from src.pce_cache.backfill import BackfillRunner
    events = [_event(5), _event(4), _event(3)]
    api = _make_mock_api_events(events)
    now = datetime.now(timezone.utc)
    runner = BackfillRunner(api, session_factory, rate_limit_per_minute=400)
    result = runner.run_events(now - timedelta(days=7), now)
    assert result.inserted == 3
    with session_factory() as s:
        count = s.execute(select(PceEvent)).scalars().all()
    assert len(count) == 3


def test_backfill_events_deduplicates(session_factory, tmp_path):
    from src.pce_cache.backfill import BackfillRunner
    events = [_event(5), _event(5)]  # duplicate
    api = _make_mock_api_events(events)
    now = datetime.now(timezone.utc)
    runner = BackfillRunner(api, session_factory, rate_limit_per_minute=400)
    result = runner.run_events(now - timedelta(days=7), now)
    assert result.inserted + result.duplicates == 2
    with session_factory() as s:
        count = s.execute(select(PceEvent)).scalars().all()
    assert len(count) == 1


def test_backfill_events_does_not_advance_watermark(session_factory, tmp_path):
    from src.pce_cache.backfill import BackfillRunner
    from src.pce_cache.watermark import WatermarkStore
    events = [_event(5)]
    api = _make_mock_api_events(events)
    now = datetime.now(timezone.utc)
    runner = BackfillRunner(api, session_factory, rate_limit_per_minute=400)
    runner.run_events(now - timedelta(days=7), now)
    wm = WatermarkStore(session_factory)
    # Watermark for "events" must remain unset (None)
    assert wm.get("events") is None


def test_backfill_traffic_inserts_rows(session_factory, tmp_path):
    from src.pce_cache.backfill import BackfillRunner
    flows = [_flow(5), _flow(4)]
    api = _make_mock_api_traffic(flows)
    now = datetime.now(timezone.utc)
    runner = BackfillRunner(api, session_factory, rate_limit_per_minute=400)
    result = runner.run_traffic(now - timedelta(days=7), now)
    assert result.inserted == 2
    with session_factory() as s:
        count = s.execute(select(PceTrafficFlowRaw)).scalars().all()
    assert len(count) == 2


def test_backfill_result_has_correct_fields(session_factory, tmp_path):
    from src.pce_cache.backfill import BackfillRunner, BackfillResult
    events = [_event(3)]
    api = _make_mock_api_events(events)
    now = datetime.now(timezone.utc)
    runner = BackfillRunner(api, session_factory, rate_limit_per_minute=400)
    result = runner.run_events(now - timedelta(days=7), now)
    assert isinstance(result, BackfillResult)
    assert hasattr(result, "total_rows")
    assert hasattr(result, "inserted")
    assert hasattr(result, "duplicates")
    assert hasattr(result, "elapsed_seconds")
    assert result.total_rows >= result.inserted


def test_backfill_traffic_deduplicates(session_factory, tmp_path):
    from src.pce_cache.backfill import BackfillRunner
    flows = [_flow(5), _flow(5)]  # duplicate (same hash)
    api = _make_mock_api_traffic(flows)
    now = datetime.now(timezone.utc)
    runner = BackfillRunner(api, session_factory, rate_limit_per_minute=400)
    result = runner.run_traffic(now - timedelta(days=7), now)
    assert result.inserted + result.duplicates == 2
    with session_factory() as s:
        count = s.execute(select(PceTrafficFlowRaw)).scalars().all()
    assert len(count) == 1


def test_backfill_traffic_populates_report_json(session_factory, tmp_path):
    """Backfilled raw flows must carry the precomputed report_json like the live
    ingestor, so reports hit the fast path (and the ix_raw_report_json_null
    partial-index invariant in schema.py holds)."""
    import orjson
    from src.pce_cache.backfill import BackfillRunner
    flows = [_flow(5)]
    api = _make_mock_api_traffic(flows)
    now = datetime.now(timezone.utc)
    runner = BackfillRunner(api, session_factory, rate_limit_per_minute=400)
    runner.run_traffic(now - timedelta(days=7), now)
    with session_factory() as s:
        row = s.execute(select(PceTrafficFlowRaw)).scalars().one()
    assert row.report_json is not None
    parsed = orjson.loads(row.report_json)
    assert isinstance(parsed, dict) and parsed  # non-empty flatten dict


def test_backfill_empty_api_returns_zero(session_factory, tmp_path):
    from src.pce_cache.backfill import BackfillRunner
    api = _make_mock_api_events([])
    now = datetime.now(timezone.utc)
    runner = BackfillRunner(api, session_factory, rate_limit_per_minute=400)
    result = runner.run_events(now - timedelta(days=7), now)
    assert result.inserted == 0
    assert result.total_rows == 0
