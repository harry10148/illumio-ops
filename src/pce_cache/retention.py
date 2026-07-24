from __future__ import annotations

from datetime import datetime, timezone, timedelta

from loguru import logger
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from src.pce_cache.models import (
    DeadLetter, IngestionCursor, PceEvent, PceTrafficFlowAgg,
    PceTrafficFlowRaw, SiemDispatch,
)


class RetentionWorker:
    # 每批一個交易：避免單一大 DELETE 交易撐爆 WAL、長時間佔住
    # cache_writer。以 PK id 選批（LIMIT 子查詢先取 id 再 IN 刪除），
    # 與索引無關、總效果與一次性 DELETE 等價。
    _DELETE_BATCH = 10000

    def __init__(self, session_factory: sessionmaker):
        self._sf = session_factory

    def _batched_delete(self, model, *where_clauses) -> int:
        total = 0
        while True:
            with self._sf.begin() as s:
                ids = s.execute(
                    select(model.id).where(*where_clauses).limit(self._DELETE_BATCH)
                ).scalars().all()
                if not ids:
                    return total
                r = s.execute(delete(model).where(model.id.in_(ids)))
                total += r.rowcount
            if len(ids) < self._DELETE_BATCH:
                return total

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

        with self._sf() as s:
            eff_events = self._effective_cutoff(
                s, "pce_events", now - timedelta(days=events_days), archive_enabled)
        results["events"] = (
            0 if eff_events is None
            else self._batched_delete(
                PceEvent, PceEvent.ingested_at < eff_events,
                *self._siem_unreferenced_clauses(PceEvent, "pce_events")))
        if eff_events is not None:
            self._warn_siem_withheld(PceEvent, "pce_events", eff_events)

        with self._sf() as s:
            eff_raw = self._effective_cutoff(
                s, "pce_traffic_flows_raw", now - timedelta(days=traffic_raw_days), archive_enabled)
        results["traffic_raw"] = (
            0 if eff_raw is None
            else self._batched_delete(
                PceTrafficFlowRaw, PceTrafficFlowRaw.ingested_at < eff_raw,
                *self._siem_unreferenced_clauses(PceTrafficFlowRaw, "pce_traffic_flows_raw")))
        if eff_raw is not None:
            self._warn_siem_withheld(PceTrafficFlowRaw, "pce_traffic_flows_raw", eff_raw)

        results["traffic_agg"] = self._batched_delete(
            PceTrafficFlowAgg,
            PceTrafficFlowAgg.bucket_day < now - timedelta(days=traffic_agg_days))

        results["dead_letter"] = self._batched_delete(
            DeadLetter, DeadLetter.quarantined_at < now - timedelta(days=dlq_days))

        # siem_dispatch grows one row per record per destination and is never
        # otherwise pruned — the dispatcher only flips status pending→sent. So
        # delivered rows accumulate forever, long after the underlying raw
        # flows are deleted at 7 days, bloating the DB and the dispatch
        # indexes/COUNT queries. Purge delivered ('sent') rows past the
        # cutoff; leave pending/failed (retry/DLQ candidates) untouched. Their
        # NULL sent_at is excluded by the `< cutoff` comparison anyway.
        results["siem_dispatch"] = self._batched_delete(
            SiemDispatch,
            SiemDispatch.status == "sent",
            SiemDispatch.sent_at < now - timedelta(days=dispatch_days))

        return results

    @staticmethod
    def _siem_reference_subqueries(source_table: str):
        """仍會回讀來源列的 SIEM 端引用：未送達的 dispatch（dispatcher 於送出
        時才以 (source_table, source_id) 重讀 raw_json 建 payload）與 DLQ
        （replay 只重新 enqueue 同一組 key）。"""
        pending = select(SiemDispatch.source_id).where(
            SiemDispatch.source_table == source_table,
            SiemDispatch.status != "sent",
        )
        dlq = select(DeadLetter.source_id).where(
            DeadLetter.source_table == source_table)
        return pending, dlq

    def _siem_unreferenced_clauses(self, model, source_table: str):
        """來源列到期仍被 pending dispatch / DLQ 引用時不可刪：dlq_days(30)/
        dispatch_days(14) 皆大於 traffic_raw_days(7)，若照 ingested_at 直刪，
        replay/補送會找不到來源列而以 payload_build_failed 二次進 DLQ——資料
        對 SIEM 永久遺失。排除被引用的列，待送達（sent）或 DLQ 到期後自然可刪。"""
        pending, dlq = self._siem_reference_subqueries(source_table)
        return (model.id.not_in(pending), model.id.not_in(dlq))

    def _warn_siem_withheld(self, model, source_table: str, cutoff: datetime) -> None:
        """被 SIEM 引用而暫緩刪除的到期列數——不可靜默（操作者要能察覺
        dispatch/DLQ 積壓正在拖住 retention）。"""
        pending, dlq = self._siem_reference_subqueries(source_table)
        with self._sf() as s:
            n = s.execute(
                select(func.count()).select_from(model).where(
                    model.ingested_at < cutoff,
                    or_(model.id.in_(pending), model.id.in_(dlq)),
                )
            ).scalar() or 0
        if n:
            logger.warning(
                "retention guard: withholding {} expired {} rows still referenced "
                "by pending SIEM dispatch/DLQ entries",
                n, source_table,
            )

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
