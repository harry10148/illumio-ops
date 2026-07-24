"""Tests for BackfillRunner — bypasses watermark, inserts by date range."""
from datetime import datetime, timedelta, timezone
import json
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import PceEvent, PceTrafficFlowRaw


@pytest.fixture
def session_factory(tmp_path):
    from src.pce_cache.schema import init_schema
    engine = create_engine(f"sqlite:///{tmp_path / 'bf.sqlite'}")
    init_schema(engine)
    return sessionmaker(engine)


def _make_mock_api_events(events):
    from unittest.mock import MagicMock
    api = MagicMock()
    # run_events 現走 fetch_events（帶明確 end_time_str + 大 max_results，
    # 取代舊的 get_events 預設 500 上限、無 until 的截斷路徑）。
    api.fetch_events.return_value = events
    return api


def _make_mock_api_traffic(flows):
    from unittest.mock import MagicMock
    api = MagicMock()
    api.fetch_traffic_for_report.return_value = flows
    return api


def _event(n):
    ts = (datetime.now(timezone.utc) - timedelta(days=n)).isoformat()
    return {
        "href": f"/orgs/1/events/e{n}",
        "event_type": "policy.update",
        "severity": "info",
        "status": "success",
        "pce_fqdn": "pce.example.com",
        "timestamp": ts,
        "notifications": [{"notification_type": "policy.update"}],
    }


def _flow(n):
    # Use a fixed timestamp to ensure two _flow(n) calls produce identical hashes
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc) - timedelta(days=n)
    ts_str = ts.isoformat()
    return {
        "src": {"workload": {"href": f"/orgs/1/workloads/src{n}"}},
        "dst": {"workload": {"href": f"/orgs/1/workloads/dst{n}"}},
        "service": {"port": 443, "proto": 6},
        "policy_decision": "allowed",
        "first_detected": ts_str,
        "last_detected": ts_str,
        "num_connections": 1,
        "flow_direction": "outbound",
    }


def test_backfill_events_inserts_rows(session_factory, tmp_path):
    from src.pce_cache.backfill import BackfillRunner
    events = [_event(5), _event(4), _event(3)]
    api = _make_mock_api_events(events)
    now = datetime.now(timezone.utc)
    runner = BackfillRunner(api, session_factory, rate_limit_per_minute=400)
    result = runner.run_events(now - timedelta(days=7), now)
    assert result.inserted == 3
    with session_factory() as s:
        count = s.execute(select(PceEvent)).scalars().all()
    assert len(count) == 3


def test_backfill_events_deduplicates(session_factory, tmp_path):
    from src.pce_cache.backfill import BackfillRunner
    events = [_event(5), _event(5)]  # duplicate
    api = _make_mock_api_events(events)
    now = datetime.now(timezone.utc)
    runner = BackfillRunner(api, session_factory, rate_limit_per_minute=400)
    result = runner.run_events(now - timedelta(days=7), now)
    assert result.inserted + result.duplicates == 2
    with session_factory() as s:
        count = s.execute(select(PceEvent)).scalars().all()
    assert len(count) == 1


def test_backfill_events_does_not_advance_watermark(session_factory, tmp_path):
    from src.pce_cache.backfill import BackfillRunner
    from src.pce_cache.watermark import WatermarkStore
    events = [_event(5)]
    api = _make_mock_api_events(events)
    now = datetime.now(timezone.utc)
    runner = BackfillRunner(api, session_factory, rate_limit_per_minute=400)
    runner.run_events(now - timedelta(days=7), now)
    wm = WatermarkStore(session_factory)
    # Watermark for "events" must remain unset (None)
    assert wm.get("events") is None


def test_backfill_traffic_inserts_rows(session_factory, tmp_path):
    from src.pce_cache.backfill import BackfillRunner
    flows = [_flow(5), _flow(4)]
    api = _make_mock_api_traffic(flows)
    now = datetime.now(timezone.utc)
    runner = BackfillRunner(api, session_factory, rate_limit_per_minute=400)
    result = runner.run_traffic(now - timedelta(days=7), now)
    assert result.inserted == 2
    with session_factory() as s:
        count = s.execute(select(PceTrafficFlowRaw)).scalars().all()
    assert len(count) == 2


