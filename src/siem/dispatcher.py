from __future__ import annotations

import threading
from datetime import datetime, timezone, timedelta
from typing import Optional

import orjson
from loguru import logger
from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import (
    DeadLetter, PceEvent, PceTrafficFlowRaw, SiemDispatch,
)
from src.siem.formatters.base import Formatter
from src.siem.transports.base import Transport


def _backoff_seconds(retries: int) -> int:
    return min(2 ** retries * 5, 3600)


# SQLite 的 SQLITE_LIMIT_VARIABLE_NUMBER 預設為 999；批次標記 sent 時把
# id 清單切成 ≤ 此值一組，避免 batch_size 調高（config 允許到 10000）時
# 觸發 "too many SQL variables"。仍在同一 transaction 內完成（每 tick 一次 commit）。
_SENT_UPDATE_CHUNK = 900


class DestinationDispatcher:
    """Dispatcher for a single SIEM destination."""

    def __init__(
        self,
        name: str,
        session_factory: sessionmaker,
        formatter: Formatter,
        transport: Transport,
        max_retries: int = 10,
        batch_size: int = 100,
        mask_pii: bool = False,
        dlq_max: int = 10000,
    ):
        self._name = name
        self._sf = session_factory
        self._formatter = formatter
        self._transport = transport
        self._max_retries = max_retries
        self._batch_size = batch_size
        self._mask_pii = mask_pii
        self._dlq_max = dlq_max
        self._lock = threading.Lock()

    def close(self) -> None:
        """Release transport resources (connection pool)."""
        if hasattr(self._transport, "close"):
            try:
                self._transport.close()
            except Exception as exc:
                logger.warning("transport close failed for {!r}: {}", self._name, exc)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def tick(self) -> dict[str, int]:
        """Process one batch. Returns {sent, failed, quarantined}."""
        if not self._lock.acquire(blocking=False):
            return {"sent": 0, "failed": 0, "quarantined": 0}
        try:
            return self._process_batch()
        finally:
            self._lock.release()

    def _process_batch(self) -> dict[str, int]:
        now = datetime.now(timezone.utc)
        sent = failed = quarantined = 0
        sent_ids: list[int] = []

        with self._sf() as s:
            rows = s.execute(
                select(SiemDispatch)
                .where(SiemDispatch.destination == self._name)
                .where(SiemDispatch.status == "pending")
                .where(
                    (SiemDispatch.next_attempt_at == None) |  # noqa: E711
                    (SiemDispatch.next_attempt_at <= now)
                )
                .order_by(SiemDispatch.queued_at)
                .limit(self._batch_size)
            ).scalars().all()
            # 單一 session 批次載入本批的 source rows（原本每列各開一個
            # session —— NullPool 下 batch=100 就是 100 條新 SQLite 連線）。
            sources = self._load_sources(s, rows)

        for dispatch_row in rows:
            payload = self._build_payload(
                dispatch_row, sources.get((dispatch_row.source_table, dispatch_row.source_id))
            )
            if payload is None:
                # Route build failures through the DLQ (not a bare status='failed')
                # so the dropped event stays inspectable and replayable.
                self._quarantine(dispatch_row, None, "payload_build_failed")
                quarantined += 1
                continue
            try:
                self._transport.send(payload)
                sent_ids.append(dispatch_row.id)
                sent += 1
            except Exception as exc:
                logger.warning("SIEM dispatch failed for row {}: {}", dispatch_row.id, exc)
                new_retries = dispatch_row.retries + 1
                if new_retries >= self._max_retries:
                    self._quarantine(dispatch_row, payload, str(exc))
                    quarantined += 1
                else:
                    next_at = datetime.now(timezone.utc) + timedelta(
                        seconds=_backoff_seconds(new_retries)
                    )
                    with self._sf.begin() as s:
                        s.execute(
                            update(SiemDispatch)
                            .where(SiemDispatch.id == dispatch_row.id)
                            .values(retries=new_retries, next_attempt_at=next_at)
                        )
                    failed += 1

        # 成功送出的列以單一 transaction 一次標記 sent（原本逐列 commit 是
        # 與 ingest 對撞的主要寫鎖 churn）。若 process 在網路送出後、此
        # commit 前崩潰，那些列下輪會重送 —— 重複交付窗口因此變寬。
        # 這是刻意的 at-least-once 取捨：SIEM 本即 at-least-once，
        # 使用者已同意 eventual。
        if sent_ids:
            sent_at = datetime.now(timezone.utc)
            with self._sf.begin() as s:
                for i in range(0, len(sent_ids), _SENT_UPDATE_CHUNK):
                    chunk = sent_ids[i:i + _SENT_UPDATE_CHUNK]
                    s.execute(
                        update(SiemDispatch)
                        .where(SiemDispatch.id.in_(chunk))
                        .values(status="sent", sent_at=sent_at)
                    )

        return {"sent": sent, "failed": failed, "quarantined": quarantined}

    _SOURCE_MODELS = {
        "pce_events": PceEvent,
        "pce_traffic_flows_raw": PceTrafficFlowRaw,
    }

    def _load_sources(self, s, rows: list[SiemDispatch]) -> dict[tuple[str, int], str]:
        """依 source_table 分組後對本批 source_id 各發一次 IN 查詢，取回
        raw_json（_build_payload 唯一用到的欄位，column-only select 同時省
        去 report_json 等未用欄位）。缺列的 (source_table, source_id) 不會
        出現在回傳的 dict 中 —— _build_payload 以此判斷缺 source row，維持
        原本『找不到就回 None』的語意。
        """
        ids_by_table: dict[str, list[int]] = {}
        for r in rows:
            ids_by_table.setdefault(r.source_table, []).append(r.source_id)

        loaded: dict[tuple[str, int], str] = {}
        for table_name, ids in ids_by_table.items():
            model = self._SOURCE_MODELS.get(table_name)
            if model is None:
                continue
            for i in range(0, len(ids), _SENT_UPDATE_CHUNK):
                chunk = ids[i:i + _SENT_UPDATE_CHUNK]
                for src_id, raw_json in s.execute(
                    select(model.id, model.raw_json).where(model.id.in_(chunk))
                ):
                    loaded[(table_name, src_id)] = raw_json
        return loaded

    def _build_payload(self, row: SiemDispatch, raw_json: Optional[str]) -> Optional[str]:
        if raw_json is None:
            return None
        try:
            data = orjson.loads(raw_json)
            if row.source_table == "pce_events":
                if self._mask_pii:
                    from src.siem.mask import mask_event
                    data = mask_event(data, mask_pii=True)
                return self._formatter.format_event(data)
            elif row.source_table == "pce_traffic_flows_raw":
                if self._mask_pii:
                    from src.siem.mask import mask_flow
                    data = mask_flow(data, mask_pii=True)
                return self._formatter.format_flow(data)
        except Exception as exc:
            logger.exception("Failed to build payload for dispatch row {}: {}", row.id, exc)
        return None

    def _quarantine(self, row: SiemDispatch, payload: Optional[str], error: str) -> None:
        now = datetime.now(timezone.utc)
        with self._sf.begin() as s:
            s.add(DeadLetter(
                source_table=row.source_table,
                source_id=row.source_id,
                destination=self._name,
                retries=row.retries + 1,
                last_error=error[:4000],
                payload_preview=payload[:512] if payload else "",
                quarantined_at=now,
            ))
            # dlq_max_per_dest：ring-buffer 語意，超過上限即刪最舊項目，
            # 否則持續失敗的目的地會讓 dead_letter 無上限成長。
            if self._dlq_max and self._dlq_max > 0:
                s.flush()
                excess_ids = s.execute(
                    select(DeadLetter.id)
                    .where(DeadLetter.destination == self._name)
                    .order_by(DeadLetter.quarantined_at.desc(), DeadLetter.id.desc())
                    .offset(self._dlq_max)
                ).scalars().all()
                if excess_ids:
                    s.execute(delete(DeadLetter).where(DeadLetter.id.in_(excess_ids)))
                    logger.warning(
                        "SIEM DLQ cap ({}) reached for {!r}: pruned {} oldest entries",
                        self._dlq_max, self._name, len(excess_ids),
                    )
            s.execute(
                update(SiemDispatch)
                .where(SiemDispatch.id == row.id)
                .values(status="failed")
            )


