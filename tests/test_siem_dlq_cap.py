"""DLQ 每目的地上限 dlq_max_per_dest 的實際執行（backlog fix 4）。

設定欄位存在已久但 _quarantine() 從未依它裁剪——本測試釘住：
寫入 DLQ 後若該目的地筆數超過上限，最舊的項目被刪除（ring-buffer 語意），
其他目的地不受影響。
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


def test_quarantine_prunes_oldest_beyond_cap(sf):
    """已有 100 筆（=上限）再進 1 筆 → 最舊的 source_id=0 被刪、總數維持 100，
    新項目存在。"""
    _seed_dlq_staggered(sf, 100)
    d = _make_dispatcher(sf, dlq_max=100)
    d._quarantine(_dispatch_row(sf), payload="p", error="boom")

    with sf() as s:
        rows = s.execute(select(DeadLetter).where(DeadLetter.destination == "dest1")).scalars().all()
    assert len(rows) == 100
    source_ids = {r.source_id for r in rows}
    assert 99999 in source_ids, "新進項目必須保留"
    assert 0 not in source_ids, "最舊項目必須被裁剪"
    assert 1 in source_ids


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
    d._quarantine(_dispatch_row(sf), payload="p", error="boom")

    with sf() as s:
        rows = s.execute(select(DeadLetter).where(DeadLetter.destination == "dest1")).scalars().all()
    assert len(rows) == 11
