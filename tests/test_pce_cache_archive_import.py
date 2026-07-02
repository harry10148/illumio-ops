import gzip
import os
from datetime import date, datetime, timezone

import orjson
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.pce_cache.schema import init_schema
from src.pce_cache.models import PceTrafficFlowRaw


@pytest.fixture
def sf(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'review.sqlite'}")
    init_schema(engine)
    return sessionmaker(engine)


@pytest.fixture
def archive_dir(tmp_path):
    d = tmp_path / "archive"
    d.mkdir()
    return str(d)


def _traffic_line(flow_hash, event_day, raw):
    return orjson.dumps({
        "event_time": f"{event_day}T12:00:00+00:00",
        "ingested_at": f"{event_day}T12:00:00+00:00",
        "flow_hash": flow_hash,
        "src_ip": "10.0.0.1", "src_workload": "/w/web",
        "dst_ip": "10.0.0.2", "dst_workload": "/w/db",
        "port": 443, "protocol": "tcp", "action": "blocked",
        "flow_count": 1, "bytes_in": 100, "bytes_out": 200,
        "raw": raw,
    })


def _write(archive_dir, name, lines):
    path = os.path.join(archive_dir, name)
    opener = gzip.open if name.endswith(".gz") else open
    with opener(path, "wb") as fh:
        for ln in lines:
            fh.write(ln + b"\n")


def _rows(sf):
    with sf() as s:
        return s.execute(select(PceTrafficFlowRaw)).scalars().all()


def test_import_restores_rows_with_fidelity(sf, archive_dir):
    from src.pce_cache.archive_import import ArchiveImporter
    raw = {"src_ip": "10.0.0.1", "dst_ip": "10.0.0.2",
           "first_detected": "2026-06-30T11:00:00+00:00", "port": 443, "action": "blocked"}
    _write(archive_dir, "traffic-2026-06-30.jsonl", [_traffic_line("h1", "2026-06-30", raw)])

    res = ArchiveImporter(archive_dir, sf).import_range(date(2026, 6, 1), date(2026, 6, 30))
    assert res["rows"] == 1 and res["files"] == 1
    rows = _rows(sf)
    assert len(rows) == 1
    r = rows[0]
    assert r.flow_hash == "h1"
    assert r.port == 443 and r.action == "blocked"
    assert orjson.loads(r.raw_json) == raw            # raw 保真
    assert r.report_json is not None                  # 已補 report_json
    # first_detected 從 raw 回推（11:00），last_detected = event_time（12:00）
    assert r.first_detected.replace(tzinfo=timezone.utc).hour == 11
    assert r.last_detected.replace(tzinfo=timezone.utc).hour == 12


def test_import_reads_gzip_and_filters_by_range(sf, archive_dir):
    from src.pce_cache.archive_import import ArchiveImporter
    raw = {"src_ip": "10.0.0.1", "dst_ip": "10.0.0.2", "port": 80, "action": "allowed"}
    _write(archive_dir, "traffic-2026-06-15.jsonl.gz", [_traffic_line("g1", "2026-06-15", raw)])
    _write(archive_dir, "traffic-2026-05-01.jsonl", [_traffic_line("out", "2026-05-01", raw)])

    res = ArchiveImporter(archive_dir, sf).import_range(date(2026, 6, 1), date(2026, 6, 30))
    assert res["rows"] == 1                            # 只匯入範圍內的 .gz
    assert {r.flow_hash for r in _rows(sf)} == {"g1"}


def test_import_skips_null_raw_and_dedups(sf, archive_dir):
    from src.pce_cache.archive_import import ArchiveImporter
    raw = {"src_ip": "1.1.1.1", "dst_ip": "2.2.2.2", "port": 22, "action": "allowed"}
    lines = [
        _traffic_line("dup", "2026-06-10", raw),
        _traffic_line("dup", "2026-06-10", raw),          # 同 flow_hash → 去重
        orjson.dumps({"event_time": "2026-06-10T12:00:00+00:00",
                      "ingested_at": "2026-06-10T12:00:00+00:00",
                      "flow_hash": "nullraw", "raw": None}),  # raw=None → skip
    ]
    _write(archive_dir, "traffic-2026-06-10.jsonl", lines)

    res = ArchiveImporter(archive_dir, sf).import_range(date(2026, 6, 1), date(2026, 6, 30))
    assert res["rows"] == 1 and res["skipped"] == 2
    assert {r.flow_hash for r in _rows(sf)} == {"dup"}


