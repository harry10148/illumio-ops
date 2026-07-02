from __future__ import annotations

from datetime import datetime, timezone, timedelta

from loguru import logger
from sqlalchemy import delete
from sqlalchemy.orm import Session, sessionmaker

from src.pce_cache.models import (
    DeadLetter, IngestionCursor, PceEvent, PceTrafficFlowAgg,
    PceTrafficFlowRaw, SiemDispatch,
)


class RetentionWorker:
    def __init__(self, session_factory: sessionmaker):
        self._sf = session_factory

    def run_once(
        self,
        events_days: int = 90,
        traffic_raw_days: int = 7,
        traffic_agg_days: int = 90,
        dlq_days: int = 30,
        dispatch_days: int = 14,
        archive_enabled: bool = False,
    ) -> dict[str, int]:
        """刪除依 ingested_at 早於保留期限的列（見下方 delete）。

        F6：ingest 端 re-pull 既有 flow 時會把 ingested_at bump 到本次 ingest
        時間（ingestor_traffic.py）。這會連帶延長該列在這裡的存活期限——
        語意上是合理的：一筆持續被 re-pull（代表仍活躍）的 flow，本就不該
        被當成陳舊資料清掉；只有真正不再出現在 PCE 回應裡的 flow，其
        ingested_at 才會停止推進、如常在保留期限到期後被刪除。"""
        now = datetime.now(timezone.utc)
        results: dict[str, int] = {}

        with self._sf.begin() as s:
            policy_cutoff = now - timedelta(days=events_days)
            eff = self._effective_cutoff(s, "pce_events", policy_cutoff, archive_enabled)
            if eff is None:
                results["events"] = 0
            else:
                r = s.execute(delete(PceEvent).where(PceEvent.ingested_at < eff))
                results["events"] = r.rowcount

        with self._sf.begin() as s:
            policy_cutoff = now - timedelta(days=traffic_raw_days)
            eff = self._effective_cutoff(s, "pce_traffic_flows_raw", policy_cutoff, archive_enabled)
            if eff is None:
                results["traffic_raw"] = 0
            else:
                r = s.execute(delete(PceTrafficFlowRaw).where(PceTrafficFlowRaw.ingested_at < eff))
                results["traffic_raw"] = r.rowcount

        with self._sf.begin() as s:
            cutoff = now - timedelta(days=traffic_agg_days)
            r = s.execute(delete(PceTrafficFlowAgg).where(PceTrafficFlowAgg.bucket_day < cutoff))
            results["traffic_agg"] = r.rowcount

        with self._sf.begin() as s:
            cutoff = now - timedelta(days=dlq_days)
            r = s.execute(delete(DeadLetter).where(DeadLetter.quarantined_at < cutoff))
            results["dead_letter"] = r.rowcount

        with self._sf.begin() as s:
            # siem_dispatch grows one row per record per destination and is never
            # otherwise pruned — the dispatcher only flips status pending→sent. So
            # delivered rows accumulate forever, long after the underlying raw
            # flows are deleted at 7 days, bloating the DB and the dispatch
            # indexes/COUNT queries. Purge delivered ('sent') rows past the
            # cutoff; leave pending/failed (retry/DLQ candidates) untouched. Their
            # NULL sent_at is excluded by the `< cutoff` comparison anyway.
            cutoff = now - timedelta(days=dispatch_days)
            r = s.execute(delete(SiemDispatch).where(
                SiemDispatch.status == "sent",
                SiemDispatch.sent_at < cutoff,
            ))
            results["siem_dispatch"] = r.rowcount

        return results

    def _effective_cutoff(
        self,
        s: Session,
        source_table: str,
        policy_cutoff: datetime,
        archive_enabled: bool,
    ) -> datetime | None:
        """回傳實際刪除界線。archive_enabled=True 時，只刪「到期且已 archive」
        的列：界線取 min(policy_cutoff, archiver cursor 的 last_ingested_at)；
        cursor 為 None（尚未 archive 任何列）→ 回傳 None（該來源不刪）。"""
        if not archive_enabled:
            return policy_cutoff
        cur = s.get(IngestionCursor, ("archiver", source_table))
        archived_ts = cur.last_ingested_at if cur else None
        # SQLite 讀回的 DateTime(timezone=True) 是 naive（tzinfo 被剝除），
        # 其值為 UTC wall-clock，補回 UTC tzinfo 才能與 aware 的 policy_cutoff 比較。
        if archived_ts is not None and archived_ts.tzinfo is None:
            archived_ts = archived_ts.replace(tzinfo=timezone.utc)
        if archived_ts is None:
            logger.warning(
                "retention guard: nothing archived for {} yet; withholding deletion",
                source_table,
            )
            return None
        if archived_ts < policy_cutoff:
            logger.warning(
                "retention guard: archive behind for {} (archived up to {} < policy {}); "
                "withholding un-archived rows",
                source_table, archived_ts, policy_cutoff,
            )
        return min(policy_cutoff, archived_ts)
