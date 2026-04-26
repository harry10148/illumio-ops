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
