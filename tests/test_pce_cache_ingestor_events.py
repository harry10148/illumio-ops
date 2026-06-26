from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import PceEvent


@pytest.fixture
def session_factory(tmp_path):
    from src.pce_cache.schema import init_schema
    engine = create_engine(f"sqlite:///{tmp_path / 'c.sqlite'}")
    init_schema(engine)
    return sessionmaker(engine)


class FakeApiClient:
    def __init__(self, events, async_events=None):
        self._events = events
        self._async_events = async_events or []
        self.sync_calls = 0
        self.async_calls = 0

    def get_events(self, max_results=500, since=None, rate_limit=False, **kw):
        self.sync_calls += 1
        return self._events[:max_results]

    def get_events_async(self, since=None, rate_limit=False, **kw):
        self.async_calls += 1
        return self._async_events


def _mk_event(i, ts):
    return {
        "href": f"/orgs/1/events/{i}",
        "uuid": f"uuid-{i}",
        "timestamp": ts.isoformat(),
        "event_type": "policy.update",
        "severity": "info",
        "status": "success",
        "pce_fqdn": "pce.example.com",
    }


def test_ingestor_writes_events_to_cache(session_factory):
    from src.pce_cache.ingestor_events import EventsIngestor
    from src.pce_cache.watermark import WatermarkStore

    ts = datetime.now(timezone.utc)
    fake = FakeApiClient(events=[_mk_event(1, ts), _mk_event(2, ts + timedelta(seconds=1))])
    ing = EventsIngestor(api=fake, session_factory=session_factory,
                         watermark=WatermarkStore(session_factory),
                         async_threshold=10000)
    count = ing.run_once()
    assert count == 2
    with session_factory() as s:
        rows = s.execute(select(PceEvent)).scalars().all()
    assert {r.pce_event_id for r in rows} == {"uuid-1", "uuid-2"}


def test_ingestor_skips_duplicates(session_factory):
    from src.pce_cache.ingestor_events import EventsIngestor
    from src.pce_cache.watermark import WatermarkStore

    ts = datetime.now(timezone.utc)
    fake = FakeApiClient(events=[_mk_event(1, ts)])
    ing = EventsIngestor(api=fake, session_factory=session_factory,
                         watermark=WatermarkStore(session_factory),
                         async_threshold=10000)
    assert ing.run_once() == 1
    assert ing.run_once() == 0  # same event, unique pce_href blocks re-insert


def test_ingestor_switches_to_async_when_forced(session_factory):
    from src.pce_cache.ingestor_events import EventsIngestor
    from src.pce_cache.watermark import WatermarkStore

    ts = datetime.now(timezone.utc)
    async_batch = [_mk_event(i, ts) for i in range(20)]
    fake = FakeApiClient(events=[], async_events=async_batch)
    ing = EventsIngestor(api=fake, session_factory=session_factory,
                         watermark=WatermarkStore(session_factory),
                         async_threshold=10000)
    ing.run_once(force_async=True)
    assert fake.async_calls == 1


class _RecordingApiClient:
    """Captures the `since` value passed to get_events so we can assert format."""
    def __init__(self):
        self.since_seen = None

    def get_events(self, max_results=500, since=None, rate_limit=False, **kw):
        self.since_seen = since
        return []

    def get_events_async(self, since=None, rate_limit=False, **kw):
        self.since_seen = since
        return []


def test_since_cursor_cold_start_returns_24h_ago_with_tz(session_factory):
    from src.pce_cache.ingestor_events import EventsIngestor
    from src.pce_cache.watermark import WatermarkStore

    api = _RecordingApiClient()
    ing = EventsIngestor(api=api, session_factory=session_factory,
                         watermark=WatermarkStore(session_factory),
                         async_threshold=10000)
    ing.run_once()

    assert api.since_seen is not None and api.since_seen != ""
    parsed = datetime.fromisoformat(api.since_seen)
    assert parsed.tzinfo is not None, "PCE rejects naive timestamps (HTTP 406)"
    delta = datetime.now(timezone.utc) - parsed
    assert timedelta(hours=23, minutes=55) < delta < timedelta(hours=24, minutes=5)


