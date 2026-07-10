"""Regression tests for the two Critical findings from the opus review of
ef44682 (fix/watchdog-overflow-pce-cache-path):

C1 — Analyzer._run_event_analysis's cache branch called
     stats.record_pce_success("events", ...) on every cycle for a purely
     LOCAL cache read (src/pce_cache subscriber), and
     StatsTracker.record_pce_success unconditionally zeroes
     pce_stats.consecutive_failures. A local disk read succeeding says
     nothing about live PCE reachability — the scheduler's ingest jobs
     (run_events_ingest/run_traffic_ingest) are the only code on this
     deployment shape that actually talk to the PCE and accumulate that
     counter. Since the cache-path monitor cycle runs every 30s
     (src/scheduler/__init__.py) while ingest jobs run every
     300s/3600s, the analyzer's own cycle reliably zeroed the counter
     before it could ever reach WATCHDOG_FAILURE_THRESHOLD — the watchdog
     added in ef44682 stayed dead code in exactly the deployment shape it
     was meant to fix.

C2 — Analyzer.save_state()'s `_merge` did `merged.update(self.state)`,
     where self.state is a snapshot loaded at cycle start. Since
     traffic_overflow is written exclusively by the scheduler's
     run_traffic_ingest job (never by Analyzer), any traffic_overflow
     written to disk after this cycle's load_state() and before this
     cycle's save_state() was overwritten by the stale (usually empty)
     in-memory snapshot — the overflow episode disappears from disk
     before ever crossing the alert path reliably.

Fix: cache reads now go through StatsTracker.record_local_read (dashboard
fields only, never consecutive_failures), Analyzer tracks a
self._pce_stats_dirty flag set only by real PCE probes
(record_pce_success/record_pce_error from _run_health_check /
_legacy_event_pull), and save_state's _merge treats traffic_overflow and
(non-dirty) pce_stats as externally co-owned keys deferring to disk.
"""
from __future__ import annotations

import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.analyzer import Analyzer, WATCHDOG_FAILURE_THRESHOLD
from src.config import ConfigManager
from src.events.poller import format_utc
from src.state_store import load_state_file, update_state_file


def _cm():
    cm = ConfigManager()
    cm.config["rules"] = []  # no system/pce_health rule -> _run_health_check never probes
    return cm


@pytest.fixture
def state_file(tmp_path, monkeypatch):
    import src.analyzer as analyzer_mod
    sf = str(tmp_path / "state.json")
    monkeypatch.setattr(analyzer_mod, "STATE_FILE", sf)
    return sf


def _cache_analyzer(rows=None):
    sub = MagicMock()
    sub.poll_new_rows.return_value = rows or []
    return Analyzer(_cm(), MagicMock(), MagicMock(), subscriber_events=sub)


def _run_cache_cycle(ana):
    """Run a full cache-path cycle without touching the (mocked) API for traffic."""
    with patch.object(ana, "_fetch_traffic",
                       return_value=(None, [], datetime.datetime.now(datetime.timezone.utc))):
        ana.run_analysis()


# ─── C1: watchdog counter must survive a cache-only cycle ─────────────────

def test_cache_cycle_run_analysis_triggers_watchdog_and_preserves_disk_count(state_file):
    """Disk pre-seeded at the watchdog threshold (as the scheduler's ingest
    jobs would leave it after N consecutive PCE failures). A cache-path
    monitor cycle must (a) fire the watchdog alert and (b) not zero the
    on-disk consecutive_failures count via its own save_state()."""
    update_state_file(state_file, lambda s: {
        **s, "pce_stats": {"consecutive_failures": WATCHDOG_FAILURE_THRESHOLD}
    })

    ana = _cache_analyzer()
    _run_cache_cycle(ana)

    ana.reporter.add_health_alert.assert_called_once()
    on_disk = load_state_file(state_file)
    assert on_disk["pce_stats"]["consecutive_failures"] == WATCHDOG_FAILURE_THRESHOLD


