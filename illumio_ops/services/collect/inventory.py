"""Inventory collector: managed workloads (mode, visibility level, labels, VEN) and the PCE's
ransomware-protection judgement, with one snapshot per day.

An incomplete workload list (more than 500 and the async path failed) keeps the previous
inventory: a partial list would make missing hosts look like hosts that left.
"""
from __future__ import annotations

import sqlite3
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from loguru import logger

from illumio_ops.domain.values import (
    CapabilityState,
    IngestSource,
    visibility_sees_allowed,
)
from illumio_ops.pce.capabilities import detect_from_status, detect_from_workloads
from illumio_ops.pce.client import PceClient, PceNotConfigured
from illumio_ops.pce.collections import PceCollectionIncomplete, get_all
from illumio_ops.services.collect import CycleResult, drops_stale
from illumio_ops.services.collect.guard import BindingMismatch, ensure_binding
from illumio_ops.services.collect.mode import collects
from illumio_ops.services.collect.traffic import PCE_FAILURES
from illumio_ops.services.context import AppContext
from illumio_ops.settings.schema import PceSettings
from illumio_ops.store.flowdb import capabilities, ingest_state, ransomware, workloads
from illumio_ops.store.flowdb.db import (
    FlowDb,
    StaleGeneration,
    db_day,
    db_time,
    transaction,
)
from illumio_ops.store.flowdb.labels import label_set_id

SOURCE = IngestSource.INVENTORY
RISK_SOURCE = IngestSource.RANSOMWARE
DEADLINE_SECONDS = 900


def _ransomware(w: Mapping[str, Any]) -> Mapping[str, Any] | None:
    rs = w.get("risk_summary")
    rw = rs.get("ransomware") if isinstance(rs, Mapping) else None
    return rw if isinstance(rw, Mapping) else None


