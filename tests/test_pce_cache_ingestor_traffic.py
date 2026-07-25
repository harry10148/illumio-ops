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


class _ConnectionFailingApiClient:
    """Mirrors real ApiClient: get_traffic_flows_async() swallows a connection-
    layer PCE failure (submit status 0) into [] but reports it via
    last_fetch_error (see src/api/traffic_query.py _submit_and_stream_async_query
    / watchdog-live-reverify-report.md step 2 — traffic 鏈同構 bug)."""
    last_fetch_error = "Connection refused"

    def get_traffic_flows_async(self, max_results=200000, rate_limit=False, **kw):
        return []


def test_run_once_records_error_on_silently_swallowed_connection_failure(session_factory):
    """RED (pre-fix): a connection-layer failure was swallowed to [] inside
    the async query submit path, so run_once() never saw an exception and the
    watermark stayed 'ok'. Fix: _fetch_window checks ApiClient.last_fetch_error
    and raises, reaching run_once()'s except → watermark.record_error()."""
    from src.pce_cache.ingestor_traffic import TrafficIngestor
    from src.pce_cache.watermark import WatermarkStore
    from src.pce_cache.models import IngestionWatermark

    fake = _ConnectionFailingApiClient()
    ing = TrafficIngestor(api=fake, session_factory=session_factory,
                          watermark=WatermarkStore(session_factory))

    count = ing.run_once()

    assert count == 0
    with session_factory() as s:
        row = s.get(IngestionWatermark, "traffic")
    assert row is not None and row.last_status == "error"
    assert "Connection refused" in (row.last_error or "")


def test_run_once_does_not_record_error_on_genuinely_empty_response(session_factory):
    """Reverse pin: PCE reachable, genuinely 0 new flows (no last_fetch_error)
    must NOT be recorded as an error."""
    from src.pce_cache.ingestor_traffic import TrafficIngestor
    from src.pce_cache.watermark import WatermarkStore
    from src.pce_cache.models import IngestionWatermark

    fake = FakeApiClient([])  # no last_fetch_error attribute at all
    ing = TrafficIngestor(api=fake, session_factory=session_factory,
                          watermark=WatermarkStore(session_factory))

    count = ing.run_once()

    assert count == 0
    with session_factory() as s:
        row = s.get(IngestionWatermark, "traffic")
    assert row is None or row.last_status != "error"


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


class BisectFakeApi:
    """第一次（全窗）回滿 max_results 觸發二分；之後每個半窗回 1 筆。"""
    def __init__(self):
        self.windows = []  # (since, until) 呼叫紀錄

    def get_traffic_flows_async(self, max_results=200000, rate_limit=False,
                                since=None, until=None, **kw):
        self.windows.append((since, until))
        if len(self.windows) == 1:
            return [_mk_flow(i) for i in range(max_results)]
        return [_mk_flow(1000 + len(self.windows))]


def test_ingest_bisects_window_on_cap_hit(session_factory):
    from src.pce_cache.ingestor_traffic import TrafficIngestor
    from src.pce_cache.watermark import WatermarkStore

    fake = BisectFakeApi()
    ing = TrafficIngestor(api=fake, session_factory=session_factory,
                          watermark=WatermarkStore(session_factory), max_results=5)
    ing.run_once()
    # 1 次全窗（滿載）+ 2 次半窗
    assert len(fake.windows) == 3
    s0, u0 = fake.windows[0]
    s1, u1 = fake.windows[1]
    s2, u2 = fake.windows[2]
    assert s1 == s0 and u2 == u0 and u1 == s2  # 兩個半窗恰好拼回全窗


def test_ingest_single_call_below_cap(session_factory):
    # 回歸：未碰頂時維持單次呼叫
    from src.pce_cache.ingestor_traffic import TrafficIngestor
    from src.pce_cache.watermark import WatermarkStore

    flows = [_mk_flow(i) for i in range(3)]
    fake = FakeApiClient(flows)
    ing = TrafficIngestor(api=fake, session_factory=session_factory,
                          watermark=WatermarkStore(session_factory), max_results=5)
    assert ing.run_once() == 3
    assert fake.calls == 1


class AlwaysFullApi:
    """每個窗口都回滿載：驗證遞迴深度有界，不會無限二分。"""
    def __init__(self):
        self.calls = 0

    def get_traffic_flows_async(self, max_results=200000, **kw):
        self.calls += 1
        return [_mk_flow(i) for i in range(max_results)]


def test_ingest_bisect_depth_bounded(session_factory):
    from src.pce_cache.ingestor_traffic import TrafficIngestor
    from src.pce_cache.watermark import WatermarkStore

    fake = AlwaysFullApi()
    ing = TrafficIngestor(api=fake, session_factory=session_factory,
                          watermark=WatermarkStore(session_factory), max_results=2)
    ing.run_once()  # 不應 RecursionError / 無限迴圈
    # 深度 6 的完整二元樹：1 + 2 + ... + 64 = 127 次呼叫為上限
    assert fake.calls <= 127


