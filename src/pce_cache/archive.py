from __future__ import annotations

import gzip
import os
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import orjson
from loguru import logger
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import IngestionCursor, PceEvent, PceTrafficFlowRaw

_BATCH = 5000
_CONSUMER = "archiver"
# 只匹配 archive 自己產生的檔名（traffic/audit-YYYY-MM-DD.jsonl[.gz]），
# 讓保存上限的刪除只碰 archive 檔、不誤刪目錄裡其他東西。
_ARCHIVE_NAME = re.compile(r"^(?:traffic|audit)-(\d{4}-\d{2}-\d{2})\.jsonl(?:\.gz)?$")


@dataclass
class ArchiveResult:
    source: str
    rows: int = 0
    files_written: list[str] = field(default_factory=list)


def _as_utc(dt: datetime) -> datetime:
    """SQLite 讀回的 DateTime(timezone=True) 是 naive（tzinfo 被剝除），
    其值為 UTC wall-clock。補上 UTC tzinfo 使下游時間戳無歧義。"""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _traffic_record(row: PceTrafficFlowRaw) -> dict:
    return {
        "event_time": _as_utc(row.last_detected).isoformat(),
        "ingested_at": _as_utc(row.ingested_at).isoformat(),
        # 頂層補 first_detected，與 flow_hash/last_detected 同樣保真格式對稱，
        # 避免 import 端只能靠 raw 回推（raw 缺值時會誤 fallback 成 last_detected）
        "first_detected": _as_utc(row.first_detected).isoformat(),
        "flow_hash": row.flow_hash,
        "src_ip": row.src_ip, "src_workload": row.src_workload,
        "dst_ip": row.dst_ip, "dst_workload": row.dst_workload,
        "port": row.port, "protocol": row.protocol, "action": row.action,
        "flow_count": row.flow_count,
        "bytes_in": row.bytes_in, "bytes_out": row.bytes_out,
        "raw": orjson.loads(row.raw_json) if row.raw_json else None,
    }


def _audit_record(row: PceEvent) -> dict:
    return {
        "event_time": _as_utc(row.timestamp).isoformat(),
        "ingested_at": _as_utc(row.ingested_at).isoformat(),
        "pce_href": row.pce_href, "pce_event_id": row.pce_event_id,
        "event_type": row.event_type, "severity": row.severity,
        "status": row.status, "pce_fqdn": row.pce_fqdn,
        "raw": orjson.loads(row.raw_json) if row.raw_json else None,
    }


# (prefix, model, source_table, event_time_attr, record_builder)
_SOURCES = [
    ("traffic", PceTrafficFlowRaw, "pce_traffic_flows_raw", "last_detected", _traffic_record),
    ("audit", PceEvent, "pce_events", "timestamp", _audit_record),
]


