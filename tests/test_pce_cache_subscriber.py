# tests/test_pce_cache_subscriber.py
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import PceEvent


@pytest.fixture
def session_factory(tmp_path):
    from src.pce_cache.schema import init_schema
    engine = create_engine(f"sqlite:///{tmp_path/'c.sqlite'}")
    init_schema(engine)
    return sessionmaker(engine)


def _seed(sf, uuid, ingested_at):
    with sf.begin() as s:
        s.add(PceEvent(
            pce_href=f"/orgs/1/events/{uuid}",
            pce_event_id=uuid, timestamp=ingested_at,
            event_type="policy.update", severity="info", status="success",
            pce_fqdn="pce.example.com", raw_json="{}", ingested_at=ingested_at,
        ))


def test_first_poll_returns_all_rows(session_factory):
    from src.pce_cache.subscriber import CacheSubscriber
    _seed(session_factory, "a", datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc))
    _seed(session_factory, "b", datetime(2026, 4, 19, 10, 1, tzinfo=timezone.utc))
    sub = CacheSubscriber(session_factory, consumer="analyzer", source_table="pce_events")
    rows = sub.poll_new_rows()
    assert len(rows) == 2


def test_second_poll_returns_only_new_rows(session_factory):
    from src.pce_cache.subscriber import CacheSubscriber
    _seed(session_factory, "a", datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc))
    sub = CacheSubscriber(session_factory, consumer="analyzer", source_table="pce_events")
    assert len(sub.poll_new_rows()) == 1
    assert len(sub.poll_new_rows()) == 0
    _seed(session_factory, "b", datetime(2026, 4, 19, 10, 1, tzinfo=timezone.utc))
    assert len(sub.poll_new_rows()) == 1


def test_cursor_persists_across_subscriber_restart(session_factory):
    from src.pce_cache.subscriber import CacheSubscriber
    _seed(session_factory, "a", datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc))
    CacheSubscriber(session_factory, "analyzer", "pce_events").poll_new_rows()
    # Fresh subscriber instance should not re-read "a"
    assert len(CacheSubscriber(session_factory, "analyzer", "pce_events")
              .poll_new_rows()) == 0


def test_independent_consumers_have_independent_cursors(session_factory):
    from src.pce_cache.subscriber import CacheSubscriber
    _seed(session_factory, "a", datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc))
    CacheSubscriber(session_factory, "analyzer", "pce_events").poll_new_rows()
    # Other consumer is still at zero — reads everything
    assert len(CacheSubscriber(session_factory, "exporter", "pce_events")
              .poll_new_rows()) == 1


def test_processor_failure_does_not_advance_cursor(session_factory):
    """At-least-once: when the processor callback raises, the cursor must NOT
    advance, so the same rows are re-delivered on the next poll instead of being
    silently skipped on consumer failure."""
    from src.pce_cache.subscriber import CacheSubscriber
    _seed(session_factory, "a", datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc))
    sub = CacheSubscriber(session_factory, "analyzer", "pce_events")

    def boom(rows):
        raise RuntimeError("consumer crashed")

    with pytest.raises(RuntimeError):
        sub.poll_new_rows(processor=boom)
    # Cursor stayed put → row still pending on the next (plain) poll.
    rows = sub.poll_new_rows()
    assert len(rows) == 1
    assert rows[0]["pce_event_id"] == "a"


def test_processor_success_advances_cursor(session_factory):
    """When the processor returns cleanly the batch is acknowledged and the
    cursor advances, so the next poll is empty."""
    from src.pce_cache.subscriber import CacheSubscriber
    _seed(session_factory, "a", datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc))
    sub = CacheSubscriber(session_factory, "analyzer", "pce_events")
    seen = []
    out = sub.poll_new_rows(processor=seen.extend)
    assert len(out) == 1 and len(seen) == 1
    assert sub.poll_new_rows() == []


def test_subscriber_rereads_row_after_ingested_at_bump(session_factory):
    """F6 副作用鎖定：ingest 端 re-pull 一筆既有 flow 會把 ingested_at bump
    到本次 ingest 時間（見 ingestor_traffic.py）。CacheSubscriber 的游標同樣
    依 (ingested_at, id) 前進，所以已經讀過這筆列的 subscriber 會在下一次
    poll 重新讀到它——這是 at-least-once 語意本就允許、預期中的行為（並非
    需要修的 bug），這裡明文鎖定，避免日後被誤當成迴歸修掉。"""
    from src.pce_cache.subscriber import CacheSubscriber
    from src.pce_cache.models import PceTrafficFlowRaw

    def _seed_flow(ingested_at):
        with session_factory.begin() as s:
            s.add(PceTrafficFlowRaw(
                flow_hash="bump1", src_ip="10.0.0.1", src_workload="web",
                dst_ip="10.0.0.2", dst_workload="db", port=443, protocol="tcp",
                action="blocked", flow_count=1, bytes_in=100, bytes_out=200,
                first_detected=datetime(2026, 4, 19, 9, 0, tzinfo=timezone.utc),
                last_detected=datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc),
                raw_json="{}", ingested_at=ingested_at,
            ))

    _seed_flow(datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc))
    sub = CacheSubscriber(session_factory, "analyzer", "pce_traffic_flows_raw")
    assert len(sub.poll_new_rows()) == 1
    assert sub.poll_new_rows() == []   # 沒有新變化時，如常不重讀

    # 模擬 re-pull：同一列（flow_hash 唯一，upsert 更新既有列）的 ingested_at
    # 被 bump 到更晚的時間。
    with session_factory.begin() as s:
        row = s.execute(select(PceTrafficFlowRaw)).scalar_one()
        row.ingested_at = datetime(2026, 4, 19, 10, 5, tzinfo=timezone.utc)

    rows = sub.poll_new_rows()
    assert len(rows) == 1   # bump 後預期會重讀，非資料遺失或迴歸
    assert rows[0]["flow_hash"] == "bump1"


def test_ties_on_ingested_at_broken_by_row_id(session_factory):
    from src.pce_cache.subscriber import CacheSubscriber
    same_ts = datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc)
    _seed(session_factory, "a", same_ts)
    _seed(session_factory, "b", same_ts)  # same ingested_at, different id
    sub = CacheSubscriber(session_factory, "analyzer", "pce_events")
    rows = sub.poll_new_rows(limit=1)
    assert len(rows) == 1
    rows2 = sub.poll_new_rows(limit=1)
    assert len(rows2) == 1
    assert rows[0]["pce_event_id"] != rows2[0]["pce_event_id"]
