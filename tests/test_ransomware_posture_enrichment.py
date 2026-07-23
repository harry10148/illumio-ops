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


def test_per_workload_error_flagged_not_silently_clean(tmp_path):
    """失敗不得偽裝乾淨：條目要帶 enrichment_error、要記 warning，
    且不得寫入 cache（否則假性乾淨會存活整個 TTL）。"""
    import json as _json
    from loguru import logger as _logger

    class BoomApi(FakeApi):
        def get_workload_risk_details(self, href):
            raise RuntimeError("boom")

    records = []
    sink_id = _logger.add(lambda m: records.append(m), level="WARNING")
    try:
        cache = tmp_path / "c.json"
        out = refresh_ransomware_posture(BoomApi(), [_wl("/w/a")],
                                         cache_path=str(cache), now=1.0)
        assert out["/w/a"]["details"] == []
        assert "boom" in out["/w/a"]["enrichment_error"]
        assert any("enrichment failed" in str(m) for m in records)
        cached = _json.loads(cache.read_text()) if cache.exists() else {}
        assert "/w/a" not in cached
    finally:
        _logger.remove(sink_id)


def test_error_entry_retried_next_run(tmp_path):
    """失敗條目未入 cache：下一輪（API 恢復）要重抓並轉乾淨。"""
    class FlakyApi(FakeApi):
        def __init__(self):
            super().__init__()
            self.fail = True

        def get_workload(self, href):
            if self.fail:
                raise RuntimeError("down")
            return super().get_workload(href)

    api = FlakyApi()
    cache = str(tmp_path / "c.json")
    out1 = refresh_ransomware_posture(api, [_wl("/w/a")], cache_path=cache, now=1.0)
    assert out1["/w/a"].get("enrichment_error")
    api.fail = False
    out2 = refresh_ransomware_posture(api, [_wl("/w/a")], cache_path=cache, now=2.0)
    assert not out2["/w/a"].get("enrichment_error")
    assert out2["/w/a"]["open_service_ports"]
