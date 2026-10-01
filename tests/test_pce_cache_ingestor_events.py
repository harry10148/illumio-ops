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


def _parse(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


class FakeApiClient:
    """模擬 PCE GET /events：依 [start, end] 篩選，碰 max_results 時只回最新的 N 筆。"""

    def __init__(self, events):
        self._events = events
        self.calls = []

    def fetch_events(self, start_time_str, end_time_str=None, max_results=5000,
                     rate_limit=False):
        self.calls.append((start_time_str, end_time_str, max_results))
        start = _parse(start_time_str)
        end = _parse(end_time_str) if end_time_str else None
        hits = [e for e in self._events
                if _parse(e["timestamp"]) >= start
                and (end is None or _parse(e["timestamp"]) <= end)]
        hits.sort(key=lambda e: e["timestamp"], reverse=True)
        return hits[:max_results]


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


def test_event_fetch_releases_cache_write_lane_until_persist():
    """Slow PCE I/O must not own the lock shared with traffic/cache writers."""
    from src.pce_cache.ingestor_events import EventsIngestor

    class RecordingLock:
        held = False

        def __enter__(self):
            assert not self.held
            self.held = True

        def __exit__(self, exc_type, exc, tb):
            self.held = False

    lock = RecordingLock()
    event = _mk_event(1, datetime.now(timezone.utc))

    class Api:
        last_fetch_error = None

        def fetch_events(self, *args, **kwargs):
            assert lock.held is False
            return [event]

    class Watermark:
        def get(self, source):
            return None

        def advance(self, source, **kwargs):
            assert lock.held is True

        def record_error(self, source, error):
            assert lock.held is True

    class Ingestor(EventsIngestor):
        def _insert_batch(self, events):
            assert lock.held is True
            return len(events)

    ing = Ingestor(
        api=Api(),
        session_factory=None,
        watermark=Watermark(),
        write_lock=lock,
    )

    assert ing.run_once() == 1
    assert lock.held is False


def test_ingestor_writes_events_to_cache(session_factory):
    from src.pce_cache.ingestor_events import EventsIngestor
    from src.pce_cache.watermark import WatermarkStore

    ts = datetime.now(timezone.utc) - timedelta(minutes=1)
    fake = FakeApiClient(events=[_mk_event(1, ts), _mk_event(2, ts + timedelta(seconds=1))])
    ing = EventsIngestor(api=fake, session_factory=session_factory,
                         watermark=WatermarkStore(session_factory),
                         async_threshold=10000)
    count = ing.run_once()
    assert count == 2
    with session_factory() as s:
        rows = s.execute(select(PceEvent)).scalars().all()
    assert {r.pce_event_id for r in rows} == {"uuid-1", "uuid-2"}


def test_ingestor_coerces_null_status_to_default(session_factory):
    """A PCE event with explicit "status": null must not crash the chunked insert
    (pce_events.status is NOT NULL); it is stored with the default "success",
    matching the absent-status convention, and the rest of the batch survives."""
    from src.pce_cache.ingestor_events import EventsIngestor
    from src.pce_cache.watermark import WatermarkStore

    ts = datetime.now(timezone.utc) - timedelta(minutes=1)
    null_status = _mk_event(1, ts)
    null_status["status"] = None        # PCE returns explicit null, not an absent key
    good = _mk_event(2, ts + timedelta(seconds=1))
    fake = FakeApiClient(events=[null_status, good])
    ing = EventsIngestor(api=fake, session_factory=session_factory,
                         watermark=WatermarkStore(session_factory),
                         async_threshold=10000)

    count = ing.run_once()

    assert count == 2                   # whole batch inserted, no rollback
    with session_factory() as s:
        by_id = {r.pce_event_id: r.status
                 for r in s.execute(select(PceEvent)).scalars().all()}
    assert by_id["uuid-1"] == "success"  # null coerced to default
    assert by_id["uuid-2"] == "success"


def test_ingestor_skips_duplicates(session_factory):
    from src.pce_cache.ingestor_events import EventsIngestor
    from src.pce_cache.watermark import WatermarkStore

    ts = datetime.now(timezone.utc) - timedelta(minutes=1)
    fake = FakeApiClient(events=[_mk_event(1, ts)])
    ing = EventsIngestor(api=fake, session_factory=session_factory,
                         watermark=WatermarkStore(session_factory),
                         async_threshold=10000)
    assert ing.run_once() == 1
    assert ing.run_once() == 0  # same event, unique pce_href blocks re-insert


def test_force_async_is_accepted_for_compat(session_factory):
    """force_async 只為簽名相容保留；一律走帶結束時間的 fetch_events。"""
    from src.pce_cache.ingestor_events import EventsIngestor
    from src.pce_cache.watermark import WatermarkStore

    ts = datetime.now(timezone.utc) - timedelta(minutes=1)
    fake = FakeApiClient(events=[_mk_event(i, ts) for i in range(20)])
    ing = EventsIngestor(api=fake, session_factory=session_factory,
                         watermark=WatermarkStore(session_factory),
                         async_threshold=10000)
    assert ing.run_once(force_async=True) == 20
    assert fake.calls and fake.calls[0][1] is not None  # 帶 end_time


class _RecordingApiClient:
    """Captures the start time passed to fetch_events so we can assert format."""
    def __init__(self):
        self.since_seen = None

    def fetch_events(self, start_time_str, end_time_str=None, max_results=5000,
                     rate_limit=False):
        self.since_seen = start_time_str
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
    parsed = _parse(api.since_seen)
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

    # watermark 12:00 − 20 分鐘 overlap（兩個 VEN 上報週期，晚到事件 re-pull）
    assert api.since_seen == "2026-05-01T11:40:00Z"


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

    parsed = _parse(api.since_seen)
    assert parsed.tzinfo is not None
    # aware watermark 減 overlap 後仍為 aware（不被剝除 tz）
    assert parsed.astimezone(timezone.utc) == aware_ts - timedelta(minutes=20)


def test_overlap_is_configurable(session_factory):
    from src.pce_cache.ingestor_events import EventsIngestor
    from src.pce_cache.models import IngestionWatermark
    from src.pce_cache.watermark import WatermarkStore

    aware_ts = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
    with session_factory.begin() as s:
        s.add(IngestionWatermark(source="events", last_timestamp=aware_ts,
                                 last_sync_at=aware_ts, last_status="ok"))
    api = _RecordingApiClient()
    EventsIngestor(api=api, session_factory=session_factory,
                   watermark=WatermarkStore(session_factory),
                   overlap=timedelta(minutes=45)).run_once()
    assert api.since_seen == "2026-05-01T11:15:00Z"


def _wm_ts(session_factory):
    from src.pce_cache.models import IngestionWatermark
    with session_factory() as s:
        ts = s.get(IngestionWatermark, "events").last_timestamp
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def test_cap_hit_bisects_until_window_drained(session_factory):
    """碰上限時 PCE 只回最新 N 筆；舊版保留這 N 筆就推 watermark，較舊的永久遺失。
    現在要二分切窗把整個視窗抓完。"""
    from src.pce_cache.ingestor_events import EventsIngestor
    from src.pce_cache.watermark import WatermarkStore

    base = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=3)
    events = [_mk_event(i, base + timedelta(minutes=5 * i)) for i in range(25)]
    fake = FakeApiClient(events=events)
    ing = EventsIngestor(api=fake, session_factory=session_factory,
                         watermark=WatermarkStore(session_factory),
                         async_threshold=10)

    assert ing.run_once() == 25            # 一筆都沒漏
    assert ing.last_run_overflow is None   # 抽乾了，不算資料遺失
    assert len(fake.calls) > 1             # 確實有切窗
    with session_factory() as s:
        assert len(s.execute(select(PceEvent)).scalars().all()) == 25
    assert _wm_ts(session_factory) == base + timedelta(minutes=5 * 24)