def test_backfill_result_has_correct_fields(session_factory, tmp_path):
    from src.pce_cache.backfill import BackfillRunner, BackfillResult
    events = [_event(3)]
    api = _make_mock_api_events(events)
    now = datetime.now(timezone.utc)
    runner = BackfillRunner(api, session_factory, rate_limit_per_minute=400)
    result = runner.run_events(now - timedelta(days=7), now)
    assert isinstance(result, BackfillResult)
    assert hasattr(result, "total_rows")
    assert hasattr(result, "inserted")
    assert hasattr(result, "duplicates")
    assert hasattr(result, "elapsed_seconds")
    assert result.total_rows >= result.inserted


def test_backfill_traffic_deduplicates(session_factory, tmp_path):
    from src.pce_cache.backfill import BackfillRunner
    flows = [_flow(5), _flow(5)]  # duplicate (same hash)
    api = _make_mock_api_traffic(flows)
    now = datetime.now(timezone.utc)
    runner = BackfillRunner(api, session_factory, rate_limit_per_minute=400)
    result = runner.run_traffic(now - timedelta(days=7), now)
    assert result.inserted + result.duplicates == 2
    with session_factory() as s:
        count = s.execute(select(PceTrafficFlowRaw)).scalars().all()
    assert len(count) == 1


def test_backfill_traffic_populates_report_json(session_factory, tmp_path):
    """Backfilled raw flows must carry the precomputed report_json like the live
    ingestor, so reports hit the fast path (and the ix_raw_report_json_null
    partial-index invariant in schema.py holds)."""
    import orjson
    from src.pce_cache.backfill import BackfillRunner
    flows = [_flow(5)]
    api = _make_mock_api_traffic(flows)
    now = datetime.now(timezone.utc)
    runner = BackfillRunner(api, session_factory, rate_limit_per_minute=400)
    runner.run_traffic(now - timedelta(days=7), now)
    with session_factory() as s:
        row = s.execute(select(PceTrafficFlowRaw)).scalars().one()
    assert row.report_json is not None
    parsed = orjson.loads(row.report_json)
    assert isinstance(parsed, dict) and parsed  # non-empty flatten dict


def test_backfill_empty_api_returns_zero(session_factory, tmp_path):
    from src.pce_cache.backfill import BackfillRunner
    api = _make_mock_api_events([])
    now = datetime.now(timezone.utc)
    runner = BackfillRunner(api, session_factory, rate_limit_per_minute=400)
    result = runner.run_events(now - timedelta(days=7), now)
    assert result.inserted == 0
    assert result.total_rows == 0


def test_backfill_events_passes_until_and_large_max_results(session_factory):
    """run_events 必須把 until 傳到 API（end_time_str）並帶大 max_results，
    否則視窗被靜默截斷在預設 500 筆且抓到的事件可能落在視窗外（2026-07-25 審查）。"""
    from src.pce_cache.backfill import BackfillRunner
    api = _make_mock_api_events([_event(3)])
    now = datetime.now(timezone.utc)
    since, until = now - timedelta(days=7), now - timedelta(days=1)
    BackfillRunner(api, session_factory).run_events(since, until)
    assert api.fetch_events.call_count == 1
    args, kwargs = api.fetch_events.call_args
    assert args[0] == since.isoformat().replace("+00:00", "Z")
    assert kwargs["end_time_str"] == until.isoformat().replace("+00:00", "Z")
    assert kwargs["max_results"] >= 10000
    assert kwargs["rate_limit"] is True


