"""Collectors: bring PCE data into the flow database on the schedule set in settings."""
from __future__ import annotations

import functools
from collections.abc import Callable
from dataclasses import dataclass
from typing import ParamSpec

from loguru import logger

from illumio_ops.store.flowdb.db import StaleGeneration

P = ParamSpec("P")


@dataclass(frozen=True)
class CycleResult:
    rows: int       # records written (new or refreshed)
    windows: int    # PCE queries that answered
    gaps: int       # windows recorded as failed or truncated
    skipped: int = 0  # records the PCE sent in a shape we could not read


def drops_stale(fn: Callable[P, CycleResult]) -> Callable[P, CycleResult]:
    """A cycle that a PCE switch overtook writes nothing and reports nothing done."""
    @functools.wraps(fn)
    def run(*args: P.args, **kwargs: P.kwargs) -> CycleResult:
        try:
            return fn(*args, **kwargs)
        except StaleGeneration:
            logger.info("{}: the PCE was switched while it ran; its results were dropped", fn.__name__)
            return CycleResult(0, 0, 0)
    return run
