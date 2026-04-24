"""Tests for src/pce_cache/lag_monitor.py (Task 7 — cache lag monitoring)."""
from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def session_factory(tmp_path):
    from src.pce_cache.schema import init_schema
    engine = create_engine(f"sqlite:///{tmp_path / 'lag.sqlite'}")
    init_schema(engine)
    return sessionmaker(engine)


def _seed_watermark(sf, source: str, last_sync_at: datetime):
    from src.pce_cache.models import IngestionWatermark
    with sf.begin() as s:
        wm = IngestionWatermark(
            source=source,
            last_sync_at=last_sync_at,
        )
        s.add(wm)


def test_lag_monitor_silent_when_within_threshold(session_factory):
    from src.pce_cache.lag_monitor import check_cache_lag
    recent = datetime.now(timezone.utc) - timedelta(seconds=60)
    _seed_watermark(session_factory, "events", recent)
    results = check_cache_lag(session_factory, max_lag_seconds=300)
    assert all(r["level"] == "ok" for r in results)


def test_lag_monitor_warns_when_exceeds_threshold(session_factory):
    from src.pce_cache.lag_monitor import check_cache_lag
    stale = datetime.now(timezone.utc) - timedelta(seconds=400)
    _seed_watermark(session_factory, "events", stale)
    results = check_cache_lag(session_factory, max_lag_seconds=300)
    assert any(r["level"] == "warning" for r in results)


def test_lag_monitor_error_when_exceeds_2x_threshold(session_factory):
    from src.pce_cache.lag_monitor import check_cache_lag
    very_stale = datetime.now(timezone.utc) - timedelta(seconds=700)
    _seed_watermark(session_factory, "events", very_stale)
    results = check_cache_lag(session_factory, max_lag_seconds=300)
    assert any(r["level"] == "error" for r in results)
