from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import PceTrafficFlowRaw


@pytest.fixture
def session_factory(tmp_path):
    from src.pce_cache.schema import init_schema
    engine = create_engine(f"sqlite:///{tmp_path / 'g.sqlite'}")
    init_schema(engine)
    return sessionmaker(engine)


def _seed(sf, n):
    now = datetime.now(timezone.utc)
    with sf.begin() as s:
        for i in range(n):
            s.add(PceTrafficFlowRaw(
                flow_hash=f"g-h{i}", src_ip="1.1.1.1", dst_ip="2.2.2.2",
                port=80, protocol="tcp", action="allowed", flow_count=1,
                bytes_in=0, bytes_out=0, first_detected=now,
                last_detected=now, ingested_at=now, raw_json="{}"))
    return now


def test_reader_raises_when_window_exceeds_cap(session_factory):
    from src.pce_cache.reader import CacheReader, CacheReadTooLarge
    now = _seed(session_factory, 3)
    reader = CacheReader(session_factory, events_retention_days=90,
                         traffic_raw_retention_days=7, read_max_rows=2)
    win = (now - timedelta(hours=1), now + timedelta(hours=1))
    with pytest.raises(CacheReadTooLarge) as ei:
        reader.read_flows_raw(*win)
    assert ei.value.count == 3 and ei.value.cap == 2
    with pytest.raises(CacheReadTooLarge):
        reader.read_flows_df(*win)


def test_reader_unlimited_by_default(session_factory):
    from src.pce_cache.reader import CacheReader
    now = _seed(session_factory, 3)
    reader = CacheReader(session_factory, events_retention_days=90,
                         traffic_raw_retention_days=7)
    rows = reader.read_flows_raw(now - timedelta(hours=1), now + timedelta(hours=1))
    assert len(rows) == 3


def test_analyzer_falls_back_to_api_on_too_large():
    from src.analyzer import Analyzer
    from src.pce_cache.reader import CacheReadTooLarge

    class FakeReader:
        def cover_state(self, *a):
            return "full"
        def read_flows_raw(self, *a, **k):
            raise CacheReadTooLarge(10, 5)

    class FakeApi:
        def execute_traffic_query_stream(self, *a, **k):
            return iter([{"x": 1}])

    a = Analyzer.__new__(Analyzer)  # 跳過建構子，只測 _fetch_query_flows
    a._cache_reader = FakeReader()
    a.api = FakeApi()
    flows, source = a._fetch_query_flows(
        "2026-07-01T00:00:00Z", "2026-07-02T00:00:00Z",
        query_pds=["allowed"], query_spec=None, needs_draft=False)
    assert source == "api"
    assert list(flows) == [{"x": 1}]
