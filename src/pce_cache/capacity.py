"""容量監控：DB 大小、磁碟剩餘、SIEM 佇列深度、archiver 落後。

全部唯讀且輕量（COUNT 走 status 索引、getsize/disk_usage 是 stat 呼叫），
供排程 job（run_capacity_monitor）與 /api/cache/health 共用。"""
from __future__ import annotations

import os
import shutil

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from src.i18n import t
from src.pce_cache.models import (
    IngestionCursor, PceEvent, PceTrafficFlowRaw, SiemDispatch,
)

_ARCHIVE_SOURCES = (
    ("traffic", PceTrafficFlowRaw, "pce_traffic_flows_raw"),
    ("audit", PceEvent, "pce_events"),
)


def capacity_snapshot(session_factory: sessionmaker, cfg) -> dict:
    db_path = cfg.db_path
    db_bytes = 0
    for suffix in ("", "-wal", "-shm"):
        try:
            db_bytes += os.path.getsize(db_path + suffix)
        except FileNotFoundError:
            pass  # -wal/-shm 不存在是常態（checkpoint 後）
        except OSError as exc:
            # 其他 stat 失敗（權限等）少算 db_bytes 會抑制容量告警——要看得見
            logger.warning("capacity stat failed for {}{}: {}", db_path, suffix, exc)
    try:
        disk_free_bytes = shutil.disk_usage(
            os.path.dirname(os.path.abspath(db_path))).free
    except OSError:
        disk_free_bytes = None

    with session_factory() as s:
        siem_pending = s.execute(
            select(func.count()).select_from(SiemDispatch)
            .where(SiemDispatch.status == "pending")).scalar() or 0
        archiver_lag: dict[str, int | None] = {}
        if getattr(cfg, "archive_enabled", False):
            for source, model, table in _ARCHIVE_SOURCES:
                newest = s.execute(select(func.max(model.ingested_at))).scalar()
                cur = s.get(IngestionCursor, ("archiver", table))
                archived = cur.last_ingested_at if cur else None
                if newest is None:
                    archiver_lag[source] = 0       # 沒資料就沒有落後
                elif archived is None:
                    archiver_lag[source] = None    # 有資料但從未封存
                else:
                    # SQLite 讀回皆為 naive UTC wall-clock，直接相減即可
                    archiver_lag[source] = max(
                        0, int((newest - archived).total_seconds()))

    return {
        "db_bytes": db_bytes,
        "disk_free_bytes": disk_free_bytes,
        "siem_pending": siem_pending,
        "archiver_lag_seconds": archiver_lag,
    }


def capacity_warnings(snap: dict, cfg) -> list[str]:
    msgs = []
    free = snap.get("disk_free_bytes")
    warn_gb = int(getattr(cfg, "disk_free_warn_gb", 10))
    if free is not None and free < warn_gb * (1 << 30):
        msgs.append(t("alert_cache_disk_low",
                      free_gb=round(free / (1 << 30), 1), warn_gb=warn_gb))

    pending_warn = int(getattr(cfg, "siem_pending_warn_rows", 50000))
    if snap.get("siem_pending", 0) > pending_warn:
        msgs.append(t("alert_siem_backlog",
                      pending=snap["siem_pending"], warn=pending_warn))

    # 落後超過 2 個 archive 週期，或從未封存（None），都要告警——
    # retention 守門會因此完全停刪，DB 將無上限成長。
    lag_warn = int(getattr(cfg, "archive_interval_hours", 24)) * 2 * 3600
    for source, lag in (snap.get("archiver_lag_seconds") or {}).items():
        if lag is None or lag > lag_warn:
            msgs.append(t("alert_archiver_behind", source=source,
                          hours=("n/a" if lag is None else round(lag / 3600, 1))))
    return msgs
