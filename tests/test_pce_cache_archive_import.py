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
