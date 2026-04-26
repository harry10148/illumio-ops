"""Phase 14 E2E: cache-first report generation + backfill."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
import json
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def session_factory(tmp_path):
    from src.pce_cache.schema import init_schema
    engine = create_engine(f"sqlite:///{tmp_path / 'e2e.sqlite'}")
    init_schema(engine)
    return sessionmaker(engine)


def _seed_events(sf, n, days_ago_start=1):
    from src.pce_cache.models import PceEvent
    import json
    now = datetime.now(timezone.utc)
    with sf.begin() as s:
        for i in range(n):
            ts = now - timedelta(days=days_ago_start + i)
            s.add(PceEvent(
                pce_href=f"/orgs/1/events/e{i}",
                pce_event_id=f"e{i}",
                timestamp=ts,
                event_type="policy.update",
                severity="info",
                status="success",
                pce_fqdn="pce.example.com",
                raw_json=json.dumps({"event_type": "policy.update", "href": f"/orgs/1/events/e{i}"}),
                ingested_at=ts,
            ))


def test_audit_report_cache_hit_no_api_call(session_factory):
    """AuditGenerator reads from cache (full hit) and does NOT call API."""
    from src.report.audit_generator import AuditGenerator
    from src.pce_cache.reader import CacheReader
    _seed_events(session_factory, 2)  # events at now-1d, now-2d; earliest ≈ now-2d
    api = MagicMock()
    api.get_events.return_value = []
    rd = CacheReader(session_factory, events_retention_days=90, traffic_raw_retention_days=7)
    gen = AuditGenerator(api=api, cache_reader=rd)
    # start at now-36h: safely after earliest (now-2d=now-48h) so cover_state="full"
    # only the now-1d event falls within [now-36h, now]
    start = datetime.now(timezone.utc) - timedelta(hours=36)
    end = datetime.now(timezone.utc)
    events = gen._fetch_events(start, end)
    assert len(events) == 1
    api.get_events.assert_not_called()


def test_audit_report_cache_miss_falls_back_to_api(session_factory):
    """AuditGenerator falls back to API when range is a miss (100+ days ago)."""
    from src.report.audit_generator import AuditGenerator
    from src.pce_cache.reader import CacheReader
    api = MagicMock()
    api.get_events.return_value = [{"event_type": "policy.update"}]
    rd = CacheReader(session_factory, events_retention_days=90, traffic_raw_retention_days=7)
    gen = AuditGenerator(api=api, cache_reader=rd)
    start = datetime.now(timezone.utc) - timedelta(days=150)
    end = datetime.now(timezone.utc) - timedelta(days=120)
    gen._fetch_events(start, end)
    api.get_events.assert_called_once()


def test_backfill_then_cache_hit(session_factory):
    """After backfill, cache reader can serve the data."""
    from src.pce_cache.backfill import BackfillRunner
    from src.pce_cache.reader import CacheReader
    now = datetime.now(timezone.utc)
    events = [
        {
            "href": "/orgs/1/events/backfill1",
            "event_type": "sec_policy.create",
            "severity": "info",
            "status": "success",
            "pce_fqdn": "pce.example.com",
            "timestamp": (now - timedelta(days=5)).isoformat(),
        }
    ]
    api = MagicMock()
    api.get_events.return_value = events
    runner = BackfillRunner(api, session_factory)
    result = runner.run_events(now - timedelta(days=7), now)
    assert result.inserted == 1
    # Now the cache reader can serve it
    rd = CacheReader(session_factory, events_retention_days=90, traffic_raw_retention_days=7)
    rows = rd.read_events(now - timedelta(days=7), now)
    assert len(rows) == 1


def test_report_generator_cache_hit_sets_metadata(session_factory):
    """ReportGenerator cache hit sets data_source='cache' in the result."""
    from src.report.report_generator import ReportGenerator
    from src.pce_cache.reader import CacheReader
    api = MagicMock()
    cache = MagicMock()
    cache.cover_state.return_value = "full"
    cache.read_flows_raw.return_value = []
    cache.read_flows_agg.return_value = []
    gen = ReportGenerator(api=api, cache_reader=cache)
    start = datetime.now(timezone.utc) - timedelta(days=1)
    end = datetime.now(timezone.utc)
    result = gen._fetch_traffic(start, end)
    assert result["source"] == "cache"
