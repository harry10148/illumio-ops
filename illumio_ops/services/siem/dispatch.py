"""Sending to SIEM destinations (spec §6.5 SIEM 轉送, P7): every tick, each enabled destination reads each of its
sources after its cursor, formats, sends and moves the cursor. At least once: a crash between a send and the cursor
write sends that batch again.

A destination that cannot be reached (connection refused, timeout, a 5xx) stops for this tick at the record that
failed — the rest of the batch is not tried, so they are not charged a failure (5.x circuit breaker) — and the next
tick starts there again. When the same record has failed max_retries times in a row, the next one is tried: if it goes
through, the first is what fails and goes to the DLQ, so one record a peer always drops cannot hold a destination
forever; if it fails too, the destination is down and nothing goes to the DLQ (5.x moved a record there every
max_retries ticks of an outage) — until the same record has failed STUCK_FACTOR times that often, when it goes anyway. A record the destination refuses for good (HTTP
4xx other than 408/429, a datagram too large) goes to the DLQ at once and the batch goes on. A full DLQ stops the
destination where it is: nothing is dropped, the status page says so. Nothing here holds a database connection while
sending: a slow SIEM never keeps a PCE switch waiting."""
from __future__ import annotations

import errno
import json
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from urllib.parse import urlsplit

import requests
from loguru import logger
from pydantic import BaseModel

from illumio_ops.domain.values import SiemFormat, SiemSource
from illumio_ops.services.context import AppContext
from illumio_ops.services.siem import sources
from illumio_ops.settings.schema import Settings, SiemDestination
from illumio_ops.siem.formatters.base import Formatter
from illumio_ops.siem.formatters.factory import formatter_for
from illumio_ops.siem.records import SiemRecord
from illumio_ops.siem.transports.base import Transport
from illumio_ops.siem.transports.factory import transport_for
from illumio_ops.store import siem as store

BUDGET_SHARE = 0.8
# A record that failed this many times max_retries goes to the DLQ even when nothing after it says whether the
# destination is down (a lone record a peer always drops must not hold the destination forever).
STUCK_FACTOR = 10          # of the tick: the next tick never starts behind this one
SYSLOG_HOST = "illumio-ops"  # the syslog host of this product's own events
IDENTITY_TTL = 3600.0
TransportFactory = Callable[[SiemDestination], Transport]

_RUN_LOCK = threading.Lock()
_identity: dict[str, tuple[float, str]] = {}


class SourceRun(BaseModel):
    sent: int = 0
    quarantined: int = 0
    error: str | None = None
    unreachable: bool = False   # the destination failed: its other sources wait for the next tick
    dlq_full: bool = False
    started: bool = False       # a new cursor was placed at the newest record


class SiemRun(BaseModel):
    destinations: dict[str, dict[str, SourceRun]] = {}
    skipped: bool = False       # another run was still going


def permanent(exc: BaseException) -> bool:
    """A refusal sending again will not change: HTTP 4xx (not 408 timeout or 429 rate limit), a datagram too large."""
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        code = exc.response.status_code
        return 400 <= code < 500 and code not in (408, 429)
    return isinstance(exc, OSError) and exc.errno == errno.EMSGSIZE


def _pce_version(ctx: AppContext, s: Settings) -> str:
    """The PCE's version for cef_pce's header (the PCE's own line carries it); asked at most hourly, 'unknown' when
    the PCE does not answer — it never stops forwarding."""
    url = s.pce.url
    hit = _identity.get(url)
    if hit and time.monotonic() - hit[0] < IDENTITY_TTL:
        return hit[1]
    version = "unknown"
    try:
        with ctx.pce_client(s.pce) as client:
            body = client.request("GET", "/product_version", org_scoped=False, timeout=10).json()
            if isinstance(body, dict) and body.get("version"):
                version = str(body["version"])
    except Exception as exc:  # noqa: BLE001 — the header is cosmetic: forwarding goes on without it
        logger.warning("SIEM: the PCE version for cef_pce could not be read ({}); the header says unknown", exc)
    _identity[url] = (time.monotonic(), version)
    return version


