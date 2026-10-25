"""The hourly analysis job (spec §5: the exposure graph is recomputed on a schedule and stored, never per
request). Its steps run in order; a step that fails is recorded and the next one still runs. A PCE switch
part-way stops the run: nothing more is written for the previous PCE."""
from __future__ import annotations

import traceback
from collections.abc import Callable
from datetime import UTC, datetime

from loguru import logger

from illumio_ops.services.analysis.exposure import run_exposure
from illumio_ops.services.analysis.ransomware import ransomware_overlay
from illumio_ops.services.context import AppContext
from illumio_ops.store.flowdb import analysis
from illumio_ops.store.flowdb.db import StaleGeneration

HourlyStep = Callable[[AppContext, datetime], None]


def _exposure(ctx: AppContext, now: datetime) -> None:
    run_exposure(ctx, now=now)


# Later steps read what earlier ones stored (the focus list last).
HOURLY_STEPS: list[tuple[str, HourlyStep]] = [
    ("exposure", _exposure),
    ("ransomware", ransomware_overlay),
]


def run_hourly_analysis(ctx: AppContext, *, now: datetime | None = None) -> dict[str, str]:
    """Each step's outcome: "ok", "stale" (the PCE was switched) or the error."""
    at = (now or datetime.now(UTC)).astimezone(UTC)
    fdb = ctx.flows()
    out: dict[str, str] = {}
    for name, step in HOURLY_STEPS:
        gen = fdb.generation
        try:
            with fdb.writing(gen) as conn:
                analysis.set_run(conn, name, started_at=at)
            step(ctx, at)
            with fdb.writing(gen) as conn:
                analysis.set_run(conn, name, ok_at=at)
            out[name] = "ok"
        except StaleGeneration:
            logger.info("hourly analysis: the PCE was switched during {}; the run stops", name)
            out[name] = "stale"
            return out
        except Exception as exc:  # noqa: BLE001 - one step's failure is recorded, the others still run
            logger.error("hourly analysis step {} failed: {}", name, traceback.format_exc())
            out[name] = f"{type(exc).__name__}: {exc}"[:500]
            try:
                with fdb.writing(gen) as conn:
                    analysis.set_run(conn, name, error=out[name])
            except StaleGeneration:
                return out
    return out
