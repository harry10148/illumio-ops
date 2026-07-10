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


def test_incremental_window_anchors_to_agg_progress_after_gap(session_factory):
    """Ingest 中斷恢復場景：agg 最大 bucket 停在 10 天前（中斷前的最後進度），
    ingestor 補拉的 backlog 落在 5 天前——比 now-3d 舊（原本會被牆鐘視窗跳過），
    但比 max_agg_day 新。cutoff 應錨定 max_agg_day - 1d 而非單純 now - 3d，
    否則這批 backlog 永遠不會進聚合表（raw 7 天 retention 到期即永久遺失）。"""
    from src.pce_cache.aggregator import TrafficAggregator
    agg = TrafficAggregator(session_factory)
    now = datetime.now(timezone.utc)
    ten_days_ago = now - timedelta(days=10)
    five_days_ago = now - timedelta(days=5)
    with session_factory.begin() as s:
        s.add(_raw(1, ten_days_ago))
    agg.run_once()  # bootstrap full-scan：agg 從空變非空，max_agg_day 停在 10 天前
    with session_factory.begin() as s:
        s.add(_raw(2, five_days_ago))
    agg.run_once()  # full=False（排程預設值）；backlog 應被補進而非漏掉
    assert len(_bucket_days(session_factory)) == 2


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
