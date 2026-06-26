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


def test_cover_state_partial_when_cache_empty_and_range_in_retention(session_factory):
    """Empty cache within retention window → partial (earliest is None branch)."""
    now = datetime.now(timezone.utc)
    rd = CacheReader(session_factory, events_retention_days=90, traffic_raw_retention_days=7)
    assert rd.cover_state("events", now - timedelta(hours=1), now) == "partial"


def test_cover_state_full_when_backfill_old_data_with_recent_ingested_at(session_factory):
    """Regression: backfill writes old `timestamp` but recent `ingested_at`.
    cover_state must judge by data timestamp so request whose start ≥ data
    start returns 'full', not 'partial'.
    """
    now = datetime.now(timezone.utc)
    data_ts = now - timedelta(days=5)        # event happened 5 days ago
    ingest_ts = now - timedelta(hours=1)     # but was backfilled an hour ago
    with session_factory.begin() as s:
        s.add(PceEvent(
            pce_href="/orgs/1/events/backfill-1",
            pce_event_id="backfill-1",
            timestamp=data_ts,
            event_type="policy.update",
            severity="info",
            status="success",
            pce_fqdn="pce.example.com",
            raw_json='{"event_type": "policy.update"}',
            ingested_at=ingest_ts,
        ))
    rd = CacheReader(session_factory, events_retention_days=90, traffic_raw_retention_days=7)
    # Request 4 days back — start (4d) ≥ data_ts (5d ago); cache covers it
    assert rd.cover_state("events", now - timedelta(days=4), now) == "full"


def test_cover_state_full_for_backfilled_window_beyond_retention_cutoff(session_factory):
    """Regression: retention deletes raw flows by ingested_at, so a flow
    backfilled with an OLD last_detected (beyond the 7-day raw cutoff) still
    physically lives in the cache. cover_state must judge coverage by the
    actual stored data extent, not the retention-day cutoff — otherwise the
    old window is wrongly reported 'miss' and the cache is bypassed.
    """
    now = datetime.now(timezone.utc)
    old_last = now - timedelta(days=30)          # 30d ago — past the 7d cutoff
    with session_factory.begin() as s:
        s.add(PceTrafficFlowRaw(
            flow_hash="backfilled-old",
            first_detected=old_last, last_detected=old_last,
            src_ip="1.2.3.4", dst_ip="5.6.7.8", port=443, protocol="tcp",
            action="allowed", flow_count=1, bytes_in=0, bytes_out=0,
            raw_json="{}", ingested_at=now,       # backfilled just now
        ))
    rd = CacheReader(session_factory, events_retention_days=90, traffic_raw_retention_days=7)
    # Old window [30d, 20d] is fully spanned by the stored data → 'full',
    # not 'miss' (the day-cutoff would have short-circuited to 'miss').
    assert rd.cover_state("traffic", old_last, now - timedelta(days=20)) == "full"
