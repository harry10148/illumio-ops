"""Tests for ReportGenerator cache-first traffic sourcing."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
import pytest


def _make_mock_api():
    api = MagicMock()
    api.fetch_traffic_for_report = MagicMock(return_value=[])
    return api


def _make_flow():
    return {
        "src": {"workload": {"href": "/orgs/1/workloads/w1"}},
        "dst": {"workload": {"href": "/orgs/1/workloads/w2"}},
        "service": {"port": 443, "proto": 6},
        "policy_decision": "allowed",
        "num_connections": 1,
    }


def _make_cache_reader(cover_state="full", flows=None, earliest=None):
    cr = MagicMock()
    cr.cover_state.return_value = cover_state
    cr.read_flows_raw.return_value = flows or [_make_flow()]
    cr.read_flows_agg.return_value = []
    cr.earliest_ingested_at.return_value = earliest
    cr.earliest_data_timestamp.return_value = earliest
    return cr


def test_report_generator_uses_cache_on_full_hit(tmp_path):
    """cover_state=full: reads from cache, does NOT call API traffic endpoint."""
    from src.report.report_generator import ReportGenerator
    api = _make_mock_api()
    cache = _make_cache_reader(cover_state="full")
    gen = ReportGenerator(api=api, cache_reader=cache)
    start = datetime.now(timezone.utc) - timedelta(days=1)
    end = datetime.now(timezone.utc)
    result = gen._fetch_traffic(start, end)
    assert result["source"] == "cache"
    cache.read_flows_raw.assert_called_once()
    api.fetch_traffic_for_report.assert_not_called()


def test_report_generator_bypasses_cache_when_none(tmp_path):
    """cache_reader=None: falls through to API."""
    from src.report.report_generator import ReportGenerator
    api = _make_mock_api()
    gen = ReportGenerator(api=api, cache_reader=None)
    start = datetime.now(timezone.utc) - timedelta(days=1)
    end = datetime.now(timezone.utc)
    result = gen._fetch_traffic(start, end)
    assert result["source"] == "api"
    api.fetch_traffic_for_report.assert_called_once()


def test_report_generator_falls_back_on_partial(tmp_path):
    """cover_state=partial with earliest=None (no fixable gap): falls back to API."""
    from src.report.report_generator import ReportGenerator
    api = _make_mock_api()
    cache = _make_cache_reader(cover_state="partial")
    gen = ReportGenerator(api=api, cache_reader=cache)
    start = datetime.now(timezone.utc) - timedelta(days=1)
    end = datetime.now(timezone.utc)
    result = gen._fetch_traffic(start, end)
    assert result["source"] == "api"
    api.fetch_traffic_for_report.assert_called_once()


def test_report_generator_falls_back_on_miss(tmp_path):
    """cover_state=miss: falls back to API."""
    from src.report.report_generator import ReportGenerator
    api = _make_mock_api()
    cache = _make_cache_reader(cover_state="miss")
    gen = ReportGenerator(api=api, cache_reader=cache)
    start = datetime.now(timezone.utc) - timedelta(days=1)
    end = datetime.now(timezone.utc)
    result = gen._fetch_traffic(start, end)
    assert result["source"] == "api"
    api.fetch_traffic_for_report.assert_called_once()


def test_report_generator_cache_hit_includes_agg(tmp_path):
    """On cache hit, result dict contains both raw and agg."""
    from src.report.report_generator import ReportGenerator
    api = _make_mock_api()
    cache = _make_cache_reader(cover_state="full")
    cache.read_flows_agg.return_value = [{"bucket_day": "2026-01-01", "flow_count": 5}]
    gen = ReportGenerator(api=api, cache_reader=cache)
    start = datetime.now(timezone.utc) - timedelta(days=1)
    end = datetime.now(timezone.utc)
    result = gen._fetch_traffic(start, end)
    assert result["agg"] is not None
    assert len(result["agg"]) == 1


def test_report_generator_hybrid_fetch_on_fresh_cache(tmp_path):
    """partial + cache_start > request start → hybrid: merge API gap + cache data."""
    from datetime import datetime, timedelta, timezone
    from src.report.report_generator import ReportGenerator

    now = datetime.now(timezone.utc)
    cache_start = now - timedelta(hours=2)   # cache only has last 2 hours
    request_start = now - timedelta(days=3)  # user wants 3 days

    api = _make_mock_api()
    api.fetch_traffic_for_report.return_value = [_make_flow()]  # API fills the gap
    cache = _make_cache_reader(
        cover_state="partial",
        flows=[_make_flow()],          # cache contributes 1 flow
        earliest=cache_start,
    )

    gen = ReportGenerator(api=api, cache_reader=cache)
    result = gen._fetch_traffic(request_start, now)

    assert result["source"] == "mixed"
    assert len(result["raw"]) == 2  # 1 from API gap + 1 from cache
    api.fetch_traffic_for_report.assert_called_once()
    cache.read_flows_raw.assert_called_once()


def test_report_generator_source_propagated_to_result(tmp_path):
    """generate_from_api propagates _fetch_traffic source into ReportResult.data_source."""
    from datetime import datetime, timedelta, timezone
    from src.report.report_generator import ReportGenerator

    now = datetime.now(timezone.utc)
    api = _make_mock_api()
    api.get_last_traffic_query_diagnostics = MagicMock(return_value={})
    cache = _make_cache_reader(cover_state="full", flows=[_make_flow()])

    gen = ReportGenerator(api=api, cache_reader=cache,
                          config_manager=MagicMock(config={"settings": {}}))
    result = gen.generate_from_api()

    assert result.data_source == "cache"


def test_fetch_traffic_partial_with_empty_api_gap_tags_as_cache(tmp_path):
    """When PCE returns zero rows for the gap, the result is effectively
    full cache — source must be 'cache', not 'mixed'."""
    from src.report.report_generator import ReportGenerator
    api = _make_mock_api()  # already returns []
    cache_start = datetime.now(timezone.utc) - timedelta(days=3)
    cache = _make_cache_reader(cover_state="partial", earliest=cache_start)
    gen = ReportGenerator(api=api, cache_reader=cache)
    start = datetime.now(timezone.utc) - timedelta(days=7)
    end = datetime.now(timezone.utc)
    result = gen._fetch_traffic(start, end)
    assert result["source"] == "cache"
    api.fetch_traffic_for_report.assert_called_once()
    cache.read_flows_raw.assert_called_once()


def test_report_generator_analysis_modules_receive_plain_list(tmp_path):
    """The 15 analysis modules still receive a plain list[dict] — not the dict wrapper."""
    from src.report.report_generator import ReportGenerator
    api = _make_mock_api()
    flows = [_make_flow(), _make_flow()]
    cache = _make_cache_reader(cover_state="full", flows=flows)
    gen = ReportGenerator(api=api, cache_reader=cache)
    start = datetime.now(timezone.utc) - timedelta(days=1)
    end = datetime.now(timezone.utc)
    result = gen._fetch_traffic(start, end)
    # The orchestrator unpacks result["raw"] for the analysis modules
    assert isinstance(result["raw"], list)
    assert len(result["raw"]) == 2


def test_generate_from_api_clip_to_cache_clips_start_to_cache_data(tmp_path):
    """clip_to_cache=True must clip the request start to earliest_data_timestamp,
    so the API call covers no leading gap and source ends up 'cache'."""
    from src.report.report_generator import ReportGenerator
    api = _make_mock_api()
    api.get_last_traffic_query_diagnostics = MagicMock(return_value={})
    cache_start = datetime.now(timezone.utc) - timedelta(days=3)
    cache = _make_cache_reader(cover_state="partial", earliest=cache_start)
    # Allow cover_state to look at the actual start passed in
    def _cover(source, s, e):
        return "full" if s >= cache_start else "partial"
    cache.cover_state.side_effect = _cover
    gen = ReportGenerator(api=api, cache_reader=cache,
                          config_manager=MagicMock(config={"settings": {}}))
    start = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat().replace("+00:00", "Z")
    end = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    result = gen.generate_from_api(start_date=start, end_date=end, clip_to_cache=True)
    # cover_state was forced to be re-evaluated against clipped start;
    # cache.cover_state should now be called with clipped start == cache_start
    args, _ = cache.cover_state.call_args
    clipped_start = args[1]
    assert clipped_start == cache_start
    api.fetch_traffic_for_report.assert_not_called()  # cover_state full → no API
    # When clip succeeds, fetch goes purely through cache
    assert result.data_source == "cache"


def test_generate_from_api_clip_to_cache_skips_clip_when_cache_after_end(tmp_path, caplog):
    """When cache_earliest > end_dt, clip must NOT push start past end.
    Leave the request range alone and let cover_state return 'miss' naturally."""
    import logging
    from src.report.report_generator import ReportGenerator
    api = _make_mock_api()
    api.get_last_traffic_query_diagnostics = MagicMock(return_value={})
    # Cache holds data AFTER the request window
    cache_start = datetime.now(timezone.utc) + timedelta(days=1)
    cache = _make_cache_reader(cover_state="miss", earliest=cache_start)
    gen = ReportGenerator(api=api, cache_reader=cache,
                          config_manager=MagicMock(config={"settings": {}}))
    start = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat().replace("+00:00", "Z")
    end = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat().replace("+00:00", "Z")
    with caplog.at_level(logging.INFO, logger="src.report.report_generator"):
        gen.generate_from_api(start_date=start, end_date=end, clip_to_cache=True)
    # Diagnostic log must mention skipping clip
    assert any("skipping clip" in rec.message for rec in caplog.records), \
        f"expected skipping-clip log; got: {[r.message for r in caplog.records]}"
    # cover_state must have been called with the ORIGINAL (unclipped) start
    args_start = cache.cover_state.call_args[0][1]
    expected_start = datetime.fromisoformat(start.replace("Z", "+00:00"))
    assert abs((args_start - expected_start).total_seconds()) < 1


def test_generate_from_api_clip_to_cache_default_off_does_not_clip(tmp_path):
    """clip_to_cache defaults False — request range is NOT mutated, hybrid
    fetch still runs as before."""
    from src.report.report_generator import ReportGenerator
    api = _make_mock_api()
    api.get_last_traffic_query_diagnostics = MagicMock(return_value={})
    cache_start = datetime.now(timezone.utc) - timedelta(days=3)
    cache = _make_cache_reader(cover_state="partial", earliest=cache_start)
    gen = ReportGenerator(api=api, cache_reader=cache,
                          config_manager=MagicMock(config={"settings": {}}))
    start = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat().replace("+00:00", "Z")
    end = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    gen.generate_from_api(start_date=start, end_date=end)
    # Default behavior: API call is made for the leading gap
    api.fetch_traffic_for_report.assert_called_once()


def test_fetch_traffic_hybrid_boundary_flow_counted_exactly_once(tmp_path):
    """資料層行為鎖（Task F3，C6 同型 follow-up）：last_detected 恰好等於
    cache_start 的 flow，在合併結果中必須恰好出現一次。

    兩個 mock 資料來源皆忠實模擬「兩端皆含端點」的查詢語意：
    - PCE traffic API 的 start_date/end_date 在秒解析度下為 inclusive
      （report_generator._fetch_traffic 與 analyzer._fetch_query_flows
      走同一個 execute_traffic_query_stream → start_date/end_date payload，
      見 src/api/traffic_query.py _build_native_traffic_payload）。
    - cache.read_flows_raw 依 last_detected >= start AND <= end 過濾
      （見 src/pce_cache/reader.py）。
    修正前 API gap 以 cache_start 結束、cache 亦含 cache_start 端點，
    合併後邊界 flow 出現兩次；修正後 gap 結束於 cache_start 前 1 秒，
    只有 cache 側回傳它 → 一次。
    """
    from datetime import datetime, timedelta, timezone
    from src.report.report_generator import ReportGenerator

    # 秒解析度截斷：_fmt_iso 直接輸出 datetime.isoformat()，若帶微秒會與
    # PCE API 的 '%Y-%m-%dT%H:%M:%SZ' 字串格式對不上（見 C6 對 analyzer 的
    # 同一假設）。
    now = datetime.now(timezone.utc).replace(microsecond=0)
    cache_start = now - timedelta(hours=2)
    request_start = now - timedelta(days=3)

    def _parse(ts):
        return datetime.strptime(ts, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)

    boundary_flow = {**_make_flow(), "id": "boundary",
                     "last_detected": cache_start.strftime('%Y-%m-%dT%H:%M:%SZ')}
    gap_only_flow = {**_make_flow(), "id": "gap-only",
                     "last_detected": (cache_start - timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ')}
    all_flows = [gap_only_flow, boundary_flow]

    api = _make_mock_api()

    def _api_fetch(start_time_str, end_time_str, filters=None):
        # 模擬 PCE traffic API：回傳 [start, end] 兩端皆含端點的 flow
        s, e = _parse(start_time_str), _parse(end_time_str)
        return [f for f in all_flows if s <= _parse(f["last_detected"]) <= e]
    api.fetch_traffic_for_report.side_effect = _api_fetch

    cache = _make_cache_reader(cover_state="partial", earliest=cache_start)

    def _cache_read(start, end, workload_hrefs=None):
        # 模擬 read_flows_raw：last_detected >= start AND <= end（皆含端點）
        return [f for f in all_flows if start <= _parse(f["last_detected"]) <= end]
    cache.read_flows_raw.side_effect = _cache_read

    gen = ReportGenerator(api=api, cache_reader=cache)
    result = gen._fetch_traffic(request_start, now)

    ids = [f["id"] for f in result["raw"]]
    assert ids.count("boundary") == 1  # 端點 flow 恰好一次
    assert ids.count("gap-only") == 1  # gap 段 flow 不受影響
    assert result["source"] == "mixed"


def test_fetch_traffic_df_hybrid_boundary_flow_counted_exactly_once(tmp_path):
    """資料層行為鎖（Task F3）：_fetch_traffic_df 走與 _fetch_traffic 相同的
    切分點，同樣需要邊界 flow 恰好計一次。見上一測試的語意說明。

    僅在合併層驗證（gap 側與 cache 側各自回傳的 DataFrame 直接拼接），
    不經過完整的 APIParser/build_unified_df 流程 —— 與 C6 對 analyzer
    的資料層測試手法一致：鎖的是切分點的算術，不是解析管線。
    """
    from datetime import datetime, timedelta, timezone
    from unittest.mock import MagicMock
    import pandas as pd
    from src.report.report_generator import ReportGenerator

    # 秒解析度截斷：理由同上一測試（_fmt_iso 直接輸出帶微秒的 isoformat()）。
    now = datetime.now(timezone.utc).replace(microsecond=0)
    cache_start = now - timedelta(hours=2)
    request_start = now - timedelta(days=3)

    boundary_row = {"id": "boundary", "last_detected": cache_start}
    gap_row = {"id": "gap-only", "last_detected": cache_start - timedelta(hours=1)}
    all_rows = [gap_row, boundary_row]

    api = _make_mock_api()

    def _api_fetch(start_time_str, end_time_str, filters=None, compute_draft=False):
        s = datetime.strptime(start_time_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
        e = datetime.strptime(end_time_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
        return [r for r in all_rows if s <= r["last_detected"] <= e]
    api.fetch_traffic_for_report.side_effect = _api_fetch

    cache = _make_cache_reader(cover_state="partial", earliest=cache_start)

    def _cache_read_df(start, end, workload_hrefs=None, policy_decisions=None):
        rows = [r for r in all_rows if start <= r["last_detected"] <= end]
        return pd.DataFrame(rows) if rows else pd.DataFrame(columns=["id", "last_detected"])
    cache.read_flows_df.side_effect = _cache_read_df

    gen = ReportGenerator(api=api, cache_reader=cache)
    # 資料層鎖：以簡單直通取代完整 APIParser 解析，只驗證切分點算術。
    gen._parse_api = lambda records: (
        pd.DataFrame(records) if records else pd.DataFrame(columns=["id", "last_detected"])
    )

    df, source = gen._fetch_traffic_df(request_start, now, None)

    ids = df["id"].tolist()
    assert ids.count("boundary") == 1  # 端點 flow 恰好一次
    assert ids.count("gap-only") == 1  # gap 段 flow 不受影響
    assert source == "mixed"
