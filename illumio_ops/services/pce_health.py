"""PCE health checks: run the probes and keep the latest result (owner of table pce_probe)."""
from __future__ import annotations

import json
from datetime import UTC, datetime

from loguru import logger

from illumio_ops.domain.values import ProbeName
from illumio_ops.pce.health import ProbeResult, probe_pce
from illumio_ops.services.context import AppContext

_UPSERT = (
    "INSERT INTO pce_probe (id, checked_at, results_json, pce_url, org_id) VALUES (1, ?, ?, ?, ?) "
    "ON CONFLICT(id) DO UPDATE SET checked_at = excluded.checked_at, results_json = excluded.results_json, "
    "pce_url = excluded.pce_url, org_id = excluded.org_id"
)


def run_probe(ctx: AppContext) -> list[ProbeResult]:
    """Probe the configured PCE now and record the outcome. PceNotConfigured propagates."""
    s = ctx.settings.current()
    with ctx.pce_client(s.pce) as client:
        results = probe_pce(client, s.pce.deployment_type)
    now = ctx.settings.current().pce
    if (now.url, now.org_id) != (s.pce.url, s.pce.org_id):
        # The PCE was switched while it answered: its result describes the previous one (F15).
        logger.info("PCE health probe answered after the PCE was switched; its result was dropped")
        return results
    payload = json.dumps([
        {"name": r.name.value, "ok": r.ok, "status": r.status, "category": r.category, "detail_key": r.detail_key}
        for r in results
    ])
    with ctx.db() as conn:
        conn.execute(_UPSERT, (datetime.now(UTC).isoformat(), payload, s.pce.url, s.pce.org_id))
    return results


def latest(ctx: AppContext) -> tuple[datetime, list[ProbeResult]] | None:
    """The stored result, only if it is about the PCE configured now."""
    pce = ctx.settings.current().pce
    with ctx.db() as conn:
        row = conn.execute("SELECT checked_at, results_json, pce_url, org_id FROM pce_probe WHERE id = 1").fetchone()
    if row is None or (row["pce_url"], row["org_id"]) != (pce.url, pce.org_id):
        return None
    results = [ProbeResult(ProbeName(d["name"]), d["ok"], d["status"], d["category"], d["detail_key"])
               for d in json.loads(row["results_json"])]
    return datetime.fromisoformat(row["checked_at"]), results


def forget(ctx: AppContext) -> None:
    """Drop the stored result: it described a different PCE (spec §6.4, switching PCE)."""
    with ctx.db() as conn:
        conn.execute("DELETE FROM pce_probe")
