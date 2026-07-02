"""siem_cli.py 互動選單的 DLQ replay/purge 假選單要接上 src/siem/dlq.py 的既有實作。

Regression 對象：`_dlq_bulk`/`_dlq_purge_all` 原本只印出「not implemented」，
點選後不會真的動到資料。修正後應與 CLI click 版（src/cli/siem.py）行為一致。
"""
from __future__ import annotations

import builtins
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import DeadLetter, SiemDispatch
from src.pce_cache.schema import init_schema


def _seq(values):
    it = iter(values)
    return lambda _p="": next(it)


@pytest.fixture
def sf(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'dlq.sqlite'}")
    init_schema(engine)
    return sessionmaker(engine)


@pytest.fixture
def cm(tmp_path):
    """最小 cm stub：_dlq_engine() 只讀 cm.models.pce_cache.db_path。"""
    return SimpleNamespace(models=SimpleNamespace(
        pce_cache=SimpleNamespace(db_path=str(tmp_path / "dlq.sqlite"))
    ))


def _seed(sf, count, dest="dest1", days_old=0):
    ts = datetime.now(timezone.utc) - timedelta(days=days_old)
    with sf.begin() as s:
        for i in range(count):
            s.add(DeadLetter(
                source_table="pce_events", source_id=i, destination=dest,
                retries=5, last_error="fail", payload_preview="...",
                quarantined_at=ts,
            ))


def test_dlq_bulk_replay_wires_to_replay_ids(sf, cm, capsys):
    from src.siem_cli import _dlq_bulk
    _seed(sf, count=2)
    with sf() as s:
        ids = [e.id for e in s.execute(select(DeadLetter)).scalars().all()]

    with patch.object(builtins, "input", _seq([",".join(str(i) for i in ids)])):
        _dlq_bulk(cm, action="replay")

    with sf() as s:
        assert s.execute(select(DeadLetter)).scalars().all() == []
        dispatch_rows = s.execute(select(SiemDispatch)).scalars().all()
    assert len(dispatch_rows) == 2
    assert all(r.status == "pending" for r in dispatch_rows)
    assert "replayed" in capsys.readouterr().out


def test_dlq_bulk_purge_deletes_only_selected_ids(sf, cm, capsys):
    from src.siem_cli import _dlq_bulk
    _seed(sf, count=3)
    with sf() as s:
        ids = [e.id for e in s.execute(select(DeadLetter)).scalars().all()]
    to_purge, to_keep = ids[:2], ids[2:]

    with patch.object(builtins, "input", _seq([",".join(str(i) for i in to_purge)])):
        _dlq_bulk(cm, action="purge")

    with sf() as s:
        remaining = [e.id for e in s.execute(select(DeadLetter)).scalars().all()]
    assert remaining == to_keep
    assert "purged 2 entries" in capsys.readouterr().out


def test_dlq_bulk_empty_input_is_noop(sf, cm, capsys):
    """空白輸入應直接返回，不呼叫任何 dlq 方法（沿用原本的早退邏輯）。"""
    from src.siem_cli import _dlq_bulk
    _seed(sf, count=1)
    with patch.object(builtins, "input", _seq([""])):
        _dlq_bulk(cm, action="replay")
    with sf() as s:
        assert len(s.execute(select(DeadLetter)).scalars().all()) == 1


def test_dlq_purge_all_wires_to_purge(sf, cm, capsys):
    from src.siem_cli import _dlq_purge_all
    _seed(sf, count=2, dest="dest1")
    _seed(sf, count=1, dest="dest2")

    with patch.object(builtins, "input", _seq(["dest1", "dest1"])):
        _dlq_purge_all(cm)

    with sf() as s:
        remaining = s.execute(select(DeadLetter)).scalars().all()
    assert len(remaining) == 1
    assert remaining[0].destination == "dest2"
    assert "purged 2 entries for dest1" in capsys.readouterr().out


def test_dlq_purge_all_cancelled_on_mismatch(sf, cm, capsys):
    from src.siem_cli import _dlq_purge_all
    _seed(sf, count=2, dest="dest1")

    with patch.object(builtins, "input", _seq(["dest1", "wrong"])):
        _dlq_purge_all(cm)

    with sf() as s:
        assert len(s.execute(select(DeadLetter)).scalars().all()) == 2
    assert "cancelled" in capsys.readouterr().out
