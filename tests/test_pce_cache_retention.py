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


def _set_archiver_cursor(sf, source_table, last_ingested_at):
    from src.pce_cache.models import IngestionCursor
    with sf.begin() as s:
        s.add(IngestionCursor(
            consumer="archiver", source_table=source_table,
            last_ingested_at=last_ingested_at, last_row_id=10**9,
            updated_at=_now(),
        ))


def test_guard_withholds_when_nothing_archived(session_factory):
    """archive_enabled 但沒有 archiver cursor（什麼都還沒 archive）→ 不刪任何 raw flow。"""
    from src.pce_cache.retention import RetentionWorker
    _seed_raw_flows(session_factory, old_count=5, new_count=0)
    worker = RetentionWorker(session_factory)
    deleted = worker.run_once(traffic_raw_days=7, archive_enabled=True)
    assert deleted["traffic_raw"] == 0
    with session_factory() as s:
        from sqlalchemy import select
        assert len(s.execute(select(PceTrafficFlowRaw)).scalars().all()) == 5


def test_guard_deletes_when_archive_caught_up(session_factory):
    """archiver cursor 已覆蓋到現在 → 到期列照常刪除。"""
    from src.pce_cache.retention import RetentionWorker
    _seed_raw_flows(session_factory, old_count=5, new_count=2)
    _set_archiver_cursor(session_factory, "pce_traffic_flows_raw", _now())
    worker = RetentionWorker(session_factory)
    deleted = worker.run_once(traffic_raw_days=7, archive_enabled=True)
    assert deleted["traffic_raw"] == 5  # 5 舊列到期且已 archive → 刪；2 新列未到期


def test_guard_withholds_rows_newer_than_cursor(session_factory):
    """archive 落後：cursor 停在很久以前 → 到期但未 archive 的列不刪。"""
    from src.pce_cache.retention import RetentionWorker
    _seed_raw_flows(session_factory, old_count=5, new_count=0)  # 皆為 100 天前、到期
    _set_archiver_cursor(session_factory, "pce_traffic_flows_raw",
                         _now() - __import__("datetime").timedelta(days=200))
    worker = RetentionWorker(session_factory)
    deleted = worker.run_once(traffic_raw_days=7, archive_enabled=True)
    # cursor(200天前) 比舊列(100天前)還早 → 舊列都在 cursor 之後 → 不刪
    assert deleted["traffic_raw"] == 0


def test_guard_withholds_events_when_nothing_archived(session_factory):
    """archive_enabled 但沒有 pce_events 的 archiver cursor（什麼都還沒 archive）
    → 不刪任何到期 event。既有守門測試只覆蓋 traffic_raw，補一條 pce_events 的最小驗證。"""
    from src.pce_cache.retention import RetentionWorker
    _seed_events(session_factory, old_count=5, new_count=0)
    worker = RetentionWorker(session_factory)
    deleted = worker.run_once(events_days=30, archive_enabled=True)
    assert deleted["events"] == 0
    with session_factory() as s:
        assert len(s.execute(select(PceEvent)).scalars().all()) == 5


def test_guard_off_matches_current_behaviour(session_factory):
    """archive_enabled=False（預設）→ 到期即刪，與現況一致（回歸保護）。"""
    from src.pce_cache.retention import RetentionWorker
    _seed_raw_flows(session_factory, old_count=5, new_count=2)
    worker = RetentionWorker(session_factory)
    deleted = worker.run_once(traffic_raw_days=7)  # 不帶 archive_enabled
    assert deleted["traffic_raw"] == 5


def _mk_raw(i, ingested_at):
    from src.pce_cache.models import PceTrafficFlowRaw
    return PceTrafficFlowRaw(
        flow_hash=f"batch-h{i}", src_ip="10.9.0.1", dst_ip="10.9.0.2",
        port=443, protocol="tcp", action="allowed", flow_count=1,
        bytes_in=0, bytes_out=0,
        first_detected=ingested_at, last_detected=ingested_at,
        ingested_at=ingested_at, raw_json="{}",
    )


