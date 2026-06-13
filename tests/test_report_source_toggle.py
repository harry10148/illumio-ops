"""Report data-source toggle: use_cache=False bypasses the cache reader entirely."""
from __future__ import annotations

import datetime
from unittest.mock import MagicMock

from src.report.report_generator import ReportGenerator

_START = datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc)
_END = datetime.datetime(2026, 6, 8, tzinfo=datetime.timezone.utc)


def _gen():
    api = MagicMock()
    api.fetch_traffic_for_report.return_value = [{"flow": 1}]
    cache = MagicMock()
    gen = ReportGenerator(config_manager=MagicMock(), api_client=api, cache_reader=cache)
    return gen, api, cache


def test_use_cache_false_goes_pure_api_and_never_touches_cache():
    gen, api, cache = _gen()
    res = gen._fetch_traffic(_START, _END, None, use_cache=False)
    assert res["source"] == "api"
    cache.cover_state.assert_not_called()
    cache.read_flows_raw.assert_not_called()
    api.fetch_traffic_for_report.assert_called_once()


def test_use_cache_true_consults_cache():
    gen, api, cache = _gen()
    cache.cover_state.return_value = "full"
    cache.read_flows_raw.return_value = [{"flow": 9}]
    cache.read_flows_agg.return_value = []
    res = gen._fetch_traffic(_START, _END, None, use_cache=True)
    assert res["source"] == "cache"
    cache.cover_state.assert_called_once()
    api.fetch_traffic_for_report.assert_not_called()
