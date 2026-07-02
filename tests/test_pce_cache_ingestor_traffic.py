from datetime import datetime, timezone, timedelta
import hashlib

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import PceTrafficFlowRaw


@pytest.fixture
def session_factory(tmp_path):
    from src.pce_cache.schema import init_schema
    engine = create_engine(f"sqlite:///{tmp_path / 'c.sqlite'}")
    init_schema(engine)
    return sessionmaker(engine)


def _mk_flow(i, action="blocked", ts=None):
    if ts is None:
        ts = datetime.now(timezone.utc)
    first = ts.isoformat()
    last = (ts + timedelta(seconds=1)).isoformat()
    return {
        "src_ip": f"10.0.{i}.1",
        "dst_ip": f"10.1.{i}.1",
        "port": 443,
        "protocol": "tcp",
        "action": action,
        "flow_count": 1,
        "bytes_in": 100,
        "bytes_out": 200,
        "first_detected": first,
        "last_detected": last,
        "src_workload": "web",
        "dst_workload": "db",
    }


class FakeApiClient:
    def __init__(self, flows):
        self._flows = flows
        self.calls = 0

    def get_traffic_flows_async(self, max_results=200000, rate_limit=False, **kw):
        self.calls += 1
        return self._flows[:max_results]


def test_traffic_ingestor_writes_blocked_flows(session_factory):
    from src.pce_cache.ingestor_traffic import TrafficIngestor
    from src.pce_cache.watermark import WatermarkStore

    flows = [_mk_flow(i, action="blocked") for i in range(10)]
    fake = FakeApiClient(flows)
    ing = TrafficIngestor(api=fake, session_factory=session_factory,
                          watermark=WatermarkStore(session_factory))
    count = ing.run_once()
    assert count == 10
    assert fake.calls == 1
    with session_factory() as s:
        rows = s.execute(select(PceTrafficFlowRaw)).scalars().all()
    assert len(rows) == 10


def test_traffic_ingestor_dedupes_on_flow_hash(session_factory):
    from src.pce_cache.ingestor_traffic import TrafficIngestor
    from src.pce_cache.watermark import WatermarkStore

    ts = datetime.now(timezone.utc)
    flows = [_mk_flow(1, ts=ts)]
    fake = FakeApiClient(flows)
    ing = TrafficIngestor(api=fake, session_factory=session_factory,
                          watermark=WatermarkStore(session_factory))
    assert ing.run_once() == 1
    assert ing.run_once() == 0  # same flow_hash, no re-insert


def test_traffic_ingestor_applies_sampler_to_allowed(session_factory):
    from src.pce_cache.ingestor_traffic import TrafficIngestor
    from src.pce_cache.watermark import WatermarkStore

    flows = [_mk_flow(i, action="allowed") for i in range(100)]
    fake = FakeApiClient(flows)
    ing = TrafficIngestor(api=fake, session_factory=session_factory,
                          watermark=WatermarkStore(session_factory),
                          sample_ratio_allowed=10)
    count = ing.run_once()
    # 1:10 sampling → expect 5–15 out of 100
    assert 5 <= count <= 20


def test_run_once_logs_poll_summary_even_on_empty(session_factory, caplog):
    """Empty PCE response must still emit an INFO line so silent skips
    are visible in the log timeline."""
    import logging
    from unittest.mock import MagicMock
    from src.pce_cache.ingestor_traffic import TrafficIngestor
    from src.pce_cache.watermark import WatermarkStore

    fake = MagicMock()
    fake.get_traffic_flows_async = MagicMock(return_value=[])
    ing = TrafficIngestor(api=fake, session_factory=session_factory,
                           watermark=WatermarkStore(session_factory))
    with caplog.at_level(logging.INFO, logger="src.pce_cache.ingestor_traffic"):
        n = ing.run_once()
    assert n == 0
    # Must contain a poll-summary line that names fetched + inserted counts
    assert any("Traffic ingest poll" in rec.message for rec in caplog.records), \
        f"expected 'Traffic ingest poll' line; got: {[r.message for r in caplog.records]}"