class NestedLongLivedApi:
    """真實 PCE async query 形狀（巢狀 timestamp_range / dst_tb*）的長壽 flow：
    每次輪詢回同一筆（first_detected 相同 → flow_hash 相同），但 last_detected
    往後、位元組往上長。第 3 次刻意回一份「較舊」的快照（亂序重拉）。"""

    _FIRST = "2026-05-01T12:00:00.000Z"
    _SNAPSHOTS = [
        ("2026-05-01T12:01:00.000Z", 1000, 2000, 1),
        ("2026-05-01T12:06:00.000Z", 5000, 6000, 5),
        ("2026-05-01T12:02:00.000Z", 10, 20, 1),      # 亂序：較舊的快照
    ]

    def __init__(self):
        self.calls = 0

    def get_traffic_flows_async(self, max_results=200000, rate_limit=False, **kw):
        last, tbi, tbo, num = self._SNAPSHOTS[min(self.calls, len(self._SNAPSHOTS) - 1)]
        self.calls += 1
        return [{
            "src": {"ip": "10.0.0.1"}, "dst": {"ip": "10.0.0.2"},
            "service": {"port": 443, "proto": 6},
            "policy_decision": "blocked",
            "timestamp_range": {"first_detected": self._FIRST, "last_detected": last},
            "dst_tbi": tbi, "dst_tbo": tbo, "num_connections": num,
        }]


def _window_payload(session_factory, since):
    from src.pce_cache.subscriber import CacheSubscriber
    sub = CacheSubscriber(session_factory, consumer="analyzer",
                          source_table="pce_traffic_flows_raw")
    rows = sub.fetch_window_rows(since)
    assert len(rows) == 1
    return rows[0]


def test_repulled_flow_refreshes_cached_payload(session_factory):
    """R1 gate：re-pull 必須連 raw_json 一起刷新。

    Analyzer 只看得到 _row_to_dict 解出的 payload：視窗過濾讀
    timestamp_range.last_detected、bandwidth/volume 讀 dst_tb*。欄位刷新但
    payload 凍在初見值時，SQL 用新的 last_detected 選出這列、Analyzer 卻用舊
    時戳判定「不在視窗內」而丟掉——長壽 flow 在每個視窗被靜默漏掉。"""
    from src.analyzer import calculate_volume_mb
    from src.pce_cache.ingestor_traffic import TrafficIngestor
    from src.pce_cache.watermark import WatermarkStore

    ing = TrafficIngestor(api=NestedLongLivedApi(), session_factory=session_factory,
                          watermark=WatermarkStore(session_factory))
    ing.run_once()
    ing.run_once()

    # 視窗起點落在兩次 last_detected 之間：SQL 選得到（欄位已刷新），
    # payload 也必須說得出同一個新時戳，否則規則引擎會 fail-closed 丟掉。
    since = datetime(2026, 5, 1, 12, 3, 0, tzinfo=timezone.utc)
    payload = _window_payload(session_factory, since)
    assert payload["timestamp_range"]["last_detected"] == "2026-05-01T12:06:00.000Z"
    assert calculate_volume_mb(payload)[0] == pytest.approx(11000 / 1024 / 1024)
    assert payload["num_connections"] == 5

    with session_factory() as s:
        row = s.execute(select(PceTrafficFlowRaw)).scalar_one()
    # payload 與權威欄位不得互相打架（同一次判斷的兩邊資料來源）
    assert row.last_detected.replace(tzinfo=timezone.utc) == \
        datetime(2026, 5, 1, 12, 6, 0, tzinfo=timezone.utc)


def test_out_of_order_repull_does_not_roll_back_payload(session_factory):
    """亂序重拉（較舊的快照）不得把新 payload 蓋回舊的——欄位是 GREATEST，
    raw_json/report_json 則取 last_detected 較新的那一側。"""
    from src.pce_cache.ingestor_traffic import TrafficIngestor
    from src.pce_cache.watermark import WatermarkStore

    ing = TrafficIngestor(api=NestedLongLivedApi(), session_factory=session_factory,
                          watermark=WatermarkStore(session_factory))
    ing.run_once()
    ing.run_once()
    ing.run_once()   # 第 3 次回較舊的快照

    since = datetime(2026, 5, 1, 12, 3, 0, tzinfo=timezone.utc)
    payload = _window_payload(session_factory, since)
    assert payload["timestamp_range"]["last_detected"] == "2026-05-01T12:06:00.000Z"
    assert payload["dst_tbi"] == 5000 and payload["dst_tbo"] == 6000


def test_volatile_tuple_excludes_json_blobs():
    """_VOLATILE 的每一欄都會被包進 func.max()——JSON 文字做 MAX 是字典序
    比大小（會挑錯邊）。raw_json/report_json 必須走 CASE，不得列在這裡。"""
    from src.pce_cache.ingestor_traffic import TrafficIngestor

    assert "raw_json" not in TrafficIngestor._VOLATILE
    assert "report_json" not in TrafficIngestor._VOLATILE
