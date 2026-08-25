"""Drop every row this appliance derived from one PCE.

The cache carries no tenant dimension: `flow_hash` is globally unique and the
ingestion watermark's primary key is `source` alone. So re-pointing the
appliance at a second PCE without clearing this leaves the two mixed, and the
new PCE inherits the old one's fetch position. Everything here is deleted
together or the state is worse than before the flush.
"""
from __future__ import annotations

import os

from loguru import logger
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import (
    Base, DeadLetter, IngestionCursor, IngestionWatermark, PceEvent,
    PceTrafficFlowAgg, PceTrafficFlowObs, PceTrafficFlowRaw, SiemDispatch,
)
from src.state_store import update_state_file

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

# Written by other subsystems but derived from the same PCE all the same. The
# rule is provenance, not who writes it: if the value describes the old PCE and
# the new one would be read as its owner, it goes.
#
# event_overflow / traffic_overflow record a fetch episode against the old PCE
# (scheduler/jobs.py's _record_overflow_state; read by
# Analyzer._maybe_alert_overflow). _ANALYZER_OWNED_STATE_KEYS already carries
# their two cooldown keys, so leaving the episodes behind cleared the cooldown
# and kept the reason — the new PCE re-fired a data-loss alert describing the
# old PCE's fetch on the very next cycle.
#
# ven_summary is the same provenance (VEN counts pulled from the old PCE) but
# does not live in the state file at all — it is in logs/dashboard_summary.json
# (src/dashboard_store.py). It is cleared alongside these, from that file, by
# the same call; see _flush_dashboard_summary below.
#
# Deliberately NOT here: rule_schedule_states / report_schedule_states, which
# belong to schedules the operator authored, not to the PCE's data.
_EXTRA_PCE_DERIVED = (
    "event_timeline",
    "pce_stats",
    "posture_summary",
    "event_overflow",
    "traffic_overflow",
)

_STATE_KEYS = tuple(_ANALYZER_OWNED_STATE_KEYS) + _EXTRA_PCE_DERIVED

# Keys of logs/dashboard_summary.json that describe the old PCE's estate.
_DASHBOARD_KEYS = ("ven_summary",)

# How long to wait for a monitor cycle already in flight to finish. Longer than
# the interactive menu's 5s (src/main.py) because losing the wait here means
# not clearing at all; far shorter than the schedulers' 600s because an
# operator is sitting in front of a settings save, and a timeout is reported
# back to them as something to retry rather than swallowed.
_ANALYSIS_LOCK_WAIT_S = 120.0


def flush_pce_derived_state(db_path: str, state_path: str) -> dict[str, int]:
    """Empty the cache tables and the PCE-derived keys of the state file.

    Returns a count per item cleared. A missing DB or state file is not an
    error: there is simply nothing of the old PCE left to remove.

    Runs under both analysis locks, in the order every other full-cycle entry
    point takes them (scheduler/jobs.py's run_monitor_cycle, the GUI's
    /api/actions/run): the cross-process ``file_lock(analysis_lock_path())``
    outside, the in-process ``analysis_lock`` inside. Taking them here rather
    than at the call sites means no caller can forget, and a caller in a
    different process (the CLI paths) still gets the one that works across
    processes — the in-process lock is inert there.

    Raises TimeoutError when a cycle in flight does not finish inside
    _ANALYSIS_LOCK_WAIT_S. Every caller flushes BEFORE writing the new
    connection, so a raise here leaves the appliance pointed at the PCE whose
    data is still intact.
    """
    from src.analyzer import analysis_lock
    from src.file_lock import file_lock
    from src.main import analysis_lock_path

    with file_lock(analysis_lock_path(), timeout=_ANALYSIS_LOCK_WAIT_S):
        with analysis_lock:
            return _flush_locked(db_path, state_path)


def _flush_locked(db_path: str, state_path: str) -> dict[str, int]:
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

    # No state file means nothing of the old PCE was ever recorded there —
    # same reading as the missing-DB case above. Skip touching it entirely
    # rather than calling update_state_file() unconditionally: that would
    # create a fresh logs/state.json out of nothing (e.g. before the
    # appliance has ever run), which isn't ours to originate here.
    if os.path.exists(state_path):
        removed: list[str] = []

        def _pop_pce_keys(state: dict) -> dict:
            for k in _STATE_KEYS:
                if k in state:
                    state.pop(k, None)
                    removed.append(k)
            return state

        # update_state_file() takes state.json's own .lock and writes via
        # tmp + os.replace, so a crash mid-write cannot truncate the file and
        # take rule_schedule_states / report_schedule_states down with it.
        #
        # That lock is NOT what keeps the cleared keys cleared. The race that
        # matters is not two writers colliding on the file: Analyzer.save_state
        # writes its own keys back from the snapshot it loaded at the START of
        # a cycle, and a cycle spans minutes (analyzer.py's _merge). A pop that
        # lands inside some cycle's load→save window is reported as a success
        # and then silently undone. That is what the two analysis locks held by
        # our caller are for — the same reasoning, and the same consequence,
        # as the GUI's reset-watermark endpoint (gui/routes/actions.py).
        update_state_file(state_path, _pop_pce_keys)
        if removed:
            logger.warning("PCE-derived state keys cleared: {}", removed)
        counts["state_keys"] = len(removed)

    counts["dashboard_keys"] = _flush_dashboard_summary()

    return counts


def _flush_dashboard_summary() -> int:
    """Drop the old PCE's estate summary from logs/dashboard_summary.json.

    Separate file, separate writer (run_ven_summary), same provenance as
    posture_summary: VEN counts, OS mix and enforcement mix pulled straight
    out of the PCE being left behind. Left in place they are shown on the new
    PCE's overview, unlabelled, until the next scheduled run — the same silent
    mixing of two estates the rest of this module exists to prevent.

    Resolved through the store's own module attribute so a test can point it
    somewhere else; nothing else here knows the path.
    """
    from src import dashboard_store

    path = dashboard_store._dashboard_file()
    if not os.path.exists(path):
        return 0
    removed: list[str] = []

    def _pop(existing: dict) -> dict:
        for k in _DASHBOARD_KEYS:
            if k in existing:
                existing.pop(k, None)
                removed.append(k)
        return existing

    dashboard_store.write_dashboard_summary(_pop)
    if removed:
        logger.warning("PCE-derived dashboard keys cleared: {}", removed)
    return len(removed)