def test_import_ignores_non_traffic_files(sf, archive_dir):
    from src.pce_cache.archive_import import ArchiveImporter
    raw = {"src_ip": "1.1.1.1", "dst_ip": "2.2.2.2", "port": 1, "action": "allowed"}
    _write(archive_dir, "audit-2026-06-10.jsonl", [b'{"pce_event_id":"e1"}'])   # audit 不匯入
    _write(archive_dir, "notes.txt", [b"ignore"])
    _write(archive_dir, "traffic-2026-06-10.jsonl", [_traffic_line("t1", "2026-06-10", raw)])

    res = ArchiveImporter(archive_dir, sf).import_range(date(2026, 6, 1), date(2026, 6, 30))
    assert res["rows"] == 1 and res["files"] == 1
    assert {r.flow_hash for r in _rows(sf)} == {"t1"}


from types import SimpleNamespace


def _cfg(tmp_path, archive_dir):
    # review DB 會放在 db_path 同目錄；archive_review_max_days 由 route 用，這裡不需要
    return SimpleNamespace(db_path=str(tmp_path / "cache.sqlite"), archive_dir=archive_dir)


def test_load_review_rebuilds_imports_and_aggregates(tmp_path, archive_dir):
    from src.pce_cache.archive_import import (
        load_archive_review, review_status, review_db_path, review_session_factory)
    from src.pce_cache.models import PceTrafficFlowAgg
    from sqlalchemy import select
    raw = {"src_ip": "10.0.0.1", "dst_ip": "10.0.0.2", "port": 443, "action": "blocked"}
    _write(archive_dir, "traffic-2026-06-20.jsonl", [_traffic_line("a1", "2026-06-20", raw)])
    cfg = _cfg(tmp_path, archive_dir)

    meta = load_archive_review(cfg, date(2026, 6, 1), date(2026, 6, 30))
    assert meta["loaded"] is True and meta["rows"] == 1
    assert os.path.exists(review_db_path(cfg))
    # status 反映 meta
    st = review_status(cfg)
    assert st["loaded"] is True and st["rows"] == 1 and st["start"] == "2026-06-01"
    # 聚合表有列（趨勢圖/KPI 用）
    with review_session_factory(cfg)() as s:
        assert len(s.execute(select(PceTrafficFlowAgg)).scalars().all()) >= 1


def test_load_review_rebuilds_on_second_load(tmp_path, archive_dir):
    from src.pce_cache.archive_import import load_archive_review, review_session_factory
    from src.pce_cache.models import PceTrafficFlowRaw
    from sqlalchemy import select
    raw = {"src_ip": "1.1.1.1", "dst_ip": "2.2.2.2", "port": 1, "action": "allowed"}
    _write(archive_dir, "traffic-2026-06-05.jsonl", [_traffic_line("first", "2026-06-05", raw)])
    _write(archive_dir, "traffic-2026-07-05.jsonl", [_traffic_line("second", "2026-07-05", raw)])
    cfg = _cfg(tmp_path, archive_dir)

    load_archive_review(cfg, date(2026, 6, 1), date(2026, 6, 30))   # 只含 first
    load_archive_review(cfg, date(2026, 7, 1), date(2026, 7, 31))   # 重建後只含 second
    with review_session_factory(cfg)() as s:
        hashes = {r.flow_hash for r in s.execute(select(PceTrafficFlowRaw)).scalars().all()}
    assert hashes == {"second"}   # 前一次載入已被重建清掉


def test_review_status_empty_when_never_loaded(tmp_path, archive_dir):
    from src.pce_cache.archive_import import review_status
    assert review_status(_cfg(tmp_path, archive_dir)) == {"loaded": False}


def test_review_session_factory_uses_nullpool(tmp_path, archive_dir):
    # Task 6 會 per-query 呼叫 review_session_factory；預設 pool（QueuePool）
    # 每次都留住連線池與 FD 直到 GC，長跑程序會累積洩漏。鎖定必須用 NullPool。
    from src.pce_cache.archive_import import review_session_factory
    cfg = _cfg(tmp_path, archive_dir)
    sf = review_session_factory(cfg)
    engine = sf.kw["bind"]            # sessionmaker 綁定的 engine
    assert type(engine.pool).__name__ == "NullPool"
