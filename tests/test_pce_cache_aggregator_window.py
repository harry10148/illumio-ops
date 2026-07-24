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


def test_backfilled_old_days_aggregated_without_full_flag(session_factory):
    """Backfill 情境：raw 列 ingested_at=now（新進）但 last_detected 在數週前。
    牆鐘視窗與 max_agg_day 錨點都照不到——aggregator 必須自我防護（游標式
    偵測新進舊日期列），不能依賴呼叫端記得帶 full=True（web.py 有帶、CLI
    沒帶，2026-07-25 審查）。"""
    from src.pce_cache.aggregator import TrafficAggregator
    from src.pce_cache.models import PceTrafficFlowRaw
    agg = TrafficAggregator(session_factory)
    now = datetime.now(timezone.utc)
    with session_factory.begin() as s:
        s.add(_raw(1, now))
    agg.run_once()  # agg 非空、游標推進到 now
    # 模擬 backfill：老日期資料、ingested_at = 現在
    old_day = now - timedelta(days=30)
    with session_factory.begin() as s:
        s.add(PceTrafficFlowRaw(
            flow_hash="agg-backfill", src_ip="1.1.1.1", dst_ip="2.2.2.2",
            port=80, protocol="tcp", action="allowed", flow_count=1,
            bytes_in=1, bytes_out=1,
            first_detected=old_day, last_detected=old_day,
            ingested_at=datetime.now(timezone.utc), raw_json="{}"))
    agg.run_once()  # 增量（排程預設）——不帶 full=True
    assert len(_bucket_days(session_factory)) == 2