def _formatter(ctx: AppContext, s: Settings, dest: SiemDestination) -> Formatter:
    pce_native = dest.format in (SiemFormat.CEF_PCE, SiemFormat.SYSLOG_CEF_PCE, SiemFormat.CEF, SiemFormat.SYSLOG_CEF)
    version = _pce_version(ctx, s) if pce_native and SiemSource.AUDIT in dest.sources else "unknown"
    return formatter_for(dest.format, pce_fqdn=urlsplit(s.pce.url).hostname or "", pce_version=version,
                         host=SYSLOG_HOST)


def sent_as(dest: SiemDestination) -> str:
    """What a stored line was made for: a DLQ resend to a destination changed since (masking on, another host, another
    format) is not made — the line would carry what the destination now asks to leave out (P7 security review)."""
    return json.dumps([dest.transport.value, dest.host, dest.port, dest.format.value, dest.mask_pii])


def _event_time(rec: SiemRecord) -> float:
    return rec.time.timestamp()


def run_siem(ctx: AppContext, *, now: datetime | None = None, budget_seconds: float | None = None,
             transport_factory: TransportFactory = transport_for,
             clock: Callable[[], float] = time.monotonic) -> SiemRun:
    if not _RUN_LOCK.acquire(blocking=False):
        return SiemRun(skipped=True)
    try:
        s = ctx.settings.current()
        if not s.siem.enabled:
            return SiemRun()
        deadline = clock() + (budget_seconds if budget_seconds is not None else s.siem.tick_seconds * BUDGET_SHARE)
        out = SiemRun()
        for dest in s.siem.destinations:
            if dest.enabled:
                out.destinations[dest.name] = _run_destination(ctx, s, dest, deadline, transport_factory, clock,
                                                               now)
        return out
    finally:
        _RUN_LOCK.release()


def _run_destination(ctx: AppContext, s: Settings, dest: SiemDestination, deadline: float,
                     factory: TransportFactory, clock: Callable[[], float], now: datetime | None) -> dict[str, SourceRun]:
    results: dict[str, SourceRun] = {}
    try:
        transport = factory(dest)
        fmt = _formatter(ctx, s, dest)
    except Exception as exc:  # noqa: BLE001 — a destination that cannot be set up (a CA file gone) waits, said
        at = (now or datetime.now(UTC)).astimezone(UTC)
        with ctx.db() as conn:
            for source in sources.cursor_sources(dest):
                store.note_error(conn, dest.id, source, f"setup: {exc}", at)
        return {source: SourceRun(error=f"setup: {exc}", unreachable=True) for source in sources.cursor_sources(dest)}
    try:
        for source in sources.cursor_sources(dest):
            r = _run_source(ctx, s, dest, source, transport, fmt, deadline, clock, now)
            results[source] = r
            if r.unreachable:
                break
    finally:
        try:
            transport.close()
        except Exception as exc:  # noqa: BLE001 — closing a broken connection: nothing left to deliver
            logger.debug("SIEM destination {} close: {}", dest.name, exc)
    return results


def _quarantine(ctx: AppContext, s: Settings, dest: SiemDestination, source: str, rec: SiemRecord, payload: str,
                error: str, attempts: int, at: datetime) -> bool:
    """Into the DLQ; False (nothing written) when the destination's DLQ is full."""
    with ctx.db() as conn:
        if store.dlq_count(conn, dest.id) >= s.siem.dlq_max_per_dest:
            store.note_error(conn, dest.id, source, "dlq_full", at)
            return False
        store.quarantine(conn, destination_id=dest.id, source=source, record_id=rec.record_id,
                         external_id=rec.external_id, event_time=rec.time, payload=payload, sent_as=sent_as(dest),
                         error=error, attempts=attempts, at=at)
    logger.warning("SIEM destination {}: {} moved to the DLQ ({})", dest.name, rec.external_id, error)
    return True


def _next_goes_through(transport: Transport, fmt: Formatter, records: list[SiemRecord], head: SiemRecord) -> bool:
    """Tell a record that keeps failing from a destination that is down: send the next one. Nothing after it, or the
    next one fails too: the destination is down, and nothing goes to the DLQ (a SIEM down for a day would otherwise
    fill it with records that only waited)."""
    nxt = next((r for r in records if r.record_id > head.record_id), None)
    if nxt is None:
        return False
    try:
        transport.send_record(fmt.format_record(nxt), _event_time(nxt))
        transport.finish_batch()
    except Exception:  # noqa: BLE001 — the destination is down: wait for it
        return False
    return True


