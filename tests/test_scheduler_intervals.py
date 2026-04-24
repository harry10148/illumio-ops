"""Tests for monitor_cycle trigger interval based on pce_cache.enabled."""
from unittest.mock import MagicMock


def _fake_cm(cache_enabled: bool, rule_check_interval: int = 300):
    cm = MagicMock()
    cm.config = {
        "api": {"url": "https://pce", "org_id": "1", "key": "k", "secret": "s", "verify_ssl": False},
        "rule_scheduler": {"check_interval_seconds": rule_check_interval},
        "settings": {"timezone": "UTC"},
    }
    cm.models.pce_cache.enabled = cache_enabled
    cm.models.pce_cache.events_poll_interval_seconds = 60
    cm.models.pce_cache.traffic_poll_interval_seconds = 300
    cm.models.siem.enabled = False
    return cm


def test_monitor_tick_is_30s_when_cache_enabled():
    from src.scheduler import build_scheduler
    cm = _fake_cm(cache_enabled=True)
    sched = build_scheduler(cm, interval_minutes=10)
    job = sched.get_job("monitor_cycle")
    assert job.trigger.interval.total_seconds() == 30


def test_monitor_tick_uses_interval_minutes_when_cache_disabled():
    from src.scheduler import build_scheduler
    cm = _fake_cm(cache_enabled=False)
    sched = build_scheduler(cm, interval_minutes=10)
    job = sched.get_job("monitor_cycle")
    assert job.trigger.interval.total_seconds() == 600
