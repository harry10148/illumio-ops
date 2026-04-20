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