def _formatter_for(dest_cfg):
    """Build formatter from SiemDestinationSettings."""
    from src.siem.formatters.cef import CEFFormatter
    from src.siem.formatters.normalized_json import NormalizedJSONFormatter
    from src.siem.formatters.syslog_wrapped import SyslogWrappedFormatter
    fmt = dest_cfg.format
    if fmt == "cef":
        return CEFFormatter()
    if fmt == "syslog_cef":
        return SyslogWrappedFormatter(CEFFormatter())
    if fmt == "syslog_json":
        return SyslogWrappedFormatter(NormalizedJSONFormatter())
    return NormalizedJSONFormatter()


def _transport_for(dest_cfg):
    """Build transport from SiemDestinationSettings."""
    transport_type = dest_cfg.transport.lower()
    host = dest_cfg.host
    port = dest_cfg.port
    if transport_type == "udp":
        from src.siem.transports.syslog_udp import SyslogUDPTransport
        return SyslogUDPTransport(host, port)
    elif transport_type == "tcp":
        from src.siem.transports.syslog_tcp import SyslogTCPTransport
        return SyslogTCPTransport(host, port)
    elif transport_type == "tls":
        from src.siem.transports.syslog_tls import SyslogTLSTransport
        return SyslogTLSTransport(
            host, port,
            tls_verify=dest_cfg.tls_verify,
            ca_bundle=dest_cfg.tls_ca_bundle,
        )
    elif transport_type == "hec":
        from src.siem.transports.splunk_hec import SplunkHECTransport
        url = f"https://{host}:{port}"
        return SplunkHECTransport(
            url,
            token=dest_cfg.hec_token or "",
            verify_tls=dest_cfg.tls_verify,
        )
    raise ValueError(f"Unknown transport: {transport_type}")


