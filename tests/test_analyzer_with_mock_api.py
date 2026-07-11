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
        "api": {"url": "https://pce.example.com:8443", "org_id": "1", "key": "k", "secret": "s"},
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


class _CapturedQuerySpec:
    """最小 TrafficQuerySpec 替身——query_flows 只讀 report_only_filters。"""
    report_only_filters: dict = {}
    requires_draft_pd = False


class _ObjectFilterCapturingApiClient(_StubApiClient):
    """在真實 query_flows -> build_traffic_query_spec 呼叫鏈上，
    捕捉實際傳入 build_traffic_query_spec 的 filters dict，
    以證明 object filter key 有從 query_flows 的 whitelist 傳遞出去
    （而非像舊測試那樣直接 monkeypatch 掉 query_flows 本身）。"""
    def __init__(self):
        self.captured_filters = None

    def build_traffic_query_spec(self, filters=None):
        self.captured_filters = dict(filters or {})
        return _CapturedQuerySpec()

    def execute_traffic_query_stream(self, start_time, end_time, query_pds, filters=None, compute_draft=False):
        return []


def test_query_flows_forwards_object_filter_keys_to_query_spec_builder():
    """query_flows 的 query_filters whitelist 必須轉發 actions.py 送來的
    18 個物件 filter key（複數 labels/iplists/workloads 與 any_*），
    否則它們會在 query_flows 這一關被靜默丟棄，永遠到不了
    build_traffic_query_spec / _flow_matches_filters。"""
    from src.config import ConfigManager
    import json, os, tempfile
    cfg = {
        "api": {"url": "https://pce.example.com:8443", "org_id": "1", "key": "k", "secret": "s"},
        "analysis": {"traffic_hours": 24, "exclude_broadcast": True, "alert_threshold": 1},
        "rules": [],
        "events": {"enabled": False, "fetch_minutes": 5, "rules": []},
    }
    tmpdir = tempfile.mkdtemp()
    cfg_path = os.path.join(tmpdir, "config.json")
    with open(cfg_path, "w") as f:
        json.dump(cfg, f)
    cm = ConfigManager(config_file=cfg_path)
    api = _ObjectFilterCapturingApiClient()
    rep = _StubReporter()
    analyzer = Analyzer(cm, api, rep)

    params = {
        "start_time": "2026-02-23T00:00:00Z",
        "end_time": "2026-02-23T23:59:59Z",
        "policy_decisions": ["blocked", "allowed"],
        "src_labels": ["app=erp", "app=web"],
        "dst_labels": ["app=db"],
        "ex_src_labels": ["env=test"],
        "ex_dst_labels": ["env=dev"],
        "src_iplist": "/orgs/1/sec_policy/active/ip_lists/1",
        "src_iplists": ["/orgs/1/sec_policy/active/ip_lists/7"],
        "dst_iplist": "/orgs/1/sec_policy/active/ip_lists/2",
        "dst_iplists": ["/orgs/1/sec_policy/active/ip_lists/8"],
        "ex_src_iplists": ["/orgs/1/sec_policy/active/ip_lists/9"],
        "ex_dst_iplists": ["/orgs/1/sec_policy/active/ip_lists/10"],
        "src_workloads": ["/orgs/1/workloads/aaa"],
        "dst_workloads": ["/orgs/1/workloads/bbb"],
        "ex_src_workloads": ["/orgs/1/workloads/ccc"],
        "ex_dst_workloads": ["/orgs/1/workloads/ddd"],
        "any_iplist": "/orgs/1/sec_policy/active/ip_lists/3",
        "any_workload": "/orgs/1/workloads/abc",
        "ex_any_iplist": "/orgs/1/sec_policy/active/ip_lists/4",
        "ex_any_workload": "/orgs/1/workloads/exc",
    }
    result = analyzer.query_flows(params)

    assert result == []
    assert api.captured_filters is not None, "build_traffic_query_spec was never called"
    expected = {k: v for k, v in params.items() if k not in ("start_time", "end_time", "policy_decisions")}
    for key, value in expected.items():
        assert api.captured_filters.get(key) == value, (
            f"query_flows dropped object filter key {key!r} before reaching build_traffic_query_spec"
        )


def test_analyzer_run_analysis_uses_stub_api(monkeypatch, tmp_path):
    """run_analysis() completes with stub doubles — no real network."""
    import datetime
    # Isolate persistent state BEFORE construction — Analyzer loads
    # src.analyzer.STATE_FILE (the repo's logs/state.json, which other tests
    # in a full-suite run write to) into self.state in __init__. A leaked
    # state with pce_stats.consecutive_failures >= 3 fires the watchdog,
    # whose reporter call _StubReporter does not implement.
    monkeypatch.setattr("src.analyzer.STATE_FILE", str(tmp_path / "state.json"))
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
