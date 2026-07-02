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


def test_import_floors_timestamps_to_whole_seconds(sf, archive_dir):
    # archive 查閱靠「查詢窗=MIN(last_detected) 整秒」使 cover_state=full、不打即時 API。
    # 匯入時把時間戳 floor 到整秒，讓此不變量與來源精度無關。
    from src.pce_cache.archive_import import ArchiveImporter
    raw = {"src_ip": "1.1.1.1", "dst_ip": "2.2.2.2", "port": 1, "action": "allowed",
           "first_detected": "2026-06-10T11:00:00.777+00:00"}
    line = orjson.dumps({
        "event_time": "2026-06-10T12:00:00.5+00:00",
        "ingested_at": "2026-06-10T12:00:00.5+00:00",
        "flow_hash": "sub", "src_ip": "1.1.1.1", "dst_ip": "2.2.2.2",
        "port": 1, "protocol": "tcp", "action": "allowed", "flow_count": 1,
        "bytes_in": 0, "bytes_out": 0, "raw": raw,
    })
    _write(archive_dir, "traffic-2026-06-10.jsonl", [line])
    ArchiveImporter(archive_dir, sf).import_range(date(2026, 6, 1), date(2026, 6, 30))
    r = _rows(sf)[0]
    assert r.last_detected.microsecond == 0
    assert r.first_detected.microsecond == 0


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


def test_import_skips_rows_missing_required_keys_or_bad_timestamp(sf, archive_dir):
    # 缺 flow_hash / event_time，或時間戳格式非法：per-line 容錯，計入
    # skipped、不中斷整次匯入；好行仍正常入庫。
    from src.pce_cache.archive_import import ArchiveImporter
    raw = {"src_ip": "1.1.1.1", "dst_ip": "2.2.2.2", "port": 22, "action": "allowed"}
    lines = [
        _traffic_line("ok1", "2026-06-10", raw),
        orjson.dumps({  # 缺 flow_hash
            "event_time": "2026-06-10T12:00:00+00:00",
            "ingested_at": "2026-06-10T12:00:00+00:00",
            "raw": raw,
        }),
        orjson.dumps({  # 缺 event_time
            "ingested_at": "2026-06-10T12:00:00+00:00",
            "flow_hash": "no-event-time", "raw": raw,
        }),
        orjson.dumps({  # 時間戳格式非法
            "event_time": "not-a-timestamp",
            "ingested_at": "2026-06-10T12:00:00+00:00",
            "flow_hash": "bad-ts", "raw": raw,
        }),
        _traffic_line("ok2", "2026-06-10", raw),
    ]
    _write(archive_dir, "traffic-2026-06-10.jsonl", lines)

    res = ArchiveImporter(archive_dir, sf).import_range(date(2026, 6, 1), date(2026, 6, 30))
    assert res["rows"] == 2 and res["skipped"] == 3
    assert {r.flow_hash for r in _rows(sf)} == {"ok1", "ok2"}