def test_cap_unresolvable_reports_overflow(session_factory):
    """同一秒超過上限、切到最小跨度仍碰頂：保留拿到的資料並回報 overflow。"""
    from src.pce_cache.ingestor_events import EventsIngestor
    from src.pce_cache.watermark import WatermarkStore

    ts = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=2)
    fake = FakeApiClient(events=[_mk_event(i, ts) for i in range(15)])
    ing = EventsIngestor(api=fake, session_factory=session_factory,
                         watermark=WatermarkStore(session_factory),
                         async_threshold=10)

    assert ing.run_once() == 10
    assert ing.last_run_overflow is not None
    assert ing.last_run_overflow["max_results"] == 10
    assert ing.last_run_overflow["source"] == "cache_ingest"


def test_watermark_never_advances_past_query_end(session_factory):
    """VEN 時鐘偏快送來未來時間戳時，watermark 不得被推到未來。"""
    from src.pce_cache.ingestor_events import EventsIngestor
    from src.pce_cache.watermark import WatermarkStore

    future = datetime.now(timezone.utc) + timedelta(hours=2)

    class Api:
        last_fetch_error = None

        def fetch_events(self, *a, **kw):
            return [_mk_event(1, future)]

    before = datetime.now(timezone.utc)
    EventsIngestor(api=Api(), session_factory=session_factory,
                   watermark=WatermarkStore(session_factory)).run_once()
    assert _wm_ts(session_factory) <= before + timedelta(seconds=5)