def test_backfill_events_bisects_on_cap_hit(session_factory):
    """單一請求碰頂（len == max_results）時要對半二分抽乾整個視窗，
    而非把截斷結果當完整資料收下。"""
    from src.pce_cache.backfill import BackfillRunner
    runner = BackfillRunner(_make_mock_api_events([]), session_factory)
    runner._EVENTS_MAX = 2  # 便於觸發 cap
    calls = []

    def fake_fetch(start, end_time_str=None, max_results=None, rate_limit=False):
        calls.append((start, end_time_str))
        if len(calls) == 1:
            return [_event(1), _event(2)]  # 碰頂 → 觸發 bisect
        return [_event(len(calls))]

    runner._api.fetch_events.side_effect = fake_fetch
    now = datetime.now(timezone.utc)
    runner.run_events(now - timedelta(days=2), now)
    assert len(calls) == 3  # 原窗 + 左右兩半


def test_backfill_events_raises_on_swallowed_fetch_error(session_factory):
    """fetch 層把連線失敗吞成 [] 只寫 last_fetch_error 時，backfill 必須拋錯
    （fail-closed），不可回報成功的 0 筆 backfill。"""
    from src.pce_cache.backfill import BackfillRunner
    api = _make_mock_api_events([])
    api.last_fetch_error = "Connection refused"
    with pytest.raises(RuntimeError, match="Connection refused"):
        BackfillRunner(api, session_factory).run_events(
            datetime.now(timezone.utc) - timedelta(days=1), datetime.now(timezone.utc))


def test_backfill_traffic_raises_on_swallowed_fetch_error(session_factory):
    from src.pce_cache.backfill import BackfillRunner
    api = _make_mock_api_traffic([])
    api.last_fetch_error = "async submit 503"
    with pytest.raises(RuntimeError, match="async submit 503"):
        BackfillRunner(api, session_factory).run_traffic(
            datetime.now(timezone.utc) - timedelta(days=1), datetime.now(timezone.utc))


def test_backfill_event_with_explicit_null_status_is_inserted(session_factory):
    """真實 PCE 事件會帶 "status": null——必須被 coerce 成 'success' 寫入，
    而非撞 NOT NULL 被靜默丟棄還誤計成 duplicate（與 ingestor_events 同修）。"""
    from src.pce_cache.backfill import BackfillRunner
    ev = _event(2)
    ev["status"] = None
    api = _make_mock_api_events([ev])
    now = datetime.now(timezone.utc)
    result = BackfillRunner(api, session_factory).run_events(now - timedelta(days=7), now)
    assert result.inserted == 1 and result.duplicates == 0
    with session_factory() as s:
        row = s.execute(select(PceEvent)).scalars().one()
    assert row.status == "success"


def test_backfill_traffic_passes_rate_limit(session_factory):
    """backfill 的 PCE 呼叫必須走全域限速器（rate_limit=True），不可在營運
    時段與 live ingest 並行時完全不節流。"""
    from src.pce_cache.backfill import BackfillRunner
    api = _make_mock_api_traffic([])
    now = datetime.now(timezone.utc)
    BackfillRunner(api, session_factory).run_traffic(now - timedelta(days=1), now)
    _, kwargs = api.fetch_traffic_for_report.call_args
    assert kwargs["rate_limit"] is True


def test_live_and_backfill_flow_hash_agree_on_nested_rows(session_factory):
    """live ingest 與 backfill 對同一筆巢狀 PCE row 必須算出同一個 flow_hash
    （含 src.ip/dst.ip fallback），否則跨路徑去重失效、重疊視窗會塞重複列。"""
    from src.pce_cache.ingestor_traffic import _flow_hash
    from src.pce_cache.backfill import _backfill_flow_hash
    nested = {
        "src": {"ip": "203.0.113.7"},
        "dst": {"ip": "10.0.0.9", "workload": {"href": "/orgs/1/workloads/w1"}},
        "service": {"port": 443, "proto": 6},
        "policy_decision": "allowed",
        "timestamp_range": {"first_detected": "2026-07-01T00:00:00Z",
                            "last_detected": "2026-07-01T00:05:00Z"},
    }
    assert _flow_hash(nested) == _backfill_flow_hash(nested)
    # 巢狀 IP 必須真的參與 hash：不同 src.ip 要得到不同 hash
    other = {**nested, "src": {"ip": "203.0.113.8"}}
    assert _flow_hash(nested) != _flow_hash(other)