def test_since_cursor_normalises_naive_watermark_to_utc(session_factory):
    from src.pce_cache.ingestor_events import EventsIngestor
    from src.pce_cache.models import IngestionWatermark
    from src.pce_cache.watermark import WatermarkStore

    naive_ts = datetime(2026, 5, 1, 12, 0, 0)  # mimics SQLite read-back
    with session_factory.begin() as s:
        s.add(IngestionWatermark(source="events", last_timestamp=naive_ts,
                                 last_sync_at=naive_ts, last_status="ok"))

    api = _RecordingApiClient()
    ing = EventsIngestor(api=api, session_factory=session_factory,
                         watermark=WatermarkStore(session_factory),
                         async_threshold=10000)
    ing.run_once()

    assert api.since_seen == "2026-05-01T12:00:00+00:00"


def test_since_cursor_preserves_aware_watermark(session_factory):
    from src.pce_cache.ingestor_events import EventsIngestor
    from src.pce_cache.models import IngestionWatermark
    from src.pce_cache.watermark import WatermarkStore

    aware_ts = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
    with session_factory.begin() as s:
        s.add(IngestionWatermark(source="events", last_timestamp=aware_ts,
                                 last_sync_at=aware_ts, last_status="ok"))

    api = _RecordingApiClient()
    ing = EventsIngestor(api=api, session_factory=session_factory,
                         watermark=WatermarkStore(session_factory),
                         async_threshold=10000)
    ing.run_once()

    parsed = datetime.fromisoformat(api.since_seen)
    assert parsed.tzinfo is not None
    assert parsed.astimezone(timezone.utc) == aware_ts


def test_async_threshold_stub_does_not_discard_sync_batch(session_factory):
    """Regression: when the sync pull hits the async threshold, the async path is
    an unimplemented stub returning []. The already-fetched sync events must be
    inserted (not discarded) and the watermark must advance to their max
    timestamp so the next poll pages forward instead of re-fetching forever."""
    from src.pce_cache.ingestor_events import EventsIngestor
    from src.pce_cache.models import IngestionWatermark
    from src.pce_cache.watermark import WatermarkStore

    base = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
    sync_batch = [_mk_event(i, base + timedelta(seconds=i)) for i in range(3)]
    fake = FakeApiClient(events=sync_batch, async_events=[])  # stub returns []
    ing = EventsIngestor(api=fake, session_factory=session_factory,
                         watermark=WatermarkStore(session_factory),
                         async_threshold=3)
    inserted = ing.run_once()

    assert fake.async_calls == 1            # cap path was taken
    assert inserted == 3                    # fetched events inserted, NOT discarded
    with session_factory() as s:
        rows = s.execute(select(PceEvent)).scalars().all()
        assert len(rows) == 3
        wm_row = s.get(IngestionWatermark, "events")
        advanced = wm_row.last_timestamp
    assert advanced is not None, "watermark must advance so paging continues"
    if advanced.tzinfo is None:             # SQLite reads back naive
        advanced = advanced.replace(tzinfo=timezone.utc)
    assert advanced == base + timedelta(seconds=2)


def test_async_threshold_uses_async_result_when_non_empty(session_factory):
    """When get_events_async is eventually implemented (returns a non-empty
    batch), the cap path must use the async result (current behavior preserved
    for the non-stub case)."""
    from src.pce_cache.ingestor_events import EventsIngestor
    from src.pce_cache.watermark import WatermarkStore

    ts = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
    sync_batch = [_mk_event(i, ts) for i in range(3)]            # hits cap=3
    async_batch = [_mk_event(100 + i, ts) for i in range(5)]    # real async data
    fake = FakeApiClient(events=sync_batch, async_events=async_batch)
    ing = EventsIngestor(api=fake, session_factory=session_factory,
                         watermark=WatermarkStore(session_factory),
                         async_threshold=3)
    inserted = ing.run_once()

    assert fake.async_calls == 1
    assert inserted == 5                     # async batch used
    with session_factory() as s:
        ids = {r.pce_event_id for r in s.execute(select(PceEvent)).scalars().all()}
    assert ids == {f"uuid-{100 + i}" for i in range(5)}
