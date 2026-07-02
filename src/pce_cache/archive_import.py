from __future__ import annotations

import gzip
import os
import re
from datetime import date, datetime, timezone

import orjson
from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import PceTrafficFlowRaw

_TRAFFIC_FILE = re.compile(r"^traffic-(\d{4}-\d{2}-\d{2})\.jsonl(?:\.gz)?$")


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

    def __init__(self, archive_dir: str, session_factory: sessionmaker):
        self._dir = archive_dir
        self._sf = session_factory

    def import_range(self, start: date, end: date) -> dict:
        from src.report.parsers.api_parser import flatten_flow_record
        rows = files = skipped = 0
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
                try:
                    with self._sf.begin() as s:
                        s.add(PceTrafficFlowRaw(
                            flow_hash=rec["flow_hash"],
                            src_ip=rec.get("src_ip", ""),
                            src_workload=rec.get("src_workload"),
                            dst_ip=rec.get("dst_ip", ""),
                            dst_workload=rec.get("dst_workload"),
                            port=rec.get("port") or 0,
                            protocol=rec.get("protocol", "tcp"),
                            action=rec.get("action", "unknown"),
                            flow_count=rec.get("flow_count") or 1,
                            bytes_in=rec.get("bytes_in") or 0,
                            bytes_out=rec.get("bytes_out") or 0,
                            first_detected=first_detected,
                            last_detected=last_detected,
                            raw_json=orjson.dumps(raw).decode("utf-8"),
                            report_json=report_json,
                            ingested_at=ingested_at,
                        ))
                    rows += 1
                except IntegrityError:
                    skipped += 1
        return {"rows": rows, "files": files, "skipped": skipped,
                "start": start.isoformat(), "end": end.isoformat()}


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


def load_archive_review(cfg, start: date, end: date) -> dict:
    """重建 review DB → 匯入範圍內 traffic archive → 跑聚合 → 寫 sidecar meta。

    防呆：範圍內沒有任何封存檔時，不重建 review DB（保留目前已載入的資料）、
    也不改 meta，回報 no_files=True，讓呼叫端明確提示，而非顯示看似成功的
    「0 筆」並把上一次載入的資料洗掉。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src.pce_cache.schema import init_schema
    from src.pce_cache.aggregator import TrafficAggregator
    if not _matching_traffic_files(cfg.archive_dir, start, end):
        prev = review_status(cfg)
        return {"loaded": bool(prev.get("loaded")), "no_files": True,
                "files": 0, "rows": 0, "skipped": 0,
                "start": start.isoformat(), "end": end.isoformat()}
    db = review_db_path(cfg)
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(db + suffix)
        except FileNotFoundError:
            pass
    engine = create_engine(f"sqlite:///{db}")
    try:
        init_schema(engine)
        sf = sessionmaker(engine)
        result = ArchiveImporter(cfg.archive_dir, sf).import_range(start, end)
        TrafficAggregator(sf).run_once()
    finally:
        engine.dispose()  # 釋放檔案 handle，讓下次重建能安全刪檔
    meta = {"loaded": True, "rows": result["rows"], "files": result["files"],
            "skipped": result["skipped"], "start": result["start"], "end": result["end"]}
    with open(_meta_path(cfg), "wb") as fh:
        fh.write(orjson.dumps(meta))
    return meta


def review_status(cfg) -> dict:
    try:
        with open(_meta_path(cfg), "rb") as fh:
            return orjson.loads(fh.read())
    except FileNotFoundError:
        return {"loaded": False}
