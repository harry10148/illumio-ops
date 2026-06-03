"""Unit test for ApiClient.get_workload_risk_details."""
from unittest.mock import MagicMock
from src.api_client import ApiClient


def _client():
    api = ApiClient.__new__(ApiClient)  # bypass __init__ (no real config/network)
    api.api_cfg = {"url": "https://pce.example:8443"}
    return api


def test_get_workload_risk_details_ok(monkeypatch):
    api = _client()
    captured = {}

    def fake_request(url, timeout=10):
        captured["url"] = url
        return 200, b'{"risk_details": {"ransomware": {"details": []}}}'

    api._request = fake_request
    out = api.get_workload_risk_details("/orgs/1/workloads/abc")
    assert captured["url"] == "https://pce.example:8443/api/v2/orgs/1/workloads/abc/risk_details"
    assert out["risk_details"]["ransomware"]["details"] == []


def test_get_workload_risk_details_error_returns_empty():
    api = _client()
    api._request = lambda url, timeout=10: (404, b"not found")
    assert api.get_workload_risk_details("/orgs/1/workloads/missing") == {}
