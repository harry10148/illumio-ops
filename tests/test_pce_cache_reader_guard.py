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


def test_guard_counts_decision_filtered_rows_not_whole_window(session_factory):
    """read_flows_df 的護欄必須以 policy_decisions 過濾後的列數判斷：
    全窗超限但過濾後遠低於上限時不可誤拋 CacheReadTooLarge（誤拋會 fallback
    到 200k 硬上限的 live API，反而造成截斷）。"""
    from datetime import datetime, timezone
    from src.pce_cache.reader import CacheReader, CacheReadTooLarge
    now = _seed(session_factory, 3)  # 3 列 action='allowed'
    with session_factory.begin() as s:
        s.add(PceTrafficFlowRaw(
            flow_hash="g-blocked", src_ip="1.1.1.1", dst_ip="2.2.2.2",
            port=80, protocol="tcp", action="blocked", flow_count=1,
            bytes_in=0, bytes_out=0, first_detected=now,
            last_detected=now, ingested_at=now, raw_json="{}"))
    reader = CacheReader(session_factory, events_retention_days=90,
                         traffic_raw_retention_days=7, read_max_rows=2)
    win = (now - timedelta(hours=1), now + timedelta(hours=1))
    # 全窗 4 列 > cap 2，但 blocked 只有 1 列 → 不得拋
    df = reader.read_flows_df(*win, policy_decisions=["blocked"])
    assert len(df) == 1
    # 未過濾時仍要保護
    with pytest.raises(CacheReadTooLarge):
        reader.read_flows_df(*win)


def test_read_events_guard_raises_over_cap(session_factory):
    """read_events 也要有 read_max_rows 護欄：超限 fail-closed 拋
    CacheReadTooLarge，而非把整窗 materialize 進長駐 process（OOM 風險）。"""
    from datetime import datetime, timezone
    from src.pce_cache.models import PceEvent
    from src.pce_cache.reader import CacheReader, CacheReadTooLarge
    now = datetime.now(timezone.utc)
    with session_factory.begin() as s:
        for i in range(3):
            s.add(PceEvent(
                pce_href=f"/orgs/1/events/g{i}", pce_event_id=f"g{i}",
                timestamp=now, event_type="t", severity="info",
                status="success", pce_fqdn="pce", raw_json="{}",
                ingested_at=now))
    reader = CacheReader(session_factory, events_retention_days=90,
                         traffic_raw_retention_days=7, read_max_rows=2)
    with pytest.raises(CacheReadTooLarge):
        reader.read_events(now - timedelta(hours=1), now + timedelta(hours=1))
    ok = CacheReader(session_factory, events_retention_days=90,
                     traffic_raw_retention_days=7, read_max_rows=10)
    assert len(ok.read_events(now - timedelta(hours=1), now + timedelta(hours=1))) == 3
