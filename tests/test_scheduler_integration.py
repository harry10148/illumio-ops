"""Integration tests for scheduler job dispatch.

Uses next_run_time=datetime.now() pattern (per plan's fallback recommendation)
to force immediate execution rather than relying on freezegun time-travel with
background threads (which is inherently timing-sensitive).
"""
import time
import threading
from datetime import datetime
from unittest.mock import MagicMock, patch


def _fake_cm(rule_check_interval=300):
    cm = MagicMock()
    cm.config = {
        "api": {"url": "https://pce", "org_id": "1", "key": "k", "secret": "s", "verify_ssl": False},
        "rule_scheduler": {"check_interval_seconds": rule_check_interval},
        "settings": {"timezone": "UTC"},
    }
    return cm


def test_scheduler_starts_and_stops_cleanly():
    """Scheduler start/shutdown lifecycle completes without error."""
    from src.scheduler import build_scheduler
    cm = _fake_cm()
    sched = build_scheduler(cm, interval_minutes=60)
    sched.start()
    assert sched.running
    sched.shutdown(wait=True)
    assert not sched.running


def test_monitor_cycle_fires_via_next_run_time():
    """monitor_cycle job fires when next_run_time is now."""
    from src.scheduler import build_scheduler

    fired = threading.Event()

    def fake_monitor(cm):
        fired.set()

    cm = _fake_cm()
    sched = build_scheduler(cm, interval_minutes=60)  # long interval so only next_run_time fires

    # Override next_run_time to fire immediately
    sched.get_job("monitor_cycle").modify(next_run_time=datetime.now(), func=fake_monitor)
    sched.start()
    try:
        fired.wait(timeout=3.0)
        assert fired.is_set(), "monitor_cycle did not fire within 3 seconds"
    finally:
        sched.shutdown(wait=True)


def test_report_tick_fires_via_next_run_time():
    """tick_report_schedules fires when next_run_time is now."""
    from src.scheduler import build_scheduler

    fired = threading.Event()

    def fake_tick(cm):
        fired.set()

    cm = _fake_cm()
    sched = build_scheduler(cm, interval_minutes=60)
    sched.get_job("tick_report_schedules").modify(next_run_time=datetime.now(), func=fake_tick)
    sched.start()
    try:
        fired.wait(timeout=3.0)
        assert fired.is_set(), "tick_report_schedules did not fire within 3 seconds"
    finally:
        sched.shutdown(wait=True)


def test_rule_tick_fires_via_next_run_time():
    """tick_rule_schedules fires when next_run_time is now."""
    from src.scheduler import build_scheduler

    fired = threading.Event()

    def fake_rule_tick(cm):
        fired.set()

    cm = _fake_cm()
    sched = build_scheduler(cm, interval_minutes=60)
    sched.get_job("tick_rule_schedules").modify(next_run_time=datetime.now(), func=fake_rule_tick)
    sched.start()
    try:
        fired.wait(timeout=3.0)
        assert fired.is_set(), "tick_rule_schedules did not fire within 3 seconds"
    finally:
        sched.shutdown(wait=True)


def test_shutdown_completes_under_10_seconds():
    """Scheduler shutdown with wait=True finishes in < 10 seconds."""
    from src.scheduler import build_scheduler

    cm = _fake_cm()
    sched = build_scheduler(cm, interval_minutes=60)
    sched.start()

    t_start = time.monotonic()
    sched.shutdown(wait=True)
    elapsed = time.monotonic() - t_start

    assert elapsed < 10.0, f"Shutdown took {elapsed:.1f}s — exceeds 10s limit"


def test_max_instances_prevents_concurrent_runs():
    """max_instances=1 means a slow job won't run concurrently."""
    from src.scheduler import build_scheduler

    run_count = [0]
    concurrent_max = [0]
    lock = threading.Lock()

    def slow_job(cm):
        with lock:
            run_count[0] += 1
            concurrent_max[0] = max(concurrent_max[0], run_count[0])
        time.sleep(0.1)
        with lock:
            run_count[0] -= 1

    cm = _fake_cm()
    sched = build_scheduler(cm, interval_minutes=60)
    sched.get_job("monitor_cycle").modify(next_run_time=datetime.now(), func=slow_job)
    sched.start()
    try:
        time.sleep(0.5)
    finally:
        sched.shutdown(wait=True)

    assert concurrent_max[0] <= 1, f"Concurrent runs exceeded 1: {concurrent_max[0]}"
