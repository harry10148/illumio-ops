"""Prove Analyzer decoupling by testing with minimal Protocol implementations."""
import pytest
from src.analyzer import Analyzer
from src.interfaces import IApiClient, IReporter


class _StubApiClient:
    """Minimal IApiClient — only the methods Analyzer.run_analysis() calls."""
    def check_health(self):
        return 200, "ok"
    def update_label_cache(self, silent=False, force_refresh=True):
        pass
    def fetch_traffic_for_report(self, *a, **kw):
        return []
    def get_all_rulesets(self, force_refresh=False):
        return []
    def get_active_rulesets(self):
        return []
    def fetch_events(self, *a, **kw):
        return []
    def resolve_actor_str(self, *a, **kw):
        return []


class _StubReporter:
    """Minimal IReporter."""
    def __init__(self):
        self.sent = []
    def send_alerts(self, alert_list, resolved_list):
        self.sent.append((alert_list, resolved_list))


def _make_analyzer():
    """Build an Analyzer with stub doubles and a minimal config."""
    import json, os, tempfile
    cfg = {
        "api": {"url": "https://pce.example.com:8443", "org_id": 1, "key": "k", "secret": "s"},
        "analysis": {"traffic_hours": 24, "exclude_broadcast": True, "alert_threshold": 1},
        "rules": [],
        "events": {"enabled": False, "fetch_minutes": 5, "rules": []},
    }
    tmpdir = tempfile.mkdtemp()
    cfg_path = os.path.join(tmpdir, "config.json")
    with open(cfg_path, "w") as f:
        json.dump(cfg, f)

    from src.config import ConfigManager
    cm = ConfigManager(config_file=cfg_path)
    api = _StubApiClient()
    rep = _StubReporter()
    return Analyzer(cm, api, rep), api, rep


def test_stub_api_client_satisfies_protocol():
    """_StubApiClient structurally satisfies IApiClient (runtime_checkable not required)."""
    from typing import get_type_hints
    stub = _StubApiClient()
    for method in ("check_health", "update_label_cache", "fetch_traffic_for_report",
                   "get_all_rulesets", "get_active_rulesets", "fetch_events", "resolve_actor_str"):
        assert callable(getattr(stub, method, None)), f"Missing: {method}"


def test_stub_reporter_satisfies_protocol():
    stub = _StubReporter()
    assert callable(getattr(stub, "send_alerts", None))


def test_analyzer_accepts_protocol_stubs():
    """Analyzer.__init__ accepts protocol-conforming stubs without errors."""
    analyzer, _, _ = _make_analyzer()
    assert analyzer is not None


def test_analyzer_run_analysis_uses_stub_api(monkeypatch):
    """run_analysis() completes with stub doubles — no real network."""
    import datetime
    analyzer, api, rep = _make_analyzer()
    # Patch time-related side effects — signatures must match actual call sites in run_analysis()
    # _fetch_traffic() → (traffic_stream, tr_rules, now_utc)
    monkeypatch.setattr(analyzer, "_fetch_traffic", lambda: (None, [], datetime.datetime.now(datetime.timezone.utc)))
    # _run_event_analysis() → list
    monkeypatch.setattr(analyzer, "_run_event_analysis", lambda: [])
    # _run_rule_engine(traffic_stream, tr_rules, now_utc) → list of (rule, result) pairs
    monkeypatch.setattr(analyzer, "_run_rule_engine", lambda stream, rules, now: [])
    # _run_health_check() → bool
    monkeypatch.setattr(analyzer, "_run_health_check", lambda: True)
    # _dispatch_alerts(triggers, tr_rules) → None
    monkeypatch.setattr(analyzer, "_dispatch_alerts", lambda triggered, tr_rules: None)
    result = analyzer.run_analysis()
    # run_analysis returns None or a summary dict — just confirm no exception
    assert result is None or isinstance(result, dict)
