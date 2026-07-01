from __future__ import annotations

import gzip
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import orjson
from loguru import logger
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import IngestionCursor, PceEvent, PceTrafficFlowRaw

_BATCH = 5000
_CONSUMER = "archiver"


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
    def __init__(self, session_factory: sessionmaker, archive_dir: str,
                 gzip_after_days: int = 7):
        self._sf = session_factory
        self._dir = archive_dir
        self._gzip_after_days = gzip_after_days

    def run_once(self) -> dict[str, ArchiveResult]:
        os.makedirs(self._dir, exist_ok=True)
        results: dict[str, ArchiveResult] = {}
        for prefix, model, source_table, ev_attr, builder in _SOURCES:
            results[
                "traffic" if prefix == "traffic" else "audit"
            ] = self._export_source(prefix, model, source_table, ev_attr, builder)
        self._gzip_old_files()
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
        # Task 3 實作；本任務先 no-op，鎖定簽章。
        return None