def build_dispatcher(dest_cfg, session_factory, dlq_max_per_dest: int = 10000) -> "DestinationDispatcher":
    """Build a DestinationDispatcher from a SiemDestinationSettings instance.

    dlq_max_per_dest 是全域 SiemSettings 欄位（非 per-destination），由呼叫端
    帶入；預設值與 config_models.SiemSettings.dlq_max_per_dest 一致。
    """
    return DestinationDispatcher(
        name=dest_cfg.name,
        session_factory=session_factory,
        formatter=_formatter_for(dest_cfg),
        transport=_transport_for(dest_cfg),
        max_retries=dest_cfg.max_retries,
        batch_size=dest_cfg.batch_size,
        mask_pii=bool(getattr(dest_cfg, "mask_pii", False)),
        dlq_max=dlq_max_per_dest,
    )


def enqueue(
    session_factory: sessionmaker,
    source_table: str,
    source_id: int,
    destinations: list[str],
) -> None:
    """Create one siem_dispatch row per destination for a newly-ingested record."""
    now = datetime.now(timezone.utc)
    with session_factory.begin() as s:
        for dest in destinations:
            s.add(SiemDispatch(
                source_table=source_table,
                source_id=source_id,
                destination=dest,
                status="pending",
                retries=0,
                queued_at=now,
            ))


# 補登 insert 的 chunk 大小，比照 repo 既有慣例（ingestor_events/traffic、
# archive_import 皆用 500）。
_ENQUEUE_CHUNK = 500


