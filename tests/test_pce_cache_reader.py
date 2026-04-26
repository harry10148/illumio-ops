from datetime import datetime, timedelta, timezone
import json
import hashlib
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.pce_cache.models import PceEvent, PceTrafficFlowRaw
from src.pce_cache.reader import CacheReader


@pytest.fixture
def session_factory(tmp_path):
    from src.pce_cache.schema import init_schema
    engine = create_engine(f"sqlite:///{tmp_path / 'c.sqlite'}")
    init_schema(engine)
    return sessionmaker(engine)


def _seed_event(sf, ts):
    with sf.begin() as s:
        s.add(PceEvent(
            pce_href=f"/orgs/1/events/{ts.isoformat()}",
            pce_event_id=ts.isoformat(),
            timestamp=ts,
            event_type="policy.update",
            severity="info",
            status="success",
            pce_fqdn="pce.example.com",
            raw_json=json.dumps({"event_type": "policy.update"}),
            ingested_at=ts,
        ))


def test_cover_state_full_when_range_in_retention(session_factory):
    now = datetime.now(timezone.utc)
    _seed_event(session_factory, now - timedelta(days=2))  # seed at range start
    rd = CacheReader(session_factory, events_retention_days=90, traffic_raw_retention_days=7)
    assert rd.cover_state("events", now - timedelta(days=2), now) == "full"


def test_cover_state_partial_when_start_before_cutoff(session_factory):
    now = datetime.now(timezone.utc)
    rd = CacheReader(session_factory, events_retention_days=90, traffic_raw_retention_days=7)
    assert rd.cover_state("events", now - timedelta(days=120), now) == "partial"


def test_cover_state_miss_when_entirely_before_cutoff(session_factory):
    now = datetime.now(timezone.utc)
    rd = CacheReader(session_factory, events_retention_days=90, traffic_raw_retention_days=7)
    assert rd.cover_state("events", now - timedelta(days=200), now - timedelta(days=150)) == "miss"


def test_read_events_returns_dict_rows(session_factory):
    now = datetime.now(timezone.utc)
    _seed_event(session_factory, now - timedelta(hours=1))
    rd = CacheReader(session_factory, events_retention_days=90, traffic_raw_retention_days=7)
    rows = rd.read_events(now - timedelta(hours=2), now)
    assert len(rows) == 1
    assert rows[0]["event_type"] == "policy.update"


def test_read_events_returns_empty_for_miss_range(session_factory):
    now = datetime.now(timezone.utc)
    rd = CacheReader(session_factory, events_retention_days=90, traffic_raw_retention_days=7)
    rows = rd.read_events(now - timedelta(days=200), now - timedelta(days=150))
    assert rows == []


def _seed_flow(sf, ingested_at):
    h = hashlib.sha1(ingested_at.isoformat().encode()).hexdigest()
    with sf.begin() as s:
        s.add(PceTrafficFlowRaw(
            flow_hash=h,
            first_detected=ingested_at,
            last_detected=ingested_at,
            src_ip="1.2.3.4",
            dst_ip="5.6.7.8",
            port=443,
            protocol="TCP",
            action="allowed",
            raw_json='{}',
            ingested_at=ingested_at,
        ))


def test_earliest_ingested_at_returns_min(session_factory):
    now = datetime.now(timezone.utc)
    older = now - timedelta(days=3)
    newer = now - timedelta(days=1)
    _seed_flow(session_factory, older)
    _seed_flow(session_factory, newer)
    rd = CacheReader(session_factory, events_retention_days=90, traffic_raw_retention_days=7)
    result = rd.earliest_ingested_at("traffic")
    assert result is not None
    assert abs((result - older).total_seconds()) < 1


def test_earliest_ingested_at_returns_none_when_empty(session_factory):
    rd = CacheReader(session_factory, events_retention_days=90, traffic_raw_retention_days=7)
    assert rd.earliest_ingested_at("traffic") is None


def test_cover_state_partial_when_start_before_cache_data(session_factory):
    """Fresh cache: data starts at now-1h, but range starts at now-3days → partial."""
    now = datetime.now(timezone.utc)
    _seed_event(session_factory, now - timedelta(hours=1))  # cache only has 1 hour
    rd = CacheReader(session_factory, events_retention_days=90, traffic_raw_retention_days=7)
    # Range starts 3 days ago — entirely within retention window but before any cached data
    assert rd.cover_state("events", now - timedelta(days=3), now) == "partial"
