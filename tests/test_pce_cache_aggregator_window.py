from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import PceTrafficFlowAgg, PceTrafficFlowRaw


@pytest.fixture
def session_factory(tmp_path):
    from src.pce_cache.schema import init_schema
    engine = create_engine(f"sqlite:///{tmp_path / 'agg.sqlite'}")
    init_schema(engine)
    return sessionmaker(engine)


def _raw(i, ts):
    return PceTrafficFlowRaw(
        flow_hash=f"agg-h{i}", src_ip="1.1.1.1", dst_ip="2.2.2.2",
        port=80, protocol="tcp", action="allowed", flow_count=1,
        bytes_in=1, bytes_out=1,
        first_detected=ts, last_detected=ts, ingested_at=ts, raw_json="{}")


def _bucket_days(sf):
    with sf() as s:
        return sorted(s.execute(select(PceTrafficFlowAgg.bucket_day)).scalars().all())


def test_bootstrap_full_scan_when_agg_empty(session_factory):
    from src.pce_cache.aggregator import TrafficAggregator
    old = datetime.now(timezone.utc) - timedelta(days=10)
    with session_factory.begin() as s:
        s.add(_raw(1, old))
    TrafficAggregator(session_factory).run_once()
    assert len(_bucket_days(session_factory)) == 1  # 視窗外的舊列也被聚合


def test_incremental_window_skips_old_raw(session_factory):
    from src.pce_cache.aggregator import TrafficAggregator
    agg = TrafficAggregator(session_factory)
    now = datetime.now(timezone.utc)
    with session_factory.begin() as s:
        s.add(_raw(1, now))
    agg.run_once()  # agg 已非空
    with session_factory.begin() as s:
        s.add(_raw(2, now - timedelta(days=10)))
    agg.run_once()  # 視窗外舊列不觸發新 bucket
    assert len(_bucket_days(session_factory)) == 1


def test_full_flag_forces_whole_table(session_factory):
    from src.pce_cache.aggregator import TrafficAggregator
    agg = TrafficAggregator(session_factory)
    now = datetime.now(timezone.utc)
    with session_factory.begin() as s:
        s.add(_raw(1, now))
    agg.run_once()
    with session_factory.begin() as s:
        s.add(_raw(2, now - timedelta(days=10)))
    agg.run_once(full=True)
    assert len(_bucket_days(session_factory)) == 2
