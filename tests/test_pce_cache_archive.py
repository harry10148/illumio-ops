import gzip
import os
import time
from datetime import datetime, timezone

import orjson
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.pce_cache.schema import init_schema
from src.pce_cache.models import PceEvent, PceTrafficFlowRaw, IngestionCursor


@pytest.fixture
def sf(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'c.sqlite'}")
    init_schema(engine)
    return sessionmaker(engine)


@pytest.fixture
def archive_dir(tmp_path):
    d = tmp_path / "archive"
    d.mkdir()
    return str(d)


def _dt(y, mo, d, h=12):
    return datetime(y, mo, d, h, 0, 0, tzinfo=timezone.utc)


def _add_traffic(sf, flow_hash, last_detected, ingested_at, raw):
    with sf.begin() as s:
        s.add(PceTrafficFlowRaw(
            flow_hash=flow_hash, first_detected=last_detected, last_detected=last_detected,
            src_ip="10.0.0.1", src_workload="web", dst_ip="10.0.0.2", dst_workload="db",
            port=443, protocol="tcp", action="blocked", flow_count=1,
            bytes_in=100, bytes_out=200, raw_json=orjson.dumps(raw).decode(),
            ingested_at=ingested_at,
        ))


def _read_lines(path):
    with open(path, "rb") as fh:
        return [orjson.loads(ln) for ln in fh.read().splitlines() if ln.strip()]


def test_archive_exports_new_traffic_rows_as_jsonl(sf, archive_dir):
    from src.pce_cache.archive import ArchiveExporter
    _add_traffic(sf, "h1", _dt(2026, 6, 30), _dt(2026, 6, 30), {"href": "/f/1", "k": "v1"})
    _add_traffic(sf, "h2", _dt(2026, 6, 30), _dt(2026, 6, 30), {"href": "/f/2", "k": "v2"})

    res = ArchiveExporter(sf, archive_dir).run_once()

    assert res["traffic"].rows == 2
    path = os.path.join(archive_dir, "traffic-2026-06-30.jsonl")
    assert os.path.exists(path)
    lines = _read_lines(path)
    assert len(lines) == 2
    assert {ln["flow_hash"] for ln in lines} == {"h1", "h2"}
    # 保真：原始 raw_json 完整內嵌且可解析
    by_hash = {ln["flow_hash"]: ln for ln in lines}
    assert by_hash["h1"]["raw"] == {"href": "/f/1", "k": "v1"}
    assert by_hash["h1"]["port"] == 443
    assert by_hash["h1"]["action"] == "blocked"
    # 契約：archive 長期保存的時間戳一律帶明確 UTC offset，避免下游
    # fromisoformat() 拿到 naive datetime 而在比較時炸掉
    assert by_hash["h1"]["event_time"].endswith("+00:00")
    assert by_hash["h1"]["ingested_at"].endswith("+00:00")


def test_archive_incremental_appends_only_new_rows(sf, archive_dir):
    from src.pce_cache.archive import ArchiveExporter
    exporter = ArchiveExporter(sf, archive_dir)

    _add_traffic(sf, "h1", _dt(2026, 6, 30), _dt(2026, 6, 30), {"n": 1})
    r1 = exporter.run_once()
    assert r1["traffic"].rows == 1

    # 沒有新列 → 第二次不匯出任何東西
    r2 = exporter.run_once()
    assert r2["traffic"].rows == 0

    # 新增兩列（較晚 ingested_at）→ 只匯出這兩列
    _add_traffic(sf, "h2", _dt(2026, 6, 30), _dt(2026, 6, 30, 13), {"n": 2})
    _add_traffic(sf, "h3", _dt(2026, 6, 30), _dt(2026, 6, 30, 14), {"n": 3})
    r3 = exporter.run_once()
    assert r3["traffic"].rows == 2

    path = os.path.join(archive_dir, "traffic-2026-06-30.jsonl")
    lines = _read_lines(path)
    assert [ln["flow_hash"] for ln in lines] == ["h1", "h2", "h3"]  # 無重複、順序穩定


