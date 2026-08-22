"""Drop every row this appliance derived from one PCE.

The cache carries no tenant dimension: `flow_hash` is globally unique and the
ingestion watermark's primary key is `source` alone. So re-pointing the
appliance at a second PCE without clearing this leaves the two mixed, and the
new PCE inherits the old one's fetch position. Everything here is deleted
together or the state is worse than before the flush.
"""
from __future__ import annotations

import json
import os

from loguru import logger
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import (
    Base, DeadLetter, IngestionCursor, IngestionWatermark, PceEvent,
    PceTrafficFlowAgg, PceTrafficFlowObs, PceTrafficFlowRaw, SiemDispatch,
)

# Order matters: SiemDispatch and DeadLetter reference rows in the data tables
# by (source_table, source_id), so they go first.
_MODELS = (
    SiemDispatch, DeadLetter,
    PceTrafficFlowAgg, PceTrafficFlowObs, PceTrafficFlowRaw, PceEvent,
    IngestionCursor, IngestionWatermark,
)

# The state.json keys that describe one PCE's history. Everything else in that
# file (schedules, GUI state, backups) survives.
#
# The analyzer already owns an authoritative list of the keys it writes, so
# take it from there rather than restating it — a restated copy drifts, and a
# key this misses is a key the next PCE inherits.
from src.analyzer import _ANALYZER_OWNED_STATE_KEYS

# Written by other subsystems but derived from the same PCE all the same.
# Deliberately NOT here: rule_schedule_states / report_schedule_states, which
# belong to schedules the operator authored, not to the PCE's data.
_EXTRA_PCE_DERIVED = ("event_timeline", "pce_stats", "posture_summary")

_STATE_KEYS = tuple(_ANALYZER_OWNED_STATE_KEYS) + _EXTRA_PCE_DERIVED


def flush_pce_derived_state(db_path: str, state_path: str) -> dict[str, int]:
    """Empty the cache tables and the PCE-derived keys of the state file.

    Returns a count per item cleared. A missing DB or state file is not an
    error: there is simply nothing of the old PCE left to remove.
    """
    counts: dict[str, int] = {}

    if os.path.exists(db_path):
        engine = create_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(engine)
        session_factory = sessionmaker(bind=engine)
        with session_factory() as session:
            for model in _MODELS:
                n = session.execute(select(func.count()).select_from(model)).scalar_one()
                session.execute(delete(model))
                counts[model.__tablename__] = int(n)
            session.commit()
        engine.dispose()
        logger.warning("PCE cache flushed: {}", counts)

    if os.path.exists(state_path):
        with open(state_path, "r", encoding="utf-8") as fh:
            state = json.load(fh)
        removed = [k for k in _STATE_KEYS if k in state]
        for k in removed:
            state.pop(k, None)
        if removed:
            with open(state_path, "w", encoding="utf-8") as fh:
                json.dump(state, fh, ensure_ascii=False, indent=2)
            logger.warning("PCE-derived state keys cleared: {}", removed)
        counts["state_keys"] = len(removed)

    return counts
