from __future__ import annotations

import gzip
import os
import re
import threading
from datetime import date, datetime, timezone

import orjson
from loguru import logger
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import PceTrafficFlowRaw

_TRAFFIC_FILE = re.compile(r"^traffic-(\d{4}-\d{2}-\d{2})\.jsonl(?:\.gz)?$")

# 同時只允許一個 load 在跑：重建/匯入/聚合期間若第二個 load 進來，會跟第一個
# 搶同一個暫存檔與目標 DB。用 module-level lock + non-blocking acquire，
# 第二個請求立即被擋下（不排隊），呼叫端（web.py）接住 ArchiveLoadBusy 回 409。
_LOAD_LOCK = threading.Lock()


class ArchiveLoadBusy(Exception):
    """另一個 load_archive_review 正在進行中（lock 非阻塞取得失敗）。"""


def _parse_dt(s: str) -> datetime:
    """archive ISO 時間戳 → aware UTC datetime。處理結尾 Z、明確 offset、
    以及 naive（早期未帶 offset 的 archive）→ 視為 UTC。"""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    dt = dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
    # Floor 到整秒：archive 查閱把查詢窗設為 MIN(last_detected) 的整秒字串
    # （actions.py 用 strftime("...%SZ")）。若時間戳帶次秒精度，start < earliest
    # 會讓 CacheReader.cover_state 判 partial → fallback 打即時 PCE API，破壞
    # 「archive 查閱只讀 review DB」的不變量。整秒化使該不變量與來源精度無關。
    return dt.replace(microsecond=0)


def _iter_lines(path: str):
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rb") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield line


def _matching_traffic_files(archive_dir: str, start: date, end: date) -> list[str]:
    """回傳 archive_dir 下檔名日期落在 [start, end]（含端點）的 traffic 日檔（排序）。
    依檔名日期挑檔，不開檔讀內容。目錄不存在/不可讀 → 回空清單。"""
    try:
        names = sorted(os.listdir(archive_dir))
    except OSError as exc:
        logger.warning("archive: listdir {} failed: {}", archive_dir, exc)
        return []
    out = []
    for name in names:
        m = _TRAFFIC_FILE.match(name)
        if not m:
            continue
        try:
            file_date = date.fromisoformat(m.group(1))
        except ValueError:
            continue
        if start <= file_date <= end:
            out.append(name)
    return out


class ArchiveImporter:
    """把 archive 的 traffic JSONL 逐行還原成 PceTrafficFlowRaw 灌進指定的 review DB。"""

    _CHUNK = 500

    def __init__(self, archive_dir: str, session_factory: sessionmaker):
        self._dir = archive_dir
        self._sf = session_factory

    def import_range(self, start: date, end: date) -> dict:
        from src.report.parsers.api_parser import flatten_flow_record
        files = skipped = rows = 0
        pending: list[dict] = []
        for name in _matching_traffic_files(self._dir, start, end):
            files += 1
            path = os.path.join(self._dir, name)
            for line in _iter_lines(path):
                try:
                    rec = orjson.loads(line)
                except orjson.JSONDecodeError:
                    skipped += 1
                    continue
                raw = rec.get("raw")
                if raw is None:
                    skipped += 1
                    continue
                last_detected = _parse_dt(rec["event_time"])
                ingested_at = _parse_dt(rec["ingested_at"])
                ts_range = raw.get("timestamp_range") or {}
                fd_raw = raw.get("first_detected") or ts_range.get("first_detected", "")
                first_detected = _parse_dt(fd_raw) if fd_raw else last_detected
                # 與即時 ingest / backfill 一致：預先算好 report_json，維持
                # ix_raw_report_json_null 的「幾乎無 NULL」不變量；flatten 失敗不阻斷。
                try:
                    report_json = orjson.dumps(flatten_flow_record(raw)).decode("utf-8")
                except Exception:  # noqa: BLE001
                    report_json = None
                pending.append({
                    "flow_hash": rec["flow_hash"],
                    "src_ip": rec.get("src_ip", ""),
                    "src_workload": rec.get("src_workload"),
                    "dst_ip": rec.get("dst_ip", ""),
                    "dst_workload": rec.get("dst_workload"),
                    "port": rec.get("port") or 0,
                    "protocol": rec.get("protocol", "tcp"),
                    "action": rec.get("action", "unknown"),
                    "flow_count": rec.get("flow_count") or 1,
                    "bytes_in": rec.get("bytes_in") or 0,
                    "bytes_out": rec.get("bytes_out") or 0,
                    "first_detected": first_detected,
                    "last_detected": last_detected,
                    "raw_json": orjson.dumps(raw).decode("utf-8"),
                    "report_json": report_json,
                    "ingested_at": ingested_at,
                })
                if len(pending) >= self._CHUNK:
                    inserted, dup = self._flush(pending)
                    rows += inserted
                    skipped += dup
                    pending = []
        if pending:
            inserted, dup = self._flush(pending)
            rows += inserted
            skipped += dup
        return {"rows": rows, "files": files, "skipped": skipped,
                "start": start.isoformat(), "end": end.isoformat()}

    def _flush(self, chunk: list[dict]) -> tuple[int, int]:
        """500 列/transaction 的 chunked upsert：以 flow_hash 為 unique key
        做 on_conflict_do_nothing，不再靠 IntegrityError 逐列去重。同批（或
        跨批但已落地）內的重複 flow_hash 只留第一筆；rowcount 即實際插入數，
        批內筆數與 rowcount 的差額即該批的重複數。"""
        with self._sf.begin() as s:
            stmt = (
                sqlite_insert(PceTrafficFlowRaw)
                .values(chunk)
                .on_conflict_do_nothing(index_elements=["flow_hash"])
            )
            result = s.execute(stmt)
            inserted = result.rowcount
        return inserted, len(chunk) - inserted


