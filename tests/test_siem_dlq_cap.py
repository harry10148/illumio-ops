"""DLQ 每目的地上限 dlq_max_per_dest 的實際執行。

舊版是 ring buffer：滿了就刪最舊的 DLQ 項目，那些記錄從此找不回來。現在
DLQ 滿了就不再收新項目——該列維持 pending、以最長退避重試，資料不遺失；
DLQ 本身仍維持在上限內，其他目的地不受影響。
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import DeadLetter, SiemDispatch
from src.siem.dispatcher import DestinationDispatcher


@pytest.fixture
def sf(tmp_path):
    from src.pce_cache.schema import init_schema
    engine = create_engine(f"sqlite:///{tmp_path / 'c.sqlite'}")
    init_schema(engine)
    return sessionmaker(engine)


def _make_dispatcher(sf, dlq_max):
    from unittest.mock import MagicMock
    return DestinationDispatcher(
        name="dest1",
        session_factory=sf,
        formatter=MagicMock(),
        transport=MagicMock(),
        max_retries=1,
        batch_size=10,
        dlq_max=dlq_max,
    )


def _seed_dlq_staggered(sf, count, dest="dest1"):
    base = datetime.now(timezone.utc) - timedelta(hours=1)
    with sf.begin() as s:
        for i in range(count):
            s.add(DeadLetter(
                source_table="pce_events", source_id=i,
                destination=dest, retries=10,
                last_error=f"fail-{i}", payload_preview="...",
                quarantined_at=base + timedelta(seconds=i),
            ))


def _dispatch_row(sf):
    with sf.begin() as s:
        row = SiemDispatch(
            source_table="pce_events", source_id=99999,
            destination="dest1", status="pending", retries=0,
            queued_at=datetime.now(timezone.utc),
        )
        s.add(row)
        s.flush()
        rid = row.id
    with sf() as s:
        return s.get(SiemDispatch, rid)


def test_quarantine_at_cap_keeps_row_queued_and_deletes_nothing(sf):
    """已有 100 筆（=上限）再要進 1 筆 → 不刪任何舊項目、不收新項目；
    該列維持 pending，下次重試排在最長退避之後。"""
    _seed_dlq_staggered(sf, 100)
    d = _make_dispatcher(sf, dlq_max=100)
    row = _dispatch_row(sf)
    assert d._quarantine(row, payload="p", error="boom") is False

    with sf() as s:
        rows = s.execute(select(DeadLetter).where(DeadLetter.destination == "dest1")).scalars().all()
        disp = s.get(SiemDispatch, row.id)
    assert len(rows) == 100
    source_ids = {r.source_id for r in rows}
    assert 0 in source_ids, "既有的 DLQ 項目不得被刪除"
    assert 99999 not in source_ids
    assert disp.status == "pending"
    next_at = disp.next_attempt_at
    if next_at.tzinfo is None:
        next_at = next_at.replace(tzinfo=timezone.utc)
    assert next_at > datetime.now(timezone.utc) + timedelta(minutes=50)


def test_quarantine_cap_scoped_per_destination(sf):
    """裁剪只作用於同目的地：其他目的地的 DLQ 不受影響。"""
    _seed_dlq_staggered(sf, 100, dest="dest1")
    _seed_dlq_staggered(sf, 5, dest="other")
    d = _make_dispatcher(sf, dlq_max=100)
    d._quarantine(_dispatch_row(sf), payload="p", error="boom")

    with sf() as s:
        other = s.execute(select(DeadLetter).where(DeadLetter.destination == "other")).scalars().all()
    assert len(other) == 5


def test_quarantine_under_cap_prunes_nothing(sf):
    _seed_dlq_staggered(sf, 10)
    d = _make_dispatcher(sf, dlq_max=100)
    assert d._quarantine(_dispatch_row(sf), payload="p", error="boom") is True

    with sf() as s:
        rows = s.execute(select(DeadLetter).where(DeadLetter.destination == "dest1")).scalars().all()
    assert len(rows) == 11
