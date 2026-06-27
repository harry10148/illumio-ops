"""A.1 — draft-policy report fetch gate.

The draft engine (R01-R05), flatten, unified-df and exporters are already wired
and tested (see test_draft_pd_engine_wiring.py). These tests cover only the
*fetch gate*: a draft-policy report must (a) request compute_draft from the PCE
and (b) bypass the cache (which has no draft_policy_decision column), while a
normal report pays neither cost.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd

from src.api.traffic_query import TrafficQueryBuilder
from src.report.report_generator import ReportGenerator


# ── Layer 0: ApiClient delegates compute_draft to the builder ─────────────────
# Regression guard: the report path calls ApiClient.fetch_traffic_for_report
# (a thin wrapper over TrafficQueryBuilder), not the builder directly. Mocked-api
# unit tests can't catch a missing kwarg on the real wrapper.

def test_api_client_fetch_traffic_for_report_forwards_compute_draft():
    from src.api_client import ApiClient
    api = ApiClient.__new__(ApiClient)  # bypass __init__ (no PCE config needed)
    api._traffic = MagicMock()
    api._traffic.fetch_traffic_for_report.return_value = []
    api.fetch_traffic_for_report("2026-06-01T00:00:00Z", "2026-06-02T00:00:00Z",
                                 compute_draft=True)
    assert api._traffic.fetch_traffic_for_report.call_args.kwargs.get("compute_draft") is True


def test_api_client_fetch_traffic_for_report_defaults_compute_draft_false():
    from src.api_client import ApiClient
    api = ApiClient.__new__(ApiClient)
    api._traffic = MagicMock()
    api._traffic.fetch_traffic_for_report.return_value = []
    api.fetch_traffic_for_report("2026-06-01T00:00:00Z", "2026-06-02T00:00:00Z")
    assert api._traffic.fetch_traffic_for_report.call_args.kwargs.get("compute_draft") is False


# ── Layer 1: TrafficQueryBuilder.fetch_traffic_for_report threads compute_draft ─

def test_fetch_traffic_for_report_threads_compute_draft():
    client = MagicMock()
    client.last_traffic_query_diagnostics = {}
    builder = TrafficQueryBuilder(client)
    spec = MagicMock()
    spec.fallback_filters = None
    with patch.object(builder, "build_traffic_query_spec", return_value=spec), \
         patch.object(builder, "execute_traffic_query_stream", return_value=iter([])) as mock_stream:
        builder.fetch_traffic_for_report(
            "2026-06-01T00:00:00Z", "2026-06-02T00:00:00Z", compute_draft=True)
    assert mock_stream.call_args.kwargs.get("compute_draft") is True


def test_fetch_traffic_for_report_defaults_compute_draft_false():
    client = MagicMock()
    client.last_traffic_query_diagnostics = {}
    builder = TrafficQueryBuilder(client)
    spec = MagicMock()
    spec.fallback_filters = None
    with patch.object(builder, "build_traffic_query_spec", return_value=spec), \
         patch.object(builder, "execute_traffic_query_stream", return_value=iter([])) as mock_stream:
        builder.fetch_traffic_for_report(
            "2026-06-01T00:00:00Z", "2026-06-02T00:00:00Z")
    assert mock_stream.call_args.kwargs.get("compute_draft") is False


# ── Layer 2: ReportGenerator threads compute_draft + gates cache on draft_policy ─

import datetime

_S = datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc)
_E = datetime.datetime(2026, 6, 2, tzinfo=datetime.timezone.utc)


def test_fetch_traffic_df_threads_compute_draft_to_api():
    gen = ReportGenerator(MagicMock(), api_client=MagicMock())
    gen.api.fetch_traffic_for_report.return_value = []
    gen._cache = None  # force the live-api path
    gen._fetch_traffic_df(_S, _E, {}, use_cache=False, compute_draft=True)
    assert gen.api.fetch_traffic_for_report.call_args.kwargs.get("compute_draft") is True


def test_generate_from_api_draft_policy_forces_live_compute_draft():
    gen = ReportGenerator(MagicMock(), api_client=MagicMock())
    with patch.object(gen, "_fetch_traffic_df", return_value=(pd.DataFrame(), "api")) as mock_fetch:
        gen.generate_from_api(start_date="2026-06-01T00:00:00Z",
                              end_date="2026-06-02T00:00:00Z", draft_policy=True)
    kw = mock_fetch.call_args.kwargs
    assert kw.get("use_cache") is False, "draft report must bypass the (draft-less) cache"
    assert kw.get("compute_draft") is True


def test_generate_from_api_default_pays_no_draft_cost():
    gen = ReportGenerator(MagicMock(), api_client=MagicMock())
    with patch.object(gen, "_fetch_traffic_df", return_value=(pd.DataFrame(), "api")) as mock_fetch:
        gen.generate_from_api(start_date="2026-06-01T00:00:00Z",
                              end_date="2026-06-02T00:00:00Z")
    kw = mock_fetch.call_args.kwargs
    assert kw.get("compute_draft") in (False, None), "normal report must not request draft"
    assert kw.get("use_cache") is True, "normal report keeps using the cache"


# ── Layer 3: CLI surfaces (click subcommand + legacy --report-type) ────────────

import sys
import types

import pytest
from click.testing import CliRunner


def _capture_draft_policy(args):
    captured = {}

    def fake_generate_from_api(self, *a, **k):
        captured["draft_policy"] = k.get("draft_policy")
        raise SystemExit(0)

    from src.cli.root import cli
    with patch("src.report.report_generator.ReportGenerator.generate_from_api",
               fake_generate_from_api), \
         patch("src.report.cache_support.cache_available", return_value=True):
        CliRunner().invoke(cli, args, catch_exceptions=True)
    return captured


def test_cli_report_draft_policy_subcommand_requests_draft():
    assert _capture_draft_policy(["report", "draft-policy"]).get("draft_policy") is True


def test_cli_report_traffic_does_not_request_draft():
    assert _capture_draft_policy(["report", "traffic"]).get("draft_policy") in (False, None)


def test_cli_report_draft_policy_passes_date_window():
    captured = {}

    def fake_generate_from_api(self, *a, **k):
        captured.update(start_date=k.get("start_date"), end_date=k.get("end_date"),
                        draft_policy=k.get("draft_policy"))
        raise SystemExit(0)

    from src.cli.root import cli
    with patch("src.report.report_generator.ReportGenerator.generate_from_api",
               fake_generate_from_api), \
         patch("src.report.cache_support.cache_available", return_value=True):
        CliRunner().invoke(
            cli,
            ["report", "draft-policy", "--start-date", "2026-06-26", "--end-date", "2026-06-27"],
            catch_exceptions=True,
        )
    assert captured.get("start_date") == "2026-06-26"
    assert captured.get("end_date") == "2026-06-27"
    assert captured.get("draft_policy") is True


def test_legacy_report_type_draft_policy_dispatches(monkeypatch):
    import src.main as main_module

    called = {}

    class _FakeConfigManager:
        def __init__(self):
            self.config = {"logging": {}, "report": {}}

    class _FakeModuleLog:
        @staticmethod
        def init(*_a, **_k):
            return None

    def _fake_traffic_report(**kwargs):
        called["kwargs"] = kwargs
        return ["/tmp/draft.html"]

    monkeypatch.setattr(main_module, "setup_logger", lambda *a, **kw: None)
    monkeypatch.setattr(main_module, "ConfigManager", _FakeConfigManager)
    monkeypatch.setitem(sys.modules, "pandas", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "src.module_log",
                        types.SimpleNamespace(ModuleLog=_FakeModuleLog))
    monkeypatch.setattr("src.cli.report.generate_traffic_report", _fake_traffic_report)
    monkeypatch.setattr(sys, "argv",
                        ["illumio_ops.py", "--report", "--report-type", "draft_policy"])

    with pytest.raises(SystemExit) as exc:
        main_module.main()

    assert exc.value.code == 0
    assert called["kwargs"].get("draft_policy") is True