def _run_source(ctx: AppContext, s: Settings, dest: SiemDestination, source: str, transport: Transport,
                fmt: Formatter, deadline: float, clock: Callable[[], float], now: datetime | None) -> SourceRun:
    pce = s.pce
    run = SourceRun()
    with ctx.db() as conn:
        cur = store.get_cursor(conn, dest.id, source)
    if cur is None or (cur.pce_url, cur.org_id) != (pce.url, pce.org_id):
        # New, or counting another PCE's ids: what is stored now is history (spec §7) — start after it.
        newest = sources.newest_id(ctx, source)
        with ctx.db() as conn:
            store.start_cursor(conn, dest.id, source, pce_url=pce.url, org_id=pce.org_id, last_id=newest)
        return SourceRun(started=True)
    last = cur.last_id
    read = sources.SOURCES[source].read
    while clock() < deadline:
        records = read(ctx, last, dest.batch_size, dest)  # its connection is closed again before anything is sent
        if not records:
            break
        at = (now or datetime.now(UTC)).astimezone(UTC)
        consumed, sent, failure = last, 0, None
        payloads: dict[int, str] = {}
        for rec in records:
            try:
                payload = fmt.format_record(rec)
            except Exception as exc:  # noqa: BLE001 — a record that cannot be formatted must not stop the rest
                if not _quarantine(ctx, s, dest, source, rec, repr(rec)[:4000], f"format: {exc}", 1, at):
                    run.dlq_full = True
                    break
                run.quarantined += 1
                consumed = rec.record_id
                continue
            payloads[rec.record_id] = payload
            try:
                transport.send_record(payload, _event_time(rec))
            except Exception as exc:  # noqa: BLE001 — classified below; the cursor stays on it
                if permanent(exc):
                    if not _quarantine(ctx, s, dest, source, rec, payload, f"refused: {exc}", 1, at):
                        run.dlq_full = True
                        break
                    run.quarantined += 1
                    consumed = rec.record_id
                    continue
                failure = (rec, str(exc) or type(exc).__name__)
                break
            sent += 1
            consumed = rec.record_id
        if sent:
            try:
                transport.finish_batch()
            except OSError as exc:  # not confirmed: nothing of this batch counts as sent (at least once)
                first = next(r for r in records if r.record_id in payloads)
                failure = (first, f"delivery_unconfirmed: {exc}")
                consumed = max([last, *(r.record_id for r in records if r.record_id < first.record_id)])
                sent = 0
        with ctx.db() as conn:
            if not store.advance(conn, dest.id, source, pce_url=pce.url, org_id=pce.org_id, last_id=consumed,
                                 sent=sent, at=at):
                return run  # the PCE was switched while the batch was out: its cursors start over
        run.sent += sent
        last = consumed
        if run.dlq_full:
            run.error = "dlq_full"
            return run
        if failure is not None:
            head, error = failure
            with ctx.db() as conn:
                attempts = store.record_failure(conn, dest.id, source, head_id=head.record_id, error=error, at=at)
            run.error, run.unreachable = error, True
            logger.warning("SIEM destination {} ({}): send failed at {} (attempt {}): {}", dest.name, source,
                           head.external_id, attempts, error)
            stuck = attempts >= dest.max_retries * STUCK_FACTOR
            if attempts >= dest.max_retries and (stuck or _next_goes_through(transport, fmt, records, head)):
                # The record after it went through (or it failed far too often): this one is what fails.
                nxt = None if stuck else next(r for r in records if r.record_id > head.record_id)
                payload = payloads.get(head.record_id) or fmt.format_record(head)
                if _quarantine(ctx, s, dest, source, head, payload, error, attempts, at):
                    run.quarantined += 1
                    run.sent += 0 if nxt is None else 1
                    with ctx.db() as conn:
                        store.advance(conn, dest.id, source, pce_url=pce.url, org_id=pce.org_id,
                                      last_id=head.record_id if nxt is None else nxt.record_id,
                                      sent=0 if nxt is None else 1, at=at)
                else:
                    run.dlq_full = True
            return run
        if len(records) < dest.batch_size:
            break
    return run
