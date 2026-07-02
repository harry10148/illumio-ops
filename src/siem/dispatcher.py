from __future__ import annotations

import threading
from datetime import datetime, timezone, timedelta
from typing import Optional

import orjson
from loguru import logger
from sqlalchemy import select, update
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
    ):
        self._name = name
        self._sf = session_factory
        self._formatter = formatter
        self._transport = transport
        self._max_retries = max_retries
        self._batch_size = batch_size
        self._mask_pii = mask_pii
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


def build_dispatcher(dest_cfg, session_factory) -> "DestinationDispatcher":
    """Build a DestinationDispatcher from a SiemDestinationSettings instance."""
    return DestinationDispatcher(
        name=dest_cfg.name,
        session_factory=session_factory,
        formatter=_formatter_for(dest_cfg),
        transport=_transport_for(dest_cfg),
        max_retries=dest_cfg.max_retries,
        batch_size=dest_cfg.batch_size,
        mask_pii=bool(getattr(dest_cfg, "mask_pii", False)),
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


def enqueue_new_records(
    session_factory: sessionmaker,
    destinations: list[str],
) -> int:
    """Safety-net backfill: enqueue any cache rows that ingestors didn't enqueue inline.

    Ingestors enqueue rows in the same transaction as the cache write, so this
    function should normally find nothing. It exists to cover (a) destinations
    being newly added/enabled (historical rows weren't enqueued at write time),
    (b) crash recovery, and (c) operator-driven backfill.

    Returns count of new dispatch rows created.
    """
    if not destinations:
        return 0

    total = 0
    pairs: list[tuple[str, type]] = [
        ("pce_events", PceEvent),
        ("pce_traffic_flows_raw", PceTrafficFlowRaw),
    ]
    for source_table, model in pairs:
        with session_factory() as s:
            # SQL anti-join: cache rows that have no SiemDispatch row yet.
            # Previously this loaded the entire dispatched-id set into Python and
            # built `id NOT IN (... one bind per id ...)`, which on a large cache
            # blew past SQLite's variable cap (`too many SQL variables`) — the
            # job then failed every tick, hammering the DB. A correlated
            # NOT EXISTS lets SQLite do the anti-join with the
            # (source_table, source_id) index and no per-id binds.
            dispatched = (
                select(SiemDispatch.id)
                .where(
                    SiemDispatch.source_table == source_table,
                    SiemDispatch.source_id == model.id,
                )
                .exists()
            )
            new_ids = s.execute(
                select(model.id).where(~dispatched)
            ).scalars().all()
        for source_id in new_ids:
            enqueue(session_factory, source_table, source_id, destinations)
            total += 1
    if total:
        logger.info(
            "siem safety-net backfill enqueued {} rows (ingestors should normally cover this; "
            "expected after destination add/enable or crash recovery)",
            total,
        )
    return total