def _map(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _row(conn: Any, w: Mapping[str, Any], fetched_at: str) -> workloads.WorkloadRow:
    ven = _map(w.get("ven"))
    status = _map(_map(w.get("agent")).get("status"))
    labels = tuple(sorted({(str(lb["key"]), str(lb["value"])) for lb in w.get("labels") or []
                           if isinstance(lb, Mapping) and lb.get("key") is not None and lb.get("value") is not None}))
    rw = _map(_ransomware(w))
    pct = rw.get("ransomware_protection_percent")
    return workloads.WorkloadRow(
        href=str(w["href"]), hostname=w.get("hostname"), name=w.get("name"), managed=int(bool(w.get("managed"))),
        enforcement_mode=w.get("enforcement_mode"), visibility_level=w.get("visibility_level"), os_id=w.get("os_id"),
        ven_version=ven.get("version") or status.get("agent_version"), ven_href=ven.get("href"),
        label_set=label_set_id(conn, labels), online=None if w.get("online") is None else int(bool(w["online"])),
        risk_exposure=rw.get("workload_exposure_severity"),
        risk_percent=float(pct) if isinstance(pct, (int, float)) and not isinstance(pct, bool) else None,
        risk_updated_at=rw.get("last_updated_at"), fetched_at=fetched_at,
    )


def visibility_summary(conn: Any) -> dict[str, int]:
    out = {"sees_allowed": 0, "blocked_only": 0, "off": 0, "unknown": 0}
    for level, n in conn.execute("SELECT visibility_level, count(*) FROM workloads GROUP BY 1"):
        sees = visibility_sees_allowed(level)
        key = ("unknown" if sees is None else "sees_allowed" if sees else "off" if level == "flow_off"
               else "blocked_only")
        out[key] += n
    return out


def _deadline() -> float:
    return time.monotonic() + DEADLINE_SECONDS


def _org_summary(client: PceClient, fdb: FlowDb, gen: int, day: str, at: datetime) -> str | None:
    """Read and store the organisation summary; returns what went wrong, if anything. A PCE
    without the endpoint (404) is a missing capability, not a failure."""
    resp = client.request("GET", "/reports/risk_summary", timeout=60, deadline=_deadline())
    state = detect_from_status(resp.status)
    summary = resp.json() if resp.status == 200 else None  # unreadable JSON raises to the risk stage
    with fdb.writing(gen) as conn:
        capabilities.record(conn, "ransomware_org_summary", state, None if resp.status == 200 else f"HTTP {resp.status}", at)
        if summary is not None:
            ransomware.write_org_summary(conn, day, summary)
    if resp.status == 200 or state is CapabilityState.UNSUPPORTED:
        return None
    return f"organisation summary: HTTP {resp.status}"


def _risk_details(client: PceClient, fdb: FlowDb, gen: int, rows: list[dict[str, Any]],
                  at: datetime) -> tuple[int, int, int]:
    """Fetch details only for workloads whose PCE summary changed: (wanted, fetched, failed)."""
    with fdb.connect() as conn:
        held = ransomware.source_updated(conn)
    todo = [(str(w["href"]), (_ransomware(w) or {}).get("last_updated_at")) for w in rows if _ransomware(w)]
    todo = [(href, updated) for href, updated in todo if href not in held or held[href] != updated]
    fetched = failed = 0
    for href, updated in todo:
        try:
            resp = client.request("GET", f"{href}/risk_details", org_scoped=False, timeout=60, deadline=_deadline())
        except PCE_FAILURES as exc:
            failed += 1
            logger.warning("risk details for a workload could not be read: {}", exc)
            continue
        if resp.status != 200:
            failed += 1
            continue
        try:
            body = resp.json()
        except ValueError:
            failed += 1
            continue
        rd = body.get("risk_details") if isinstance(body, Mapping) else None
        rw = rd.get("ransomware") if isinstance(rd, Mapping) else None
        details = rw.get("details") if isinstance(rw, Mapping) else None
        with fdb.writing(gen) as conn:
            ransomware.upsert_services(conn, href, details if isinstance(details, list) else [],
                                       source_updated_at=updated, at=at)
        fetched += 1
    return len(todo), fetched, failed


@drops_stale
def run_inventory_cycle(ctx: AppContext, *, now: datetime | None = None) -> CycleResult:
    gen = ctx.flows().generation  # noted before the settings it goes with (FlowDb.generation)
    settings = ctx.settings.current()
    if not collects(settings, IngestSource.INVENTORY):
        return CycleResult(0, 0, 0)
    try:
        client = ctx.pce_client(settings.pce)
    except PceNotConfigured:
        return CycleResult(0, 0, 0)
    at = (now or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)
    day = db_day(at)
    fdb = ctx.flows()
    with fdb.writing(gen) as conn:
        ingest_state.mark_started(conn, SOURCE, at)
    try:
        return _inventory(ctx, client, settings.pce, fdb, gen, at, day)
    except StaleGeneration:
        raise
    except Exception as exc:
        with fdb.writing(gen) as conn:
            ingest_state.mark_failed(conn, SOURCE, at, f"{type(exc).__name__}: {exc}")
        raise


def _inventory(ctx: AppContext, client: PceClient, pce: PceSettings, fdb: FlowDb, gen: int, at: datetime,
               day: str) -> CycleResult:
    with client:
        try:
            rows = get_all(client, "/workloads", params={"managed": "true"}, deadline=_deadline())
        except PceCollectionIncomplete as exc:
            with fdb.writing(gen) as conn:
                ingest_state.mark_failed(conn, SOURCE, at, f"incomplete: {exc.reason}")
            logger.warning("workload inventory incomplete, keeping the previous one: {}", exc)
            return CycleResult(0, 1, 1)
        except PCE_FAILURES as exc:
            with fdb.writing(gen) as conn:
                ingest_state.mark_failed(conn, SOURCE, at, str(exc))
            return CycleResult(0, 0, 1)
        with fdb.writing(gen) as conn:
            try:
                ensure_binding(conn, pce, at)
            except BindingMismatch as exc:
                ingest_state.mark_failed(conn, SOURCE, at, f"binding: {exc}")
                return CycleResult(0, 1, 0)
            stamp = db_time(at)
            with transaction(conn):
                workloads.replace_inventory(conn, [_row(conn, w, stamp) for w in rows])
                ransomware.prune_missing(conn, (str(w["href"]) for w in rows))
                for name, state in detect_from_workloads(rows).items():
                    capabilities.record(conn, name, state, None, at)
                ingest_state.mark_ok(conn, SOURCE, at, watermark=None, rows=len(rows))
        # The ransomware stage reports on its own source and never fails the inventory before it.
        try:
            summary_error = _org_summary(client, fdb, gen, day, at)
            wanted, fetched, failed = _risk_details(client, fdb, gen, rows, at)
        except (*PCE_FAILURES, ValueError, sqlite3.Error) as exc:  # ValueError: an unreadable body
            logger.warning("ransomware protection could not be read: {}", exc)
            with fdb.writing(gen) as conn:
                ingest_state.mark_failed(conn, RISK_SOURCE, at, f"{type(exc).__name__}: {exc}")
        else:
            problems = [p for p in (summary_error, f"{failed} of {wanted} workloads failed" if failed else None) if p]
            with fdb.writing(gen) as conn:
                if problems:
                    ingest_state.mark_failed(conn, RISK_SOURCE, at, "; ".join(problems))
                else:
                    ingest_state.mark_ok(conn, RISK_SOURCE, at, watermark=None, rows=fetched)
    with fdb.writing(gen) as conn:
        workloads.snapshot_day(conn, day)
        ransomware.snapshot_day(conn, day)
    return CycleResult(len(rows), 1, 0)