def review_db_path(cfg) -> str:
    """review DB 放在 cache db_path 同目錄下，固定檔名。"""
    base = os.path.dirname(os.path.abspath(cfg.db_path))
    return os.path.join(base, "archive_review.sqlite")


def _meta_path(cfg) -> str:
    return review_db_path(cfg) + ".meta.json"


def review_session_factory(cfg):
    """對 review DB 建一個 sessionmaker（短命 engine，不用 process 快取，
    避免 review DB 被重建後抓到舊連線）。

    此函式會被 per-query 呼叫，若用預設 pool（QueuePool）engine 又從不
    dispose，長跑程序會累積連線池與 SQLite FD 直到 GC。用 NullPool 讓
    每個 session 各開各關自己的連線、不留池；讀路徑本就不需連線池。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import NullPool
    from src.pce_cache.schema import init_schema
    engine = create_engine(f"sqlite:///{review_db_path(cfg)}", poolclass=NullPool)
    init_schema(engine)
    return sessionmaker(engine)


def _remove_sqlite_sidecars(path: str) -> None:
    """只刪 -wal/-shm sidecar，留下主檔（存在才刪，不存在不當錯誤）。"""
    for suffix in ("-wal", "-shm"):
        try:
            os.remove(path + suffix)
        except FileNotFoundError:
            pass


def _remove_sqlite_files(path: str) -> None:
    """刪除 SQLite 主檔與其 -wal/-shm sidecar（存在才刪，不存在不當錯誤）。"""
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    _remove_sqlite_sidecars(path)


def _write_meta(cfg, meta: dict) -> None:
    """meta 寫入 temp + os.replace，避免崩潰留下半寫入的 meta 檔。"""
    path = _meta_path(cfg)
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(orjson.dumps(meta))
    os.replace(tmp, path)


def load_archive_review(cfg, start: date, end: date) -> dict:
    """重建 review DB → 匯入範圍內 traffic archive → 跑聚合 → 寫 sidecar meta。

    防呆：範圍內沒有任何封存檔時，不重建 review DB（保留目前已載入的資料）、
    也不改 meta，回報 no_files=True，讓呼叫端明確提示，而非顯示看似成功的
    「0 筆」並把上一次載入的資料洗掉。

    併發：整個函式被 module-level lock 包住，non-blocking acquire——第二個
    進來的 load 立即拋 ArchiveLoadBusy，不排隊、不會跟第一個搶同一份暫存檔。

    核心不變量：load 失敗後，review_status 與 review DB 必須仍一致地描述
    上一次成功載入。做法是 build-to-temp：整個重建/匯入/聚合都灌到獨立的
    暫存檔（`archive_review.sqlite.tmp`），只有全部成功才 os.replace 原子
    切換成正式檔、再寫 meta；任何一步失敗，正式 DB 與 meta 完全沒被碰過，
    只需清掉暫存檔。"""
    from sqlalchemy import create_engine
    from src.pce_cache.schema import init_schema
    from src.pce_cache.aggregator import TrafficAggregator
    if not _LOAD_LOCK.acquire(blocking=False):
        raise ArchiveLoadBusy()
    try:
        if not _matching_traffic_files(cfg.archive_dir, start, end):
            prev = review_status(cfg)
            return {"loaded": bool(prev.get("loaded")), "no_files": True,
                    "files": 0, "rows": 0, "skipped": 0,
                    "start": start.isoformat(), "end": end.isoformat()}
        db = review_db_path(cfg)
        tmp = db + ".tmp"
        # 清掉前次可能留下的暫存檔（例如上次崩潰在切換前中斷）。
        _remove_sqlite_files(tmp)
        engine = create_engine(f"sqlite:///{tmp}")
        try:
            init_schema(engine)
            sf = sessionmaker(engine)
            result = ArchiveImporter(cfg.archive_dir, sf).import_range(start, end)
            TrafficAggregator(sf).run_once()
            # 把 WAL 內容併回主檔並清空 -wal，讓暫存檔本身自足——
            # 之後 os.replace 只搬主檔，不會漏資料留在 -wal 裡。
            with engine.begin() as conn:
                conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            engine.dispose()
            _remove_sqlite_files(tmp)
            raise
        engine.dispose()  # 釋放檔案 handle，才能安全 replace
        # 切換前清掉暫存檔自己殘留的 -wal/-shm（TRUNCATE checkpoint 後理論上
        # 已空，防禦性再清一次），以及目標檔案的舊 -wal/-shm（換了主檔後，
        # 舊 sidecar 對新主檔無效，留著會被下個連線誤讀）。
        _remove_sqlite_sidecars(tmp)
        _remove_sqlite_sidecars(db)
        os.replace(tmp, db)
        meta = {"loaded": True, "rows": result["rows"], "files": result["files"],
                "skipped": result["skipped"], "start": result["start"], "end": result["end"]}
        _write_meta(cfg, meta)
        return meta
    finally:
        _LOAD_LOCK.release()


def review_status(cfg) -> dict:
    try:
        with open(_meta_path(cfg), "rb") as fh:
            return orjson.loads(fh.read())
    except (FileNotFoundError, orjson.JSONDecodeError):
        return {"loaded": False}