def test_run_once_emits_poll_log_even_when_insert_batch_raises(session_factory, caplog):
    """Regression: if _insert_batch raises mid-run (e.g., DB locked), the
    poll-summary log must still emit so the operator's timeline isn't blank
    on the failure case."""
    import logging
    from unittest.mock import MagicMock
    from src.pce_cache.ingestor_traffic import TrafficIngestor
    from src.pce_cache.watermark import WatermarkStore

    fake = MagicMock()
    fake.get_traffic_flows_async = MagicMock(return_value=[{"src_ip": "1.1.1.1"}])
    ing = TrafficIngestor(api=fake, session_factory=session_factory,
                           watermark=WatermarkStore(session_factory))
    # Force _insert_batch to raise
    ing._insert_batch = MagicMock(side_effect=RuntimeError("DB locked"))
    with caplog.at_level(logging.INFO, logger="src.pce_cache.ingestor_traffic"):
        with __import__("pytest").raises(RuntimeError):
            ing.run_once()
    assert any("Traffic ingest poll" in rec.message for rec in caplog.records), \
        f"expected poll log on insert failure; got: {[r.message for r in caplog.records]}"


class BumpingApiClient:
    """Returns the SAME flow on both polls (identical first_detected → identical
    flow_hash), but with a later last_detected and higher byte/flow counters on
    the 2nd pull — simulating a long-lived flow re-pulled inside the grace
    window."""

    _FIRST = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc).isoformat()

    def __init__(self):
        self.calls = 0

    def _flow(self, last, fc, bi, bo):
        return {
            "src_ip": "10.0.0.1", "dst_ip": "10.0.0.2", "port": 443,
            "protocol": "tcp", "action": "blocked", "flow_count": fc,
            "bytes_in": bi, "bytes_out": bo,
            "first_detected": self._FIRST, "last_detected": last,
        }

    def get_traffic_flows_async(self, max_results=200000, rate_limit=False, **kw):
        self.calls += 1
        if self.calls == 1:
            last = datetime(2026, 5, 1, 12, 1, 0, tzinfo=timezone.utc).isoformat()
            return [self._flow(last, fc=1, bi=100, bo=200)]
        last = datetime(2026, 5, 1, 12, 6, 0, tzinfo=timezone.utc).isoformat()
        return [self._flow(last, fc=5, bi=500, bo=600)]


def test_repulled_flow_refreshes_volatile_counters(session_factory):
    """ON CONFLICT must refresh (not freeze) last_detected/bytes/flow_count for
    a re-pulled long-lived flow, taking GREATEST so counters never shrink."""
    from src.pce_cache.ingestor_traffic import TrafficIngestor
    from src.pce_cache.watermark import WatermarkStore

    ing = TrafficIngestor(api=BumpingApiClient(), session_factory=session_factory,
                          watermark=WatermarkStore(session_factory))
    assert ing.run_once() == 1   # genuinely new row
    assert ing.run_once() == 0   # same flow_hash → update, not a new insert
    with session_factory() as s:
        rows = s.execute(select(PceTrafficFlowRaw)).scalars().all()
    assert len(rows) == 1        # still one row (deduped on flow_hash)
    row = rows[0]
    assert row.bytes_in == 500
    assert row.bytes_out == 600
    assert row.flow_count == 5
    # last_detected advanced to the later sighting (GREATEST), read back naive
    assert row.last_detected.replace(tzinfo=timezone.utc) == \
        datetime(2026, 5, 1, 12, 6, 0, tzinfo=timezone.utc)