class ArchiveExporter:
    """把 pce_cache 的 traffic/audit 列增量匯出成分日 JSONL，供長期保存。

    交付語意：每批先寫檔並 fsync 成功後才推進 archiver cursor，故為
    at-least-once —— 正常運作不重複，但若在 fsync 後、cursor 推進前崩潰，
    下次會重寫同批，JSONL 可能含重複列（無資料遺失；下游可用 flow_hash /
    pce_event_id 去重）。

    儲存語意：以 append + gzip 輪替 + remove 操作一般 POSIX 可讀寫目錄，
    非硬體 WORM 檔案系統（後者會拒絕 append/remove）。目錄不可寫時各操作
    以 logger.warning 安全降級，不會腐化既有檔案。

    長壽 flow 的成長會被重新匯出（F6 修復，取代舊版「只文件化不改行為」的
    已知限制）：
      - 匯出游標依 (ingested_at, id) 前進；ingestor 的 upsert（見
        ingestor_traffic.py 的 on_conflict_do_update）現在會把 conflict 時的
        ingested_at bump 到本次 ingest 時間（不再只刷新 last_detected/
        bytes_in/bytes_out/flow_count 這些 volatile 欄位）。
      - 因此一筆 flow 即使先前已被匯出過（游標已越過它舊的 ingested_at），
        只要之後在 live cache 端又被 re-pull 而成長，bump 過的 ingested_at
        會讓它重新落在游標之後，下一輪 export 會再次撿到它、寫出成長後的值。
      - import 端（archive_import.py 的 ArchiveImporter._flush）同步改成
        upsert（取代舊版 on_conflict_do_nothing）：同 flow_hash 的後續匯出以
        MAX 合併 last_detected/bytes_in/bytes_out/flow_count（first_detected
        取 MIN；raw_json/report_json 取較新 last_detected 那一側），而不是把
        後到的成長值整批丟棄。兩端缺一則修復無效：只 bump 不改 import 端，
        後到的列在匯入時仍會被丟棄；只改 import 端不 bump，archiver 游標根本
        不會重新撿到該列讓它有機會被再次匯出。
      - 歷史遺留：F6 修復前產生的 archive 檔案，其中長壽 flow 可能仍停在
        「首次匯出當下的快照值」；只要該 flow 之後（在修復後的 ingestor 下）
        再被 re-pull 一次並匯出，import 端的 MAX 合併會自然把 review DB 的值
        追上最新累積值，不需要手動 backfill。短命 flow（一次性、匯出後不再
        被 upsert）本就不受影響。
    """

    def __init__(self, session_factory: sessionmaker, archive_dir: str,
                 gzip_after_days: int = 7, retention_days: int = 0):
        self._sf = session_factory
        self._dir = archive_dir
        self._gzip_after_days = gzip_after_days
        self._retention_days = retention_days

    def run_once(self) -> dict[str, ArchiveResult]:
        os.makedirs(self._dir, exist_ok=True)
        results: dict[str, ArchiveResult] = {}
        for prefix, model, source_table, ev_attr, builder in _SOURCES:
            results[prefix] = self._export_source(prefix, model, source_table, ev_attr, builder)
        self._gzip_old_files()
        self._purge_old_files()
        return results

    def _export_source(self, prefix, model, source_table, ev_attr, builder) -> ArchiveResult:
        res = ArchiveResult(source=prefix)
        files: set[str] = set()
        last_ts, last_id = self._read_cursor(source_table)
        while True:
            with self._sf() as s:
                q = (select(model)
                     .order_by(model.ingested_at, model.id)
                     .limit(_BATCH))
                if last_ts is not None:
                    q = q.where(or_(
                        model.ingested_at > last_ts,
                        and_(model.ingested_at == last_ts, model.id > last_id),
                    ))
                rows = s.execute(q).scalars().all()
                # 在 session 開啟期間就把要用的欄位取出，避免 detached 存取
                batch = [(builder(r), getattr(r, ev_attr), r.ingested_at, r.id) for r in rows]
            if not batch:
                break
            written = self._write_batch(prefix, batch)
            files.update(written)
            last_ts, last_id = batch[-1][2], batch[-1][3]
            self._write_cursor(source_table, last_ts, last_id)
            res.rows += len(batch)
            if len(batch) < _BATCH:
                break
        res.files_written = sorted(files)
        return res

    def _write_batch(self, prefix, batch) -> set[str]:
        # 依事件時間 UTC 日分組，一批可落在多個日期檔
        by_day: dict[str, list[bytes]] = {}
        for record, ev_time, _ing, _rid in batch:
            # 分日與序列化共用同一 UTC 正規化 helper，避免同根因的 naive-datetime bug 分兩處修
            day = _as_utc(ev_time).astimezone(timezone.utc).strftime("%Y-%m-%d")
            by_day.setdefault(day, []).append(orjson.dumps(record))
        written: set[str] = set()
        for day, lines in by_day.items():
            path = os.path.join(self._dir, f"{prefix}-{day}.jsonl")
            with open(path, "ab") as fh:
                for ln in lines:
                    fh.write(ln)
                    fh.write(b"\n")
                fh.flush()
                os.fsync(fh.fileno())
            written.add(path)
        return written

    def _read_cursor(self, source_table) -> tuple[datetime | None, int | None]:
        with self._sf() as s:
            cur = s.get(IngestionCursor, (_CONSUMER, source_table))
        if cur is None:
            return (None, None)
        return (cur.last_ingested_at, cur.last_row_id)

    def _write_cursor(self, source_table, ts: datetime, row_id: int) -> None:
        now = datetime.now(timezone.utc)
        with self._sf.begin() as s:
            cur = s.get(IngestionCursor, (_CONSUMER, source_table))
            if cur is None:
                cur = IngestionCursor(consumer=_CONSUMER, source_table=source_table,
                                      updated_at=now)
                s.add(cur)
            cur.last_ingested_at = ts
            cur.last_row_id = row_id
            cur.updated_at = now

    def _gzip_old_files(self) -> None:
        cutoff = time.time() - self._gzip_after_days * 86400
        try:
            names = os.listdir(self._dir)
        except OSError as exc:
            # best-effort 清理：目錄不存在/無權限/非目錄等任何列目錄失敗都安全跳過，不中斷 archive job
            logger.warning("archive gzip skipped {} (listdir failed): {}", self._dir, exc)
            return
        for name in names:
            if not name.endswith(".jsonl"):
                continue
            path = os.path.join(self._dir, name)
            try:
                if os.path.getmtime(path) >= cutoff:
                    continue
                gz_path = path + ".gz"
                # 既有 .gz 用 append 成新 gzip member，保留舊資料；多-member gzip
                # 標準工具可透明解壓。"wb" 會截斷覆寫既有內容，故僅在無既有 .gz 時使用。
                mode = "ab" if os.path.exists(gz_path) else "wb"
                with open(path, "rb") as src, gzip.open(gz_path, mode) as dst:
                    while True:
                        chunk = src.read(1 << 20)
                        if not chunk:
                            break
                        dst.write(chunk)
                    dst.flush()
                    os.fsync(dst.fileno())
                os.remove(path)  # 只有 .gz 成功寫入後才刪原檔
            except OSError as exc:
                logger.warning("archive gzip skipped {}: {}", path, exc)

    def _purge_old_files(self) -> None:
        # retention_days=0（或負）→ 永久保留，不刪任何 archive 檔。
        if self._retention_days <= 0:
            return
        cutoff = datetime.now(timezone.utc).date() - timedelta(days=self._retention_days)
        try:
            names = os.listdir(self._dir)
        except OSError as exc:
            logger.warning("archive purge skipped {} (listdir failed): {}", self._dir, exc)
            return
        for name in names:
            m = _ARCHIVE_NAME.match(name)
            if not m:
                continue
            try:
                file_date = date.fromisoformat(m.group(1))
            except ValueError:
                continue
            # 依「檔名事件日」判斷（非 mtime）：只刪事件日早於保存期界線的 archive 檔。
            if file_date < cutoff:
                path = os.path.join(self._dir, name)
                try:
                    os.remove(path)
                except OSError as exc:
                    logger.warning("archive purge skipped {}: {}", path, exc)
