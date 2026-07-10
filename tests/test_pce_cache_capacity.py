from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import PceTrafficFlowRaw


@pytest.fixture
def cache_db(tmp_path):
    from src.pce_cache.schema import init_schema
    db_path = str(tmp_path / "cap.sqlite")
    engine = create_engine(f"sqlite:///{db_path}")
    init_schema(engine)
    return db_path, sessionmaker(engine)


def test_capacity_snapshot_shape_and_lag(cache_db):
    from src.pce_cache.capacity import capacity_snapshot
    db_path, sf = cache_db
    now = datetime.now(timezone.utc)
    with sf.begin() as s:
        s.add(PceTrafficFlowRaw(
            flow_hash="cap-h1", src_ip="1.1.1.1", dst_ip="2.2.2.2",
            port=80, protocol="tcp", action="allowed", flow_count=1,
            bytes_in=0, bytes_out=0, first_detected=now, last_detected=now,
            ingested_at=now, raw_json="{}"))
    cfg = SimpleNamespace(db_path=db_path, archive_enabled=True)
    snap = capacity_snapshot(sf, cfg)
    assert snap["db_bytes"] > 0
    assert snap["siem_pending"] == 0
    # 有資料但 archiver 從未推進 cursor → None（全部未封存）
    assert snap["archiver_lag_seconds"]["traffic"] is None


def test_capacity_warnings_thresholds():
    from src.pce_cache.capacity import capacity_warnings
    cfg = SimpleNamespace(disk_free_warn_gb=10, siem_pending_warn_rows=100,
                          archive_interval_hours=24)
    snap = {
        "db_bytes": 1,
        "disk_free_bytes": 1 << 30,               # 1 GB < 10 GB 門檻
        "siem_pending": 500,                       # > 100
        "archiver_lag_seconds": {"traffic": 999999},  # > 48h
    }
    msgs = capacity_warnings(snap, cfg)
    assert len(msgs) == 3


def test_capacity_warnings_quiet_when_healthy():
    from src.pce_cache.capacity import capacity_warnings
    cfg = SimpleNamespace(disk_free_warn_gb=10, siem_pending_warn_rows=100,
                          archive_interval_hours=24)
    snap = {"db_bytes": 1, "disk_free_bytes": 100 << 30,
            "siem_pending": 0, "archiver_lag_seconds": {"traffic": 60}}
    assert capacity_warnings(snap, cfg) == []


def test_scheduler_registers_capacity_monitor():
    # 仿 tests/test_scheduler_write_serialization.py 的 MagicMock cm 模式
    from unittest.mock import MagicMock
    from src.scheduler import build_scheduler
    cm = MagicMock()
    cm.config = {}
    cm.models.pce_cache.enabled = True
    cm.models.pce_cache.events_poll_interval_seconds = 300
    cm.models.pce_cache.traffic_poll_interval_seconds = 3600
    cm.models.pce_cache.archive_enabled = False
    cm.models.siem.enabled = False
    sched = build_scheduler(cm)
    job = sched.get_job("pce_cache_capacity_monitor")
    assert job is not None
    assert job.executor == "default"
