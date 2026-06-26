from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import PceTrafficFlowAgg, PceTrafficFlowRaw


@pytest.fixture
def session_factory(tmp_path):
    from src.pce_cache.schema import init_schema
    engine = create_engine(f"sqlite:///{tmp_path / 'c.sqlite'}")
    init_schema(engine)
    return sessionmaker(engine)


def _seed_raw(sf, count, action="blocked"):
    now = datetime.now(timezone.utc)
    with sf.begin() as s:
        for i in range(count):
            s.add(PceTrafficFlowRaw(
                flow_hash=f"h-{action}-{i}",
                first_detected=now, last_detected=now,
                src_ip="10.0.0.1", src_workload="web",
                dst_ip="10.0.0.2", dst_workload="db",
                port=443, protocol="tcp", action=action,
                flow_count=1, bytes_in=100, bytes_out=200,
                raw_json="{}", ingested_at=now,
            ))


def test_aggregator_groups_by_day_workload_pair(session_factory):
    from src.pce_cache.aggregator import TrafficAggregator
    _seed_raw(session_factory, count=50, action="blocked")
    agg = TrafficAggregator(session_factory)
    inserted = agg.run_once()
    assert inserted >= 1
    with session_factory() as s:
        rows = s.execute(select(PceTrafficFlowAgg)).scalars().all()
    assert len(rows) == 1
    assert rows[0].flow_count == 50
    assert rows[0].bytes_total == 50 * (100 + 200)


def test_aggregator_is_idempotent(session_factory):
    from src.pce_cache.aggregator import TrafficAggregator
    _seed_raw(session_factory, count=5)
    agg = TrafficAggregator(session_factory)
    agg.run_once()
    agg.run_once()  # second run must not double-count
    with session_factory() as s:
        rows = s.execute(select(PceTrafficFlowAgg)).scalars().all()
    assert len(rows) == 1
    assert rows[0].flow_count == 5


def test_aggregator_dedups_null_workload_rows(session_factory):
    """Regression: rows with NULL src/dst_workload (unmanaged endpoints) must
    still dedup. SQLite treats NULL as DISTINCT in the unique index, so the
    aggregator coalesces NULL→'' — otherwise every run re-inserts them and the
    agg table balloons (observed 4.5M rows in prod)."""
    from src.pce_cache.aggregator import TrafficAggregator
    now = datetime.now(timezone.utc)
    with session_factory.begin() as s:
        for i in range(5):  # same group, NULL src_workload (unmanaged scanner)
            s.add(PceTrafficFlowRaw(
                flow_hash=f"null-{i}", first_detected=now, last_detected=now,
                src_ip="172.16.15.142", src_workload=None,
                dst_ip="10.0.0.9", dst_workload="db",
                port=443, protocol="tcp", action="potentially_blocked",
                flow_count=1, bytes_in=0, bytes_out=0, raw_json="{}", ingested_at=now,
            ))
    agg = TrafficAggregator(session_factory)
    agg.run_once()
    agg.run_once()  # second run must NOT duplicate
    with session_factory() as s:
        rows = s.execute(select(PceTrafficFlowAgg)).scalars().all()
    null_group = [r for r in rows if r.dst_workload == "db" and r.port == 443]
    assert len(null_group) == 1, f"expected 1 deduped row, got {len(null_group)}"
    assert null_group[0].src_workload == ""        # NULL coalesced to sentinel
    assert null_group[0].flow_count == 5           # summed


def test_aggregator_does_not_shrink_bucket_when_raw_rows_expire(session_factory):
    """Regression: raw has 7-day retention, agg keeps 90 days. When retention
    deletes a bucket's raw rows, re-aggregation recomputes from the surviving
    sliver — a plain overwrite would corrupt the stored historical sum downward.
    MAX(existing, recomputed) must keep the full value."""
    from sqlalchemy import delete
    from src.pce_cache.aggregator import TrafficAggregator

    _seed_raw(session_factory, count=50, action="blocked")
    agg = TrafficAggregator(session_factory)
    agg.run_once()
    with session_factory() as s:
        rows = s.execute(select(PceTrafficFlowAgg)).scalars().all()
    assert len(rows) == 1
    assert rows[0].flow_count == 50
    full_bytes = rows[0].bytes_total

    # Simulate retention sweeping away most of the bucket's raw rows (keep 10/50).
    survivors = [f"h-blocked-{i}" for i in range(10)]
    with session_factory.begin() as s:
        s.execute(delete(PceTrafficFlowRaw).where(
            PceTrafficFlowRaw.flow_hash.notin_(survivors)))

    # Re-aggregate from the surviving sliver: stored value must NOT shrink.
    agg.run_once()
    with session_factory() as s:
        rows = s.execute(select(PceTrafficFlowAgg)).scalars().all()
    assert len(rows) == 1
    assert rows[0].flow_count == 50, "aged bucket corrupted downward by re-aggregation"
    assert rows[0].bytes_total == full_bytes