def test_repulled_flow_does_not_reenqueue_siem(session_factory):
    """Refreshing a re-pulled flow must NOT re-enqueue it to SIEM — only the
    first (genuinely new) insert enqueues. Otherwise every grace-window re-pull
    floods destinations with duplicate dispatches."""
    from src.pce_cache.ingestor_traffic import TrafficIngestor
    from src.pce_cache.watermark import WatermarkStore
    from src.pce_cache.models import SiemDispatch

    ing = TrafficIngestor(api=BumpingApiClient(), session_factory=session_factory,
                          watermark=WatermarkStore(session_factory),
                          siem_destinations=["splunk"])
    ing.run_once()
    ing.run_once()
    with session_factory() as s:
        dispatches = s.execute(select(SiemDispatch)).scalars().all()
    assert len(dispatches) == 1


def test_repulled_flow_bumps_ingested_at(session_factory):
    """F6：re-pull 一筆既有 flow（同 flow_hash）必須把 ingested_at bump 到本次
    ingest 時間，而非凍結在首次插入時的值——archiver 的匯出游標依
    (ingested_at, id) 前進，不 bump 就永遠不會重新撿到這筆持續成長的列，
    造成長壽 flow 的 archive 計數系統性低於 live cache（根因）。"""
    from src.pce_cache.ingestor_traffic import TrafficIngestor
    from src.pce_cache.watermark import WatermarkStore

    ing = TrafficIngestor(api=BumpingApiClient(), session_factory=session_factory,
                          watermark=WatermarkStore(session_factory))
    ing.run_once()
    with session_factory() as s:
        first_ingested_at = s.execute(select(PceTrafficFlowRaw)).scalar_one().ingested_at

    ing.run_once()  # re-pull：同 flow_hash，只更新
    with session_factory() as s:
        second_ingested_at = s.execute(select(PceTrafficFlowRaw)).scalar_one().ingested_at

    assert second_ingested_at > first_ingested_at


def test_since_cursor_attaches_utc_offset_to_naive_watermark(session_factory):
    """Regression: SQLite reads last_timestamp back NAIVE, so the emitted `since`
    had no tz offset and the PCE rejected it (HTTP 406 invalid_timestamp). The
    cursor must carry a UTC offset, mirroring EventsIngestor."""
    from src.pce_cache.ingestor_traffic import TrafficIngestor
    from src.pce_cache.models import IngestionWatermark
    from src.pce_cache.watermark import WatermarkStore

    naive_ts = datetime(2026, 5, 1, 12, 0, 0)  # mimics SQLite read-back (no tz)
    with session_factory.begin() as s:
        s.add(IngestionWatermark(source="traffic", last_timestamp=naive_ts,
                                 last_sync_at=naive_ts, last_status="ok"))

    ing = TrafficIngestor(api=FakeApiClient([]), session_factory=session_factory,
                          watermark=WatermarkStore(session_factory))
    since = ing._since_cursor()

    assert since is not None
    parsed = datetime.fromisoformat(since)
    assert parsed.tzinfo is not None, "PCE rejects naive timestamps (HTTP 406)"
    assert parsed.utcoffset() == timedelta(0)
    # 5-minute grace window still applied, now with a UTC offset
    assert parsed == datetime(2026, 5, 1, 11, 55, 0, tzinfo=timezone.utc)


def test_traffic_run_once_records_error_status_on_insert_failure(session_factory):
    import pytest
    from sqlalchemy.exc import OperationalError
    from src.pce_cache.ingestor_traffic import TrafficIngestor
    from src.pce_cache.watermark import WatermarkStore
    from src.pce_cache.models import IngestionWatermark

    fake = FakeApiClient([_mk_flow(1)])
    ing = TrafficIngestor(api=fake, session_factory=session_factory,
                          watermark=WatermarkStore(session_factory))

    def _boom(_flows):
        raise OperationalError("INSERT", {}, Exception("database is locked"))
    ing._insert_batch = _boom

    with pytest.raises(OperationalError):        # re-raise 契約保留
        ing.run_once()

    with session_factory() as s:
        row = s.get(IngestionWatermark, "traffic")
    assert row is not None                        # record_error 必須在 re-raise 前寫入 watermark
    assert row.last_status == "error"
    assert "database is locked" in (row.last_error or "")