def test_archive_cursor_persisted_for_archiver_consumer(sf, archive_dir):
    from src.pce_cache.archive import ArchiveExporter
    _add_traffic(sf, "h1", _dt(2026, 6, 30), _dt(2026, 6, 30), {"n": 1})
    ArchiveExporter(sf, archive_dir).run_once()
    with sf() as s:
        cur = s.get(IngestionCursor, ("archiver", "pce_traffic_flows_raw"))
    assert cur is not None
    assert cur.last_row_id is not None


def test_archive_splits_files_by_event_date(sf, archive_dir):
    from src.pce_cache.archive import ArchiveExporter
    # 同一批、事件時間跨兩天（ingested_at 遞增以維持游標順序）
    _add_traffic(sf, "d1", _dt(2026, 6, 29), _dt(2026, 6, 30, 10), {"n": 1})
    _add_traffic(sf, "d2", _dt(2026, 6, 30), _dt(2026, 6, 30, 11), {"n": 2})

    res = ArchiveExporter(sf, archive_dir).run_once()
    assert res["traffic"].rows == 2

    p29 = os.path.join(archive_dir, "traffic-2026-06-29.jsonl")
    p30 = os.path.join(archive_dir, "traffic-2026-06-30.jsonl")
    assert len(_read_lines(p29)) == 1
    assert len(_read_lines(p30)) == 1
    assert _read_lines(p29)[0]["flow_hash"] == "d1"


def test_archive_buckets_naive_sqlite_datetime_by_utc_day(sf, archive_dir):
    # SQLite 讀回 DateTime(timezone=True) 會是 naive datetime（tzinfo 被剝除），
    # 值本身仍是 UTC wall-clock。UTC 午夜後 30 分的事件必須落在當天（UTC）檔案，
    # 不能被本機時區（例如 +8）誤判成前一天。
    # 把 host TZ 固定成 UTC+8，讓這條測試在任何 CI host（包括 TZ=UTC）都有鑑別力：
    # 若程式碼退化成用本機時區分日，這裡一定會抓到。
    original_tz = os.environ.get("TZ")
    os.environ["TZ"] = "Asia/Taipei"
    time.tzset()
    try:
        from src.pce_cache.archive import ArchiveExporter
        midnight_utc = datetime(2026, 7, 1, 0, 30, tzinfo=timezone.utc)
        _add_traffic(sf, "h1", midnight_utc, midnight_utc, {"n": 1})

        res = ArchiveExporter(sf, archive_dir).run_once()
        assert res["traffic"].rows == 1

        correct_path = os.path.join(archive_dir, "traffic-2026-07-01.jsonl")
        wrong_path = os.path.join(archive_dir, "traffic-2026-06-30.jsonl")
        assert os.path.exists(correct_path)
        assert not os.path.exists(wrong_path)
        lines = _read_lines(correct_path)
        assert [ln["flow_hash"] for ln in lines] == ["h1"]
    finally:
        if original_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = original_tz
        time.tzset()


def test_archive_exports_audit_events(sf, archive_dir):
    from src.pce_cache.archive import ArchiveExporter
    with sf.begin() as s:
        s.add(PceEvent(
            pce_href="/orgs/1/events/e1", pce_event_id="e1",
            timestamp=_dt(2026, 6, 30), event_type="user.sign_in", severity="info",
            status="success", pce_fqdn="pce.test",
            raw_json=orjson.dumps({"href": "/orgs/1/events/e1", "d": 1}).decode(),
            ingested_at=_dt(2026, 6, 30),
        ))
    res = ArchiveExporter(sf, archive_dir).run_once()
    assert res["audit"].rows == 1
    path = os.path.join(archive_dir, "audit-2026-06-30.jsonl")
    lines = _read_lines(path)
    assert lines[0]["pce_event_id"] == "e1"
    assert lines[0]["event_type"] == "user.sign_in"
    assert lines[0]["raw"] == {"href": "/orgs/1/events/e1", "d": 1}


