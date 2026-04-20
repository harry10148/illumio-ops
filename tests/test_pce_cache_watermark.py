from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def session_factory(tmp_path):
    from src.pce_cache.schema import init_schema
    engine = create_engine(f"sqlite:///{tmp_path / 'c.sqlite'}")
    init_schema(engine)
    return sessionmaker(engine)


def test_watermark_initially_empty(session_factory):
    from src.pce_cache.watermark import WatermarkStore
    ws = WatermarkStore(session_factory)
    assert ws.get("events") is None


def test_watermark_roundtrip(session_factory):
    from src.pce_cache.watermark import WatermarkStore
    ws = WatermarkStore(session_factory)
    ts = datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc)
    ws.advance("events", last_timestamp=ts, last_href="/orgs/1/events/abc")
    got = ws.get("events")
    # SQLite doesn't preserve tzinfo; compare naive datetimes
    assert got.last_timestamp == ts.replace(tzinfo=None)
    assert got.last_href == "/orgs/1/events/abc"


def test_watermark_records_error(session_factory):
    from src.pce_cache.watermark import WatermarkStore
    ws = WatermarkStore(session_factory)
    ws.record_error("traffic", "429 rate limited")
    got = ws.get("traffic")
    assert got.last_status == "error"
    assert "rate limited" in got.last_error