def test_pure_cache_cycle_does_not_change_disk_consecutive_failures(state_file):
    """No health-check rule configured, cache subscriber succeeds (no PCE
    probe at all this cycle): the on-disk consecutive_failures must be left
    exactly as-is — not zeroed (old bug) and not incremented."""
    update_state_file(state_file, lambda s: {
        **s, "pce_stats": {"consecutive_failures": 1}
    })

    ana = _cache_analyzer()
    _run_cache_cycle(ana)

    on_disk = load_state_file(state_file)
    assert on_disk["pce_stats"]["consecutive_failures"] == 1
    ana.reporter.add_health_alert.assert_not_called()


def test_save_state_merge_defers_to_disk_pce_stats_when_not_dirty(state_file):
    """Isolates the _merge fix directly: simulate the scheduler ingest job
    writing a fresher consecutive_failures value to disk in the gap between
    this Analyzer instance's load_state() (at construction) and its
    save_state() call. A non-dirty analyzer (no real PCE probe performed
    this cycle) must not clobber that fresher disk value with its own stale
    in-memory snapshot."""
    update_state_file(state_file, lambda s: {**s, "pce_stats": {"consecutive_failures": 1}})
    ana = _cache_analyzer()
    assert ana.state["pce_stats"]["consecutive_failures"] == 1  # stale snapshot taken at load

    # Scheduler ingest job races in with a fresher value mid-cycle.
    update_state_file(state_file, lambda s: {
        **s, "pce_stats": {**s.get("pce_stats", {}), "consecutive_failures": WATCHDOG_FAILURE_THRESHOLD}
    })

    ana.save_state()

    on_disk = load_state_file(state_file)
    assert on_disk["pce_stats"]["consecutive_failures"] == WATCHDOG_FAILURE_THRESHOLD


# ─── C2: traffic_overflow must survive a cache-only cycle ─────────────────

def test_cache_cycle_preserves_and_alerts_on_traffic_overflow(state_file):
    """Disk pre-seeded with a traffic_overflow episode (as run_traffic_ingest
    would leave it). A cache-path cycle must fire the overflow meta-alert
    and must not wipe a FRESHER disk value written mid-cycle by the
    scheduler's run_traffic_ingest job (simulated here via the
    _fetch_traffic patch point, which runs before the overflow check/save)
    — only that job resolves/clears traffic_overflow, never the analyzer.
    A same-value preseed-then-save round-trip would pass even on the buggy
    merge (no observable divergence), so this must inject a real race to be
    a meaningful regression test."""
    initial_overflow = {"raw_count": 5, "max_results": 5,
                         "query_since": "s0", "query_until": "u0"}
    fresher_overflow = {"raw_count": 200000, "max_results": 200000,
                         "query_since": "2026-07-10T00:00:00+00:00",
                         "query_until": "2026-07-10T00:01:00+00:00"}
    update_state_file(state_file, lambda s: {**s, "traffic_overflow": initial_overflow})

    ana = _cache_analyzer()
    assert ana.state["traffic_overflow"] == initial_overflow  # stale snapshot from load

    def _fetch_traffic_with_race(*args, **kwargs):
        update_state_file(state_file, lambda s: {**s, "traffic_overflow": fresher_overflow})
        return None, [], datetime.datetime.now(datetime.timezone.utc)

    with patch.object(ana, "_fetch_traffic", side_effect=_fetch_traffic_with_race):
        ana.run_analysis()

    ana.reporter.add_health_alert.assert_called_once()

    on_disk = load_state_file(state_file)
    assert on_disk["traffic_overflow"] == fresher_overflow


def test_save_state_merge_defers_to_disk_traffic_overflow(state_file):
    """Isolates the _merge fix: traffic_overflow written to disk after this
    Analyzer instance's load_state() (at construction) must survive this
    Analyzer's save_state() unchanged, since Analyzer never writes this key
    itself — it must always defer to whatever is on disk."""
    initial_overflow = {"raw_count": 5, "max_results": 5}
    fresher_overflow = {"raw_count": 200000, "max_results": 200000}
    update_state_file(state_file, lambda s: {**s, "traffic_overflow": initial_overflow})

    ana = _cache_analyzer()
    assert ana.state["traffic_overflow"] == initial_overflow

    update_state_file(state_file, lambda s: {**s, "traffic_overflow": fresher_overflow})

    ana.save_state()

    on_disk = load_state_file(state_file)
    assert on_disk["traffic_overflow"] == fresher_overflow


