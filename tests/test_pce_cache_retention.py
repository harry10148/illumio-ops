from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import (
    PceEvent, PceTrafficFlowRaw, PceTrafficFlowAgg, DeadLetter, SiemDispatch
)


@pytest.fixture
def session_factory(tmp_path):
    from src.pce_cache.schema import init_schema
    engine = create_engine(f"sqlite:///{tmp_path / 'c.sqlite'}")
    init_schema(engine)
    return sessionmaker(engine)


def _old(days=100):
    return datetime.now(timezone.utc) - timedelta(days=days)


def _now():
    return datetime.now(timezone.utc)


def _seed_events(sf, old_count, new_count):
    with sf.begin() as s:
        for i in range(old_count):
            s.add(PceEvent(
                pce_href=f"/old/ev/{i}", pce_event_id=f"old-{i}",
                timestamp=_old(), event_type="test", severity="info",
                status="success", pce_fqdn="pce.test", raw_json="{}",
                ingested_at=_old(),
            ))
        for i in range(new_count):
            s.add(PceEvent(
                pce_href=f"/new/ev/{i}", pce_event_id=f"new-{i}",
                timestamp=_now(), event_type="test", severity="info",
                status="success", pce_fqdn="pce.test", raw_json="{}",
                ingested_at=_now(),
            ))


def _seed_raw_flows(sf, old_count, new_count):
    with sf.begin() as s:
        for i in range(old_count):
            s.add(PceTrafficFlowRaw(
                flow_hash=f"old-raw-{i}", first_detected=_old(), last_detected=_old(),
                src_ip="10.0.0.1", dst_ip="10.0.0.2", port=443, protocol="tcp",
                action="blocked", flow_count=1, bytes_in=0, bytes_out=0,
                raw_json="{}", ingested_at=_old(),
            ))
        for i in range(new_count):
            s.add(PceTrafficFlowRaw(
                flow_hash=f"new-raw-{i}", first_detected=_now(), last_detected=_now(),
                src_ip="10.0.0.1", dst_ip="10.0.0.2", port=443, protocol="tcp",
                action="blocked", flow_count=1, bytes_in=0, bytes_out=0,
                raw_json="{}", ingested_at=_now(),
            ))


def _seed_dlq(sf, old_count, new_count):
    with sf.begin() as s:
        for i in range(old_count):
            s.add(DeadLetter(
                source_table="pce_events", source_id=i, destination="dest1",
                retries=10, last_error="fail", payload_preview="...",
                quarantined_at=_old(),
            ))
        for i in range(new_count):
            s.add(DeadLetter(
                source_table="pce_events", source_id=1000+i, destination="dest1",
                retries=10, last_error="fail", payload_preview="...",
                quarantined_at=_now(),
            ))


def test_retention_purges_old_events(session_factory):
    from src.pce_cache.retention import RetentionWorker
    _seed_events(session_factory, old_count=5, new_count=3)
    worker = RetentionWorker(session_factory)
    deleted = worker.run_once(events_days=30, traffic_raw_days=7, traffic_agg_days=90, dlq_days=30)
    assert deleted["events"] == 5
    with session_factory() as s:
        remaining = s.execute(select(PceEvent)).scalars().all()
    assert len(remaining) == 3


def test_retention_purges_old_raw_flows(session_factory):
    from src.pce_cache.retention import RetentionWorker
    _seed_raw_flows(session_factory, old_count=10, new_count=2)
    worker = RetentionWorker(session_factory)
    deleted = worker.run_once(events_days=30, traffic_raw_days=7, traffic_agg_days=90, dlq_days=30)
    assert deleted["traffic_raw"] == 10
    with session_factory() as s:
        remaining = s.execute(select(PceTrafficFlowRaw)).scalars().all()
    assert len(remaining) == 2


def test_retention_purges_old_dlq(session_factory):
    from src.pce_cache.retention import RetentionWorker
    _seed_dlq(session_factory, old_count=4, new_count=1)
    worker = RetentionWorker(session_factory)
    deleted = worker.run_once(events_days=30, traffic_raw_days=7, traffic_agg_days=90, dlq_days=30)
    assert deleted["dead_letter"] == 4
    with session_factory() as s:
        remaining = s.execute(select(DeadLetter)).scalars().all()
    assert len(remaining) == 1


def _seed_dispatch(sf, sent_old, sent_new, pending, failed):
    with sf.begin() as s:
        for i in range(sent_old):
            s.add(SiemDispatch(
                source_table="pce_traffic_flows_raw", source_id=i, destination="splunk",
                status="sent", retries=0, queued_at=_old(), sent_at=_old(),
            ))
        for i in range(sent_new):
            s.add(SiemDispatch(
                source_table="pce_traffic_flows_raw", source_id=1000 + i, destination="splunk",
                status="sent", retries=0, queued_at=_now(), sent_at=_now(),
            ))
        for i in range(pending):
            s.add(SiemDispatch(
                source_table="pce_traffic_flows_raw", source_id=2000 + i, destination="splunk",
                status="pending", retries=0, queued_at=_old(), sent_at=None,
            ))
        for i in range(failed):
            s.add(SiemDispatch(
                source_table="pce_traffic_flows_raw", source_id=3000 + i, destination="splunk",
                status="failed", retries=5, queued_at=_old(), sent_at=None,
            ))


def test_retention_purges_old_sent_siem_dispatch(session_factory):
    _seed_dispatch(session_factory, sent_old=6, sent_new=2, pending=3, failed=1)
    from src.pce_cache.retention import RetentionWorker
    worker = RetentionWorker(session_factory)
    deleted = worker.run_once(events_days=90, traffic_raw_days=7, traffic_agg_days=90,
                              dlq_days=30, dispatch_days=14)
    assert deleted["siem_dispatch"] == 6
    with session_factory() as s:
        remaining = s.execute(select(SiemDispatch)).scalars().all()
    # 2 recent 'sent' + 3 pending + 1 failed survive; 6 aged 'sent' purged
    assert len(remaining) == 6
    assert sorted(r.status for r in remaining) == \
        ["failed", "pending", "pending", "pending", "sent", "sent"]


def test_retention_keeps_pending_and_failed_siem_dispatch(session_factory):
    """Only delivered ('sent') rows past the cutoff are purged. Pending/failed
    rows (retry/DLQ candidates, NULL sent_at) must never be deleted by age."""
    _seed_dispatch(session_factory, sent_old=0, sent_new=0, pending=4, failed=2)
    from src.pce_cache.retention import RetentionWorker
    worker = RetentionWorker(session_factory)
    deleted = worker.run_once(dispatch_days=1)
    assert deleted["siem_dispatch"] == 0
    with session_factory() as s:
        assert len(s.execute(select(SiemDispatch)).scalars().all()) == 6
