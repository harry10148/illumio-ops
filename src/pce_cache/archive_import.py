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
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _iter_lines(path: str):
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rb") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield line


class ArchiveImporter:
    """把 archive 的 traffic JSONL 逐行還原成 PceTrafficFlowRaw 灌進指定的 review DB。"""

    def __init__(self, archive_dir: str, session_factory: sessionmaker):
        self._dir = archive_dir
        self._sf = session_factory

    def import_range(self, start: date, end: date) -> dict:
        from src.report.parsers.api_parser import flatten_flow_record
        rows = files = skipped = 0
        try:
            names = sorted(os.listdir(self._dir))
        except OSError as exc:
            logger.warning("archive import: listdir {} failed: {}", self._dir, exc)
            names = []
        for name in names:
            m = _TRAFFIC_FILE.match(name)
            if not m:
                continue
            try:
                file_date = date.fromisoformat(m.group(1))
            except ValueError:
                continue
            if file_date < start or file_date > end:
                continue
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