def test_gzip_rotates_only_old_files(sf, archive_dir):
    from src.pce_cache.archive import ArchiveExporter
    exporter = ArchiveExporter(sf, archive_dir, gzip_after_days=7)

    old_path = os.path.join(archive_dir, "traffic-2026-06-01.jsonl")
    new_path = os.path.join(archive_dir, "traffic-2026-06-30.jsonl")
    with open(old_path, "wb") as fh:
        fh.write(orjson.dumps({"flow_hash": "old", "raw": {"n": 1}}) + b"\n")
    with open(new_path, "wb") as fh:
        fh.write(orjson.dumps({"flow_hash": "new", "raw": {"n": 2}}) + b"\n")

    # 把舊檔 mtime 調成 30 天前；新檔維持現在
    old_mtime = time.time() - 30 * 86400
    os.utime(old_path, (old_mtime, old_mtime))

    exporter._gzip_old_files()

    # 舊檔被壓縮、原檔移除；內容可解回原文
    assert not os.path.exists(old_path)
    gz = old_path + ".gz"
    assert os.path.exists(gz)
    with gzip.open(gz, "rb") as fh:
        restored = [orjson.loads(ln) for ln in fh.read().splitlines() if ln.strip()]
    assert restored[0]["flow_hash"] == "old"

    # 新檔不動
    assert os.path.exists(new_path)
    assert not os.path.exists(new_path + ".gz")


def test_gzip_is_idempotent_and_skips_already_gzipped(sf, archive_dir):
    from src.pce_cache.archive import ArchiveExporter
    exporter = ArchiveExporter(sf, archive_dir, gzip_after_days=7)
    gz = os.path.join(archive_dir, "traffic-2026-06-01.jsonl.gz")
    with gzip.open(gz, "wb") as fh:
        fh.write(b'{"flow_hash": "x"}\n')
    old_mtime = time.time() - 30 * 86400
    os.utime(gz, (old_mtime, old_mtime))
    with open(gz, "rb") as fh:
        before = fh.read()
    # 不應拋錯、也不應動既有 .gz
    exporter._gzip_old_files()
    assert os.path.exists(gz)
    # 路徑不變不代表內容沒被重寫：確認 bytes 前後一致，偵測「跳過邏輯失效但重複寫入同路徑」的迴歸
    with open(gz, "rb") as fh:
        after = fh.read()
    assert after == before


def test_gzip_rotation_appends_to_existing_gz_without_overwriting(sf, archive_dir):
    """既有 .gz（batch A，例如上一輪 rotation 留下的）+ 同名新 .jsonl（batch B，到期）
    → _gzip_old_files() 後 .gz 必須同時保留 batch A 與 batch B（多-member gzip），
    不能用 'wb' 截斷覆寫掉既有 batch A。"""
    from src.pce_cache.archive import ArchiveExporter
    exporter = ArchiveExporter(sf, archive_dir, gzip_after_days=7)

    path = os.path.join(archive_dir, "traffic-2026-05-01.jsonl")
    gz_path = path + ".gz"

    # 既有 .gz：batch A
    with gzip.open(gz_path, "wb") as fh:
        fh.write(orjson.dumps({"flow_hash": "batchA"}) + b"\n")

    # 同名新 .jsonl：batch B，mtime 調成到期
    with open(path, "wb") as fh:
        fh.write(orjson.dumps({"flow_hash": "batchB"}) + b"\n")
    old_mtime = time.time() - 30 * 86400
    os.utime(path, (old_mtime, old_mtime))

    exporter._gzip_old_files()

    assert not os.path.exists(path)  # 原 .jsonl 已移除
    with gzip.open(gz_path, "rb") as fh:
        restored = [orjson.loads(ln) for ln in fh.read().splitlines() if ln.strip()]
    assert {r["flow_hash"] for r in restored} == {"batchA", "batchB"}


def test_gzip_old_files_swallows_non_missing_oserror_from_listdir(sf, archive_dir, monkeypatch):
    from src.pce_cache import archive as archive_mod
    from src.pce_cache.archive import ArchiveExporter

    def _raise_permission_error(_path):
        raise PermissionError("denied")

    # os.listdir 可能丟出 FileNotFoundError 以外的 OSError（例如權限不足、非目錄），
    # 這是 best-effort 清理常式，任何列目錄失敗都應安全跳過而非中斷 archive job
    monkeypatch.setattr(archive_mod.os, "listdir", _raise_permission_error)

    ArchiveExporter(sf, archive_dir)._gzip_old_files()  # 不應拋錯
