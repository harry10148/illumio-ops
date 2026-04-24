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
    ):
        self._name = name
        self._sf = session_factory
        self._formatter = formatter
        self._transport = transport
        self._max_retries = max_retries
        self._batch_size = batch_size
        self._lock = threading.Lock()

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

        for dispatch_row in rows:
            payload = self._build_payload(dispatch_row)
            if payload is None:
                continue
            try:
                self._transport.send(payload)
                with self._sf.begin() as s:
                    s.execute(
                        update(SiemDispatch)
                        .where(SiemDispatch.id == dispatch_row.id)
                        .values(status="sent", sent_at=datetime.now(timezone.utc))
                    )
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

        return {"sent": sent, "failed": failed, "quarantined": quarantined}

    def _build_payload(self, row: SiemDispatch) -> Optional[str]:
        try:
            with self._sf() as s:
                if row.source_table == "pce_events":
                    src = s.get(PceEvent, row.source_id)
                    if src is None:
                        return None
                    data = orjson.loads(src.raw_json)
                    return self._formatter.format_event(data)
                elif row.source_table == "pce_traffic_flows_raw":
                    src = s.get(PceTrafficFlowRaw, row.source_id)
                    if src is None:
                        return None
                    data = orjson.loads(src.raw_json)
                    return self._formatter.format_flow(data)
        except Exception as exc:
            logger.exception("Failed to build payload for dispatch row {}: {}", row.id, exc)
        return None

    def _quarantine(self, row: SiemDispatch, payload: str, error: str) -> None:
        now = datetime.now(timezone.utc)
        with self._sf.begin() as s:
            s.add(DeadLetter(
                source_table=row.source_table,
                source_id=row.source_id,
                destination=self._name,
                retries=row.retries + 1,
                last_error=error[:4000],
                payload_preview=payload[:512],
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
    from src.siem.formatters.json_line import JSONLineFormatter
    return CEFFormatter() if dest_cfg.format.startswith("cef") else JSONLineFormatter()


def _transport_for(dest_cfg):
    """Build transport from SiemDestinationSettings."""
    transport_type = dest_cfg.transport.lower()
    host, _, port_str = dest_cfg.endpoint.rpartition(":")
    port = int(port_str) if port_str.isdigit() else 514
    if not host:
        host = dest_cfg.endpoint
    if transport_type == "udp":
        from src.siem.transports.syslog_udp import SyslogUDPTransport
        return SyslogUDPTransport(host, port)
    elif transport_type == "tcp":
        from src.siem.transports.syslog_tcp import SyslogTCPTransport
        return SyslogTCPTransport(host, port)
    elif transport_type == "tls":
        from src.siem.transports.syslog_tls import SyslogTLSTransport
        return SyslogTLSTransport(host, port, tls_verify=dest_cfg.tls_verify)
    elif transport_type == "hec":
        from src.siem.transports.splunk_hec import SplunkHECTransport
        return SplunkHECTransport(dest_cfg.endpoint, token=dest_cfg.hec_token or "")
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
    """Enqueue cache rows not yet in siem_dispatch. Returns count of new rows created."""
    if not destinations:
        return 0

    total = 0
    pairs: list[tuple[str, type]] = [
        ("pce_events", PceEvent),
        ("pce_traffic_flows_raw", PceTrafficFlowRaw),
    ]
    for source_table, model in pairs:
        with session_factory() as s:
            already = set(
                s.execute(
                    select(SiemDispatch.source_id).where(
                        SiemDispatch.source_table == source_table
                    )
                ).scalars().all()
            )
            if already:
                new_ids = s.execute(
                    select(model.id).where(model.id.not_in(already))
                ).scalars().all()
            else:
                new_ids = s.execute(
                    select(model.id)
                ).scalars().all()
        for source_id in new_ids:
            enqueue(session_factory, source_table, source_id, destinations)
            total += 1
    return total
