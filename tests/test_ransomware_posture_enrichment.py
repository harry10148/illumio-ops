"""Tests for ransomware_posture_enrichment (cache-then-fetch, listening filter)."""
from src.report.ransomware_posture_enrichment import refresh_ransomware_posture


class FakeApi:
    def __init__(self):
        self.workload_calls = 0
        self.rd_calls = 0

    def get_workload(self, href):
        self.workload_calls += 1
        return {"services": {"open_service_ports": [
            {"port": 3389, "protocol": 6, "process_name": "svchost.exe", "user": "SYSTEM"},
        ]}}

    def get_workload_risk_details(self, href):
        self.rd_calls += 1
        return {"risk_details": {"ransomware": {"details": [
            {"port": 3389, "proto": 6, "name": "S-RDP", "severity": "critical",
             "port_status": "listening", "protection_state": "unprotected"},
        ]}}}


def _wl(href, sev="critical"):
    return {"href": href,
            "risk_summary": {"ransomware": {"workload_exposure_severity": sev,
                                            "ransomware_protection_percent": 0.0}}}


def test_fetches_only_computed_non_fully_protected(tmp_path):
    api = FakeApi()
    wls = [
        _wl("/w/a"),                                            # computed critical -> fetch
        {"href": "/w/b", "risk_summary": {"ransomware": None}},  # pending -> skip
        _wl("/w/c", sev="fully_protected"),                      # protected -> skip
    ]
    out = refresh_ransomware_posture(api, wls,
                                     cache_path=str(tmp_path / "c.json"), now=1000.0)
    assert set(out.keys()) == {"/w/a"}
    assert api.workload_calls == 1 and api.rd_calls == 1
    assert out["/w/a"]["details"][0]["name"] == "S-RDP"
    assert out["/w/a"]["open_service_ports"][0]["port"] == 3389


def test_cache_hit_skips_api(tmp_path):
    api = FakeApi()
    cache = str(tmp_path / "c.json")
    refresh_ransomware_posture(api, [_wl("/w/a")], cache_path=cache, now=1000.0)
    assert api.workload_calls == 1
    refresh_ransomware_posture(api, [_wl("/w/a")], cache_path=cache, now=1000.0 + 60)
    assert api.workload_calls == 1 and api.rd_calls == 1


def test_stale_cache_refetches(tmp_path):
    api = FakeApi()
    cache = str(tmp_path / "c.json")
    refresh_ransomware_posture(api, [_wl("/w/a")], cache_path=cache,
                               ttl_hours=24, now=1000.0)
    refresh_ransomware_posture(api, [_wl("/w/a")], cache_path=cache,
                               ttl_hours=24, now=1000.0 + 25 * 3600)
    assert api.workload_calls == 2


def test_per_workload_error_is_swallowed(tmp_path):
    class BoomApi(FakeApi):
        def get_workload_risk_details(self, href):
            raise RuntimeError("boom")
    out = refresh_ransomware_posture(BoomApi(), [_wl("/w/a")],
                                     cache_path=str(tmp_path / "c.json"), now=1.0)
    assert out["/w/a"]["details"] == []