def test_retention_deletes_across_multiple_batches(session_factory, monkeypatch):
    from datetime import datetime, timezone, timedelta
    from src.pce_cache.retention import RetentionWorker

    old = datetime.now(timezone.utc) - timedelta(days=30)
    fresh = datetime.now(timezone.utc)
    with session_factory.begin() as s:
        for i in range(25):
            s.add(_mk_raw(i, old))
        s.add(_mk_raw(999, fresh))  # 未到期，不可被刪

    monkeypatch.setattr(RetentionWorker, "_DELETE_BATCH", 10)  # 強迫跨 3 批
    result = RetentionWorker(session_factory).run_once(traffic_raw_days=7)
    assert result["traffic_raw"] == 25

    from sqlalchemy import select, func
    from src.pce_cache.models import PceTrafficFlowRaw
    with session_factory() as s:
        remaining = s.execute(
            select(func.count()).select_from(PceTrafficFlowRaw)).scalar()
    assert remaining == 1


def test_retention_withholds_raw_referenced_by_pending_dispatch(session_factory):
    """到期 raw 列若仍被未送達（pending/failed）的 siem_dispatch 引用，不可刪
    ——dispatcher 送出時才回讀來源列建 payload，先刪會讓補送永久失敗。"""
    from src.pce_cache.retention import RetentionWorker
    _seed_raw_flows(session_factory, old_count=3, new_count=0)
    with session_factory() as s:
        ids = sorted(r.id for r in s.execute(select(PceTrafficFlowRaw)).scalars())
    with session_factory.begin() as s:
        s.add(SiemDispatch(
            source_table="pce_traffic_flows_raw", source_id=ids[0],
            destination="splunk", status="pending", retries=0, queued_at=_old()))
    deleted = RetentionWorker(session_factory).run_once(traffic_raw_days=7)
    assert deleted["traffic_raw"] == 2  # 被引用那筆保留
    with session_factory() as s:
        remaining = [r.id for r in s.execute(select(PceTrafficFlowRaw)).scalars()]
    assert remaining == [ids[0]]


def test_retention_withholds_events_referenced_by_dlq(session_factory):
    """到期 event 若仍被 DLQ 引用（replay 只重新 enqueue 同組 key），不可刪。"""
    from src.pce_cache.retention import RetentionWorker
    _seed_events(session_factory, old_count=3, new_count=0)
    with session_factory() as s:
        ids = sorted(r.id for r in s.execute(select(PceEvent)).scalars())
    with session_factory.begin() as s:
        s.add(DeadLetter(
            source_table="pce_events", source_id=ids[1], destination="dest1",
            retries=10, last_error="down", payload_preview="",
            quarantined_at=_now()))
    deleted = RetentionWorker(session_factory).run_once(events_days=30)
    assert deleted["events"] == 2
    with session_factory() as s:
        remaining = [r.id for r in s.execute(select(PceEvent)).scalars()]
    assert remaining == [ids[1]]


def test_retention_deletes_raw_once_dispatch_sent(session_factory):
    """引用一旦送達（status='sent'）就不再擋刪——防護不可把 retention 永久卡死。"""
    from src.pce_cache.retention import RetentionWorker
    _seed_raw_flows(session_factory, old_count=2, new_count=0)
    with session_factory() as s:
        ids = sorted(r.id for r in s.execute(select(PceTrafficFlowRaw)).scalars())
    with session_factory.begin() as s:
        s.add(SiemDispatch(
            source_table="pce_traffic_flows_raw", source_id=ids[0],
            destination="splunk", status="sent", retries=0,
            queued_at=_old(), sent_at=_old()))
    deleted = RetentionWorker(session_factory).run_once(traffic_raw_days=7)
    assert deleted["traffic_raw"] == 2  # sent 引用不擋刪