def test_import_truncated_gzip_skips_remainder_and_continues(sf, archive_dir):
    # 截斷/損壞的 .gz（gzip 輪替中途崩潰的典型場景）：該檔剩餘部分放棄，
    # 記 warning，不中斷整次匯入，繼續匯入下一檔。
    from src.pce_cache.archive_import import ArchiveImporter
    raw = {"src_ip": "1.1.1.1", "dst_ip": "2.2.2.2", "port": 22, "action": "allowed"}
    path = os.path.join(archive_dir, "traffic-2026-06-01.jsonl.gz")
    with gzip.open(path, "wb") as fh:
        fh.write(_traffic_line("truncated", "2026-06-01", raw) + b"\n")
    # 截斷尾部，破壞 gzip 的 end-of-stream marker，模擬半寫入檔案。
    with open(path, "rb") as fh:
        good_bytes = fh.read()
    with open(path, "wb") as fh:
        fh.write(good_bytes[: len(good_bytes) // 2])

    _write(archive_dir, "traffic-2026-06-02.jsonl", [_traffic_line("good", "2026-06-02", raw)])

    res = ArchiveImporter(archive_dir, sf).import_range(date(2026, 6, 1), date(2026, 6, 30))
    assert res["files"] == 2                          # 兩檔都嘗試讀
    assert {r.flow_hash for r in _rows(sf)} == {"good"}  # 下一檔繼續匯入


def test_import_flush_db_error_propagates(sf, archive_dir):
    # DB 寫入例外（_flush）不可被 per-line 容錯吞掉，仍須往外傳播。
    from src.pce_cache.archive_import import ArchiveImporter
    raw = {"src_ip": "1.1.1.1", "dst_ip": "2.2.2.2", "port": 22, "action": "allowed"}
    _write(archive_dir, "traffic-2026-06-10.jsonl", [_traffic_line("boom", "2026-06-10", raw)])

    importer = ArchiveImporter(archive_dir, sf)
    importer._flush = lambda chunk: (_ for _ in ()).throw(RuntimeError("db boom"))
    with pytest.raises(RuntimeError, match="db boom"):
        importer.import_range(date(2026, 6, 1), date(2026, 6, 30))


def test_import_dedups_multiple_rows_within_same_batch(sf, archive_dir):
    # 同一批（500 列/transaction）內有 3 筆重複 flow_hash：只留第一筆，
    # skipped 由 rowcount 差額推得（3 筆嘗試 - 1 筆實際插入 = 2）。
    from src.pce_cache.archive_import import ArchiveImporter
    raw = {"src_ip": "1.1.1.1", "dst_ip": "2.2.2.2", "port": 22, "action": "allowed"}
    lines = [_traffic_line("triple", "2026-06-10", raw) for _ in range(3)]
    _write(archive_dir, "traffic-2026-06-10.jsonl", lines)

    res = ArchiveImporter(archive_dir, sf).import_range(date(2026, 6, 1), date(2026, 6, 30))
    assert res["rows"] == 1 and res["skipped"] == 2
    assert {r.flow_hash for r in _rows(sf)} == {"triple"}


def test_import_dedups_across_files(sf, archive_dir):
    # 同 flow_hash 出現在不同 archive 檔案（跨檔案）：仍靠 flow_hash unique
    # 約束只留一筆，統計（rows/skipped/files）需正確反映跨檔案的重複。
    from src.pce_cache.archive_import import ArchiveImporter
    raw = {"src_ip": "1.1.1.1", "dst_ip": "2.2.2.2", "port": 22, "action": "allowed"}
    _write(archive_dir, "traffic-2026-06-10.jsonl", [_traffic_line("cross", "2026-06-10", raw)])
    _write(archive_dir, "traffic-2026-06-11.jsonl", [_traffic_line("cross", "2026-06-11", raw)])

    res = ArchiveImporter(archive_dir, sf).import_range(date(2026, 6, 1), date(2026, 6, 30))
    assert res["rows"] == 1 and res["skipped"] == 1 and res["files"] == 2
    assert {r.flow_hash for r in _rows(sf)} == {"cross"}


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


def test_load_review_no_files_preserves_previous(tmp_path, archive_dir):
    from src.pce_cache.archive_import import (
        load_archive_review, review_session_factory, review_status)
    from sqlalchemy import select
    raw = {"src_ip": "1.1.1.1", "dst_ip": "2.2.2.2", "port": 1, "action": "allowed"}
    _write(archive_dir, "traffic-2026-06-05.jsonl", [_traffic_line("keep", "2026-06-05", raw)])
    cfg = _cfg(tmp_path, archive_dir)

    load_archive_review(cfg, date(2026, 6, 1), date(2026, 6, 30))   # 有資料
    # 載入一個沒有任何封存檔的範圍 → 不重建、回 no_files、保留前次
    res = load_archive_review(cfg, date(2026, 7, 1), date(2026, 7, 31))
    assert res["no_files"] is True and res["files"] == 0

    with review_session_factory(cfg)() as s:
        hashes = {r.flow_hash for r in s.execute(select(PceTrafficFlowRaw)).scalars().all()}
    assert hashes == {"keep"}                       # 上一次載入的資料仍在
    assert review_status(cfg)["start"] == "2026-06-01"   # meta 未被覆寫


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


def test_load_review_concurrent_second_call_raises_busy(tmp_path, archive_dir, monkeypatch):
    """兩個 load 併發：第一個進行中時，第二個必須立即被 module-level lock
    擋下（non-blocking），而不是排隊等待或同時重建同一個 review DB。"""
    import threading
    from src.pce_cache import archive_import

    raw = {"src_ip": "1.1.1.1", "dst_ip": "2.2.2.2", "port": 1, "action": "allowed"}
    _write(archive_dir, "traffic-2026-06-05.jsonl", [_traffic_line("c1", "2026-06-05", raw)])
    cfg = _cfg(tmp_path, archive_dir)

    started = threading.Event()
    release = threading.Event()
    orig_import_range = archive_import.ArchiveImporter.import_range

    def slow_import_range(self, start, end):
        started.set()
        assert release.wait(timeout=5), "release 逾時未被設置"
        return orig_import_range(self, start, end)

    monkeypatch.setattr(archive_import.ArchiveImporter, "import_range", slow_import_range)

    results = {}

    def _first():
        results["first"] = archive_import.load_archive_review(
            cfg, date(2026, 6, 1), date(2026, 6, 30))

    t = threading.Thread(target=_first)
    t.start()
    assert started.wait(timeout=5), "第一個 load 未進入 import_range"
    with pytest.raises(archive_import.ArchiveLoadBusy):
        archive_import.load_archive_review(cfg, date(2026, 6, 1), date(2026, 6, 30))
    release.set()
    t.join(timeout=5)
    assert not t.is_alive()
    assert results["first"]["loaded"] is True and results["first"]["rows"] == 1


def test_load_review_failure_path_preserves_previous_db_and_meta(tmp_path, archive_dir, monkeypatch):
    """核心不變量：mid-import 例外後，review DB 內容與 review_status 仍必須
    一致地描述上一次成功載入，不可留下「meta 說 A、DB 是半個 B」的狀態。"""
    from src.pce_cache import archive_import

    raw = {"src_ip": "1.1.1.1", "dst_ip": "2.2.2.2", "port": 1, "action": "allowed"}
    _write(archive_dir, "traffic-2026-06-05.jsonl", [_traffic_line("keep", "2026-06-05", raw)])
    cfg = _cfg(tmp_path, archive_dir)

    good = archive_import.load_archive_review(cfg, date(2026, 6, 1), date(2026, 6, 30))
    assert good["loaded"] is True

    db_path = archive_import.review_db_path(cfg)
    db_bytes_before = open(db_path, "rb").read()
    status_before = archive_import.review_status(cfg)

    def boom(self, start, end):
        raise RuntimeError("mid-import boom")

    monkeypatch.setattr(archive_import.ArchiveImporter, "import_range", boom)
    _write(archive_dir, "traffic-2026-07-05.jsonl", [_traffic_line("new", "2026-07-05", raw)])

    with pytest.raises(RuntimeError):
        archive_import.load_archive_review(cfg, date(2026, 7, 1), date(2026, 7, 31))

    # 舊 DB 檔案 bytes 不變（從未被動過，重建只灌到 .tmp）
    assert open(db_path, "rb").read() == db_bytes_before
    # status 仍回報舊 meta，不是失敗那次的半吊子結果
    assert archive_import.review_status(cfg) == status_before
    # 失敗路徑要把暫存檔清乾淨，不留半灌的 .tmp
    assert not os.path.exists(db_path + ".tmp")
    assert not os.path.exists(db_path + ".tmp-wal")
    assert not os.path.exists(db_path + ".tmp-shm")


def test_review_status_corrupted_meta_returns_not_loaded(tmp_path, archive_dir):
    """半寫入或空的 meta 檔（崩潰造成）不可讓 review_status 拋
    orjson.JSONDecodeError；應視同未載入。"""
    from src.pce_cache.archive_import import review_status, _meta_path
    cfg = _cfg(tmp_path, archive_dir)
    with open(_meta_path(cfg), "wb") as fh:
        fh.write(b"")
    assert review_status(cfg) == {"loaded": False}

    with open(_meta_path(cfg), "wb") as fh:
        fh.write(b'{"loaded": true, "rows": ')  # 半寫入的 JSON
    assert review_status(cfg) == {"loaded": False}


def test_load_review_meta_write_is_atomic_no_tmp_leftover(tmp_path, archive_dir):
    """成功路徑不留 meta 的暫存檔（temp + os.replace 完成後應清乾淨）。"""
    from src.pce_cache.archive_import import load_archive_review, _meta_path
    raw = {"src_ip": "1.1.1.1", "dst_ip": "2.2.2.2", "port": 1, "action": "allowed"}
    _write(archive_dir, "traffic-2026-06-05.jsonl", [_traffic_line("a1", "2026-06-05", raw)])
    cfg = _cfg(tmp_path, archive_dir)

    load_archive_review(cfg, date(2026, 6, 1), date(2026, 6, 30))
    assert not os.path.exists(_meta_path(cfg) + ".tmp")
