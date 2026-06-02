"""mod16 (open-ports attack surface) report integration — opt-in, default OFF."""
from __future__ import annotations

import types

from src.report.report_generator import _compute_open_ports_surface


class _FakeApi:
    def __init__(self):
        self.get_calls = 0

    def fetch_managed_workloads(self):
        return [
            {"href": "/orgs/1/workloads/a", "hostname": "host-a"},
            {"href": "/orgs/1/workloads/b", "hostname": "host-b"},
        ]

    def get_workload(self, href):
        self.get_calls += 1
        return {"services": {"open_service_ports": [
            {"port": 445, "protocol": 6},
            {"port": 22, "protocol": 6},
        ]}}


def _cm(enabled: bool):
    asf = types.SimpleNamespace(enabled=enabled, max_workloads=500, cache_ttl_hours=24)
    report = types.SimpleNamespace(attack_surface=asf)
    pce = types.SimpleNamespace(rate_limit_per_minute=400)
    models = types.SimpleNamespace(report=report, pce_cache=pce)
    return types.SimpleNamespace(models=models)


def test_disabled_returns_none_and_makes_no_api_calls():
    api = _FakeApi()
    assert _compute_open_ports_surface(api, _cm(enabled=False), 20) is None
    assert api.get_calls == 0  # opt-in: zero enrichment work when disabled


def test_missing_api_returns_none():
    assert _compute_open_ports_surface(None, _cm(enabled=True), 20) is None


def test_enabled_populates_surface(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    api = _FakeApi()
    res = _compute_open_ports_surface(api, _cm(enabled=True), 20)
    assert res is not None
    assert res["total_workloads"] == 2
    assert res["workloads_with_services"] == 2
    top = {(p["port"], p["protocol"]): p for p in res["top_ports"]}
    assert (445, "TCP") in top
    assert top[(445, "TCP")]["workload_count"] == 2


def test_enabled_survives_api_error(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()

    class _BrokenApi(_FakeApi):
        def get_workload(self, href):
            raise RuntimeError("boom")

    res = _compute_open_ports_surface(_BrokenApi(), _cm(enabled=True), 20)
    # enrichment tolerates per-workload errors → empty ports, still a valid dict
    assert res is not None
    assert res["workloads_with_services"] == 0