# ─── Task 2: alert_dlq must survive a cache-only cycle ────────────────────

def test_save_state_merge_defers_to_disk_alert_dlq(state_file):
    """Isolates the _merge fix: alert_dlq is written exclusively by the
    Reporter's DLQ push/pop (via update_state_file, src/reporter.py), never
    by Analyzer. Simulate the Reporter clearing the on-disk queue (a
    successful retry-drain) in the gap between this Analyzer instance's
    load_state() (at construction) and its save_state() call — the cleared
    disk value must survive, not be resurrected by this cycle's stale
    in-memory snapshot."""
    entry = {"attempts": 1, "first_failed_at": "2026-07-10T00:00:00+00:00"}
    update_state_file(state_file, lambda s: {**s, "alert_dlq": [entry]})
    ana = _cache_analyzer()
    assert ana.state["alert_dlq"] == [entry]  # stale snapshot taken at load

    # Reporter drains the DLQ mid-cycle (successful retry).
    update_state_file(state_file, lambda s: {**s, "alert_dlq": []})

    ana.save_state()

    on_disk = load_state_file(state_file)
    assert on_disk["alert_dlq"] == []


# ─── H-Task 3 (scheduler side): watchdog_last_alert_at must survive a
# cache-only cycle ──────────────────────────────────────────────────────────

def test_save_state_merge_defers_to_disk_watchdog_last_alert_at_when_not_dirty(state_file):
    """Isolates the _merge fix: watchdog_last_alert_at is co-owned with the
    scheduler's cache-ingest jobs — _record_ingest_pce_result's
    record_pce_success clears it to None on disk directly when a real PCE
    probe recovers (see d75170e). Simulate that recovery landing on disk in
    the gap between this Analyzer instance's load_state() (at construction,
    snapshotting the still-stale timestamp left by a prior incident) and its
    save_state() call. The cleared (None) disk value must survive — not be
    resurrected by this cycle's stale in-memory snapshot — otherwise a fresh
    incident within the 60-minute cooldown window of the old one is silently
    suppressed (the exact bug H-Task 3 was meant to eliminate, reborn on the
    scheduler side)."""
    stale_ts = format_utc(datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=10))
    update_state_file(state_file, lambda s: {**s, "watchdog_last_alert_at": stale_ts})
    ana = _cache_analyzer()
    assert ana.state["watchdog_last_alert_at"] == stale_ts  # stale snapshot taken at load

    # Scheduler's ingest job recovers mid-cycle: record_pce_success clears
    # watchdog_last_alert_at to None on disk directly (never through this
    # Analyzer instance).
    update_state_file(state_file, lambda s: {**s, "watchdog_last_alert_at": None})

    ana.save_state()

    on_disk = load_state_file(state_file)
    assert on_disk["watchdog_last_alert_at"] is None


def test_check_watchdog_alert_timestamp_survives_save_when_pce_stats_not_dirty(state_file):
    """Reverse pin: a cache-only cycle where _check_watchdog itself fires an
    alert (no health-check rule deployed, so self._pce_stats_dirty stays
    False all cycle) must still persist the timestamp _check_watchdog just
    wrote into self.state. watchdog_last_alert_at needs its own dirty flag,
    separate from _pce_stats_dirty — sharing it would make save_state() defer
    to disk (stale/absent) instead of writing this cycle's own cooldown
    timestamp, so the watchdog would re-alert every cycle instead of
    respecting WATCHDOG_COOLDOWN_MINUTES."""
    update_state_file(state_file, lambda s: {
        **s, "pce_stats": {"consecutive_failures": WATCHDOG_FAILURE_THRESHOLD}
    })
    ana = _cache_analyzer()
    _run_cache_cycle(ana)  # no health rule -> _pce_stats_dirty stays False; _check_watchdog still fires

    ana.reporter.add_health_alert.assert_called_once()
    on_disk = load_state_file(state_file)
    assert on_disk["watchdog_last_alert_at"]
