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
