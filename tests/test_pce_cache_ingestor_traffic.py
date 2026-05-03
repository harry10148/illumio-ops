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
