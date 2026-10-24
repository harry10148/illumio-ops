"""PCE health checks: run the probes and keep the latest result (owner of table pce_probe)."""
from __future__ import annotations

import json
from datetime import UTC, datetime

from illumio_ops.domain.values import ProbeName
from illumio_ops.pce.health import ProbeResult, probe_pce
from illumio_ops.services.context import AppContext

_UPSERT = (
    "INSERT INTO pce_probe (id, checked_at, results_json) VALUES (1, ?, ?) "
    "ON CONFLICT(id) DO UPDATE SET checked_at = excluded.checked_at, results_json = excluded.results_json"
)


def run_probe(ctx: AppContext) -> list[ProbeResult]:
    """Probe the configured PCE now and record the outcome. PceNotConfigured propagates."""
    s = ctx.settings.current()
    with ctx.pce_factory(s.pce) as client:
        results = probe_pce(client, s.pce.deployment_type)
    payload = json.dumps([
        {"name": r.name.value, "ok": r.ok, "status": r.status, "category": r.category, "detail_key": r.detail_key}
        for r in results
    ])
    with ctx.db() as conn:
        conn.execute(_UPSERT, (datetime.now(UTC).isoformat(), payload))
    return results


def latest(ctx: AppContext) -> tuple[datetime, list[ProbeResult]] | None:
    with ctx.db() as conn:
        row = conn.execute("SELECT checked_at, results_json FROM pce_probe WHERE id = 1").fetchone()
    if row is None:
        return None
    results = [ProbeResult(ProbeName(d["name"]), d["ok"], d["status"], d["category"], d["detail_key"])
               for d in json.loads(row["results_json"])]
    return datetime.fromisoformat(row["checked_at"]), results