def enqueue_new_records(
    session_factory: sessionmaker,
    destinations_by_source_table: dict[str, list[str]],
) -> int:
    """Safety-net backfill: enqueue any (cache row, destination) pairs that
    ingestors didn't enqueue inline.

    Ingestors enqueue rows in the same transaction as the cache write, so this
    function should normally find nothing. It exists to cover (a) a
    destination being newly added/enabled for a source_type — historical rows
    of that source_type were never enqueued to it, even if the same cache row
    already has dispatch rows for other destinations — (b) crash recovery,
    and (c) operator-driven backfill.

    The anti-join is scoped per (source_table, source_id, destination), not
    just per (source_table, source_id): a row already dispatched to
    destination A is still eligible for backfill to newly-enabled destination
    B if it lacks a B row. at-least-once semantics for a given
    (row, destination) pair are unchanged — the anti-join still guards
    against re-enqueuing a pair that already has a dispatch row.

    destinations_by_source_table maps source_table (e.g. "pce_events") to the
    destination names already filtered to that source_table's source_type
    (see scheduler.jobs._enabled_siem_destinations). This mirrors the
    ingest-side filter so, e.g., an audit-only destination is never backfilled
    a traffic row and vice versa.

    Steady-state cost: exactly one full scan of each source table per call,
    independent of the number of destinations. This runs unconditionally
    every dispatch tick (default 30s), so the candidate scan folds all
    destinations' NOT EXISTS into a single OR'd query (phase 1); only the
    normally-empty candidate set pays a second, indexed per-destination
    resolution (phase 2).

    All new rows are inserted within a single transaction (chunked to respect
    SQLite's bound-parameter cap), not one transaction per row — backfilling a
    large cache on first SIEM enable would otherwise be a per-row fsync storm.

    Returns count of new dispatch rows created.
    """
    pairs: list[tuple[str, type]] = [
        ("pce_events", PceEvent),
        ("pce_traffic_flows_raw", PceTrafficFlowRaw),
    ]
    to_enqueue: list[tuple[str, int, str]] = []  # (source_table, source_id, destination)
    with session_factory() as s:
        for source_table, model in pairs:
            dests = destinations_by_source_table.get(source_table) or []
            if not dests:
                continue

            def _dispatched_to(dest: str):
                # Anti-join 帶 destination 條件：曾為其他 destination enqueue
                # 過的 row，對新啟用的 destination 仍補得到；同一
                # (row, destination) pair 則被擋住。相比舊版「載入全部
                # dispatched id + `id NOT IN (...)`」，correlated NOT EXISTS
                # 也不會撞 SQLite 變數上限。
                return (
                    select(SiemDispatch.id)
                    .where(
                        SiemDispatch.source_table == source_table,
                        SiemDispatch.source_id == model.id,
                        SiemDispatch.destination == dest,
                    )
                    .exists()
                )

            # Phase 1：單次全表掃描找候選 —— 缺「任一」destination dispatch
            # row 的 source rows（全部 destination 的 NOT EXISTS 以 OR 合併）。
            # 正常情況（ingest 已 inline enqueue）回空集合，直接結束。
            candidates = s.execute(
                select(model.id).where(
                    or_(*[~_dispatched_to(dest) for dest in dests])
                )
            ).scalars().all()
            if not candidates:
                continue

            # Phase 2：僅對候選 id 精確判定缺哪些 (id, destination) pair。
            # 以 chunked `id IN (...)` 走 ix_dispatch_source 索引查既有
            # pair，再於 Python 補集 —— 成本與候選數成正比，與全表無關。
            dest_set = set(dests)
            for i in range(0, len(candidates), _SENT_UPDATE_CHUNK):
                chunk = candidates[i:i + _SENT_UPDATE_CHUNK]
                existing = set(
                    s.execute(
                        select(SiemDispatch.source_id, SiemDispatch.destination)
                        .where(
                            SiemDispatch.source_table == source_table,
                            SiemDispatch.source_id.in_(chunk),
                            SiemDispatch.destination.in_(dest_set),
                        )
                    ).all()
                )
                to_enqueue.extend(
                    (source_table, sid, dest)
                    for sid in chunk
                    for dest in dests
                    if (sid, dest) not in existing
                )

    total = len(to_enqueue)
    if total:
        now = datetime.now(timezone.utc)
        with session_factory.begin() as s:
            for i in range(0, total, _ENQUEUE_CHUNK):
                chunk = to_enqueue[i:i + _ENQUEUE_CHUNK]
                s.add_all([
                    SiemDispatch(
                        source_table=source_table, source_id=source_id,
                        destination=dest, status="pending", retries=0,
                        queued_at=now,
                    )
                    for source_table, source_id, dest in chunk
                ])
                # 逐 chunk flush，使每個 INSERT 陳述式受 chunk 上限約束，
                # 但仍在同一 transaction 內（commit 只有一次）。
                s.flush()
        logger.info(
            "siem safety-net backfill enqueued {} (row, destination) pairs "
            "(ingestors should normally cover this; expected after "
            "destination add/enable or crash recovery)",
            total,
        )
    return total
