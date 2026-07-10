import time
from datetime import date, datetime, timezone
from types import SimpleNamespace

import orjson


def _write_archive(dir_path, day: str, n: int):
    ts = datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)
    lines = []
    for i in range(n):
        lines.append(orjson.dumps({
            "flow_hash": f"a-h{day}-{i}", "src_ip": "10.0.0.1",
            "dst_ip": "10.0.0.2", "src_workload": None, "dst_workload": None,
            "port": 443, "protocol": "tcp", "action": "allowed",
            "flow_count": 1, "bytes_in": 10, "bytes_out": 20,
            "event_time": ts.isoformat(), "ingested_at": ts.isoformat(),
            "first_detected": ts.isoformat(),
            "raw": {"src_ip": "10.0.0.1"},
        }))
    (dir_path / f"traffic-{day}.jsonl").write_bytes(b"\n".join(lines) + b"\n")


def _cfg(tmp_path):
    return SimpleNamespace(
        archive_dir=str(tmp_path / "arch"),
        db_path=str(tmp_path / "cache.sqlite"),
        archive_review_max_days=31,
    )


def _wait_terminal(timeout=15):
    from src.pce_cache.archive_import import load_progress
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = load_progress()
        if st.get("state") in ("done", "error"):
            return st
        time.sleep(0.1)
    raise AssertionError(f"load did not finish: {load_progress()}")


def test_start_archive_load_runs_in_background(tmp_path):
    from src.pce_cache.archive_import import start_archive_load
    (tmp_path / "arch").mkdir()
    _write_archive(tmp_path / "arch", "2026-07-01", 5)
    res = start_archive_load(_cfg(tmp_path), date(2026, 7, 1), date(2026, 7, 1))
    assert res["started"] is True
    st = _wait_terminal()
    assert st["state"] == "done"
    assert st["rows"] == 5


def test_start_archive_load_busy_raises(tmp_path):
    import pytest
    from src.pce_cache import archive_import as ai
    (tmp_path / "arch").mkdir()
    assert ai._LOAD_LOCK.acquire(blocking=False)  # 模擬另一個 load 進行中
    try:
        with pytest.raises(ai.ArchiveLoadBusy):
            ai.start_archive_load(_cfg(tmp_path), date(2026, 7, 1), date(2026, 7, 1))
    finally:
        ai._LOAD_LOCK.release()


def test_load_error_reported_in_progress(tmp_path):
    from src.pce_cache.archive_import import start_archive_load
    (tmp_path / "arch").mkdir()
    (tmp_path / "arch" / "traffic-2026-07-01.jsonl").write_bytes(b"")
    cfg = _cfg(tmp_path)
    cfg.db_path = str(tmp_path / "no-such-dir" / "x" / "cache.sqlite")  # 逼出錯誤
    start_archive_load(cfg, date(2026, 7, 1), date(2026, 7, 1))
    st = _wait_terminal()
    assert st["state"] == "error"
    assert st["error"]