class _ConnectionFailingApiClient:
    """Mirrors real ApiClient: get_events() swallows a connection-layer PCE
    failure into [] but reports it via last_fetch_error (see
    src/api_client.py fetch_events / watchdog-live-reverify-report.md step 2)."""
    last_fetch_error = "Connection refused"

    def fetch_events(self, *args, **kw):
        return []


def test_run_once_records_error_on_silently_swallowed_connection_failure(session_factory):
    """RED (pre-fix): a connection-layer failure inside get_events() was
    swallowed to [] by fetch_events(), so run_once() never saw an exception and
    the watermark stayed 'ok' — the watchdog got no signal on a real PCE
    outage. Fix: check ApiClient.last_fetch_error and record it the same as
    any other fetch failure."""
    from src.pce_cache.ingestor_events import EventsIngestor
    from src.pce_cache.watermark import WatermarkStore
    from src.pce_cache.models import IngestionWatermark

    fake = _ConnectionFailingApiClient()
    ing = EventsIngestor(api=fake, session_factory=session_factory,
                         watermark=WatermarkStore(session_factory), async_threshold=10000)

    count = ing.run_once()

    assert count == 0
    with session_factory() as s:
        row = s.get(IngestionWatermark, "events")
    assert row is not None and row.last_status == "error"
    assert "Connection refused" in (row.last_error or "")


def test_run_once_does_not_record_error_on_genuinely_empty_response(session_factory):
    """Reverse pin: PCE reachable, genuinely 0 new events (no last_fetch_error)
    must NOT be recorded as an error — a false alarm is as bad as a missed one."""
    from src.pce_cache.ingestor_events import EventsIngestor
    from src.pce_cache.watermark import WatermarkStore
    from src.pce_cache.models import IngestionWatermark

    fake = FakeApiClient(events=[])  # no last_fetch_error attribute at all
    ing = EventsIngestor(api=fake, session_factory=session_factory,
                         watermark=WatermarkStore(session_factory), async_threshold=10000)

    count = ing.run_once()

    assert count == 0
    with session_factory() as s:
        row = s.get(IngestionWatermark, "events")
    assert row is None or row.last_status != "error"


def test_events_run_once_records_error_status_on_insert_failure(session_factory):
    import pytest
    from sqlalchemy.exc import OperationalError
    from src.pce_cache.ingestor_events import EventsIngestor
    from src.pce_cache.watermark import WatermarkStore
    from src.pce_cache.models import IngestionWatermark

    ts = datetime.now(timezone.utc)
    fake = FakeApiClient(events=[_mk_event(1, ts)])
    ing = EventsIngestor(api=fake, session_factory=session_factory,
                         watermark=WatermarkStore(session_factory), async_threshold=10000)

    def _boom(_events):
        raise OperationalError("INSERT", {}, Exception("database is locked"))
    ing._insert_batch = _boom

    with pytest.raises(OperationalError):
        ing.run_once()

    with session_factory() as s:
        row = s.get(IngestionWatermark, "events")
    assert row is not None and row.last_status == "error"
    assert "database is locked" in (row.last_error or "")
