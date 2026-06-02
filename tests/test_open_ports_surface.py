"""Tests for open-ports attack-surface analysis (Piece A), enrichment (Piece B),
and config (Piece C)."""
from __future__ import annotations

import json
import time

import pytest

# ---------------------------------------------------------------------------
# Piece A: pure analysis
# ---------------------------------------------------------------------------

from src.report.analysis.open_ports_surface import open_ports_surface


def _workload(hostname: str, ports: list[dict] | None) -> dict:
    """Build a minimal workload dict with or without open_service_ports."""
    w: dict = {"hostname": hostname, "href": f"/orgs/1/workloads/{hostname}"}
    if ports is not None:
        w["services"] = {"open_service_ports": ports}
    return w


def _port(port: int, proto: int) -> dict:
    return {"port": port, "protocol": proto}


class TestOpenPortsSurface:
    def test_empty_workloads(self):
        result = open_ports_surface([])
        assert result["top_ports"] == []
        assert result["total_ports"] == 0
        assert result["workloads_with_services"] == 0
        assert result["total_workloads"] == 0

    def test_workload_without_services(self):
        result = open_ports_surface([_workload("host1", None)])
        assert result["total_workloads"] == 1
        assert result["workloads_with_services"] == 0
        assert result["top_ports"] == []

    def test_workload_with_empty_services(self):
        w = {"hostname": "host1", "services": {}}
        result = open_ports_surface([w])
        assert result["workloads_with_services"] == 0

    def test_protocol_names_tcp_udp_other(self):
        workloads = [
            _workload("h1", [_port(80, 6), _port(53, 17), _port(1, 99)]),
        ]
        result = open_ports_surface(workloads)
        protos = {e["port"]: e["protocol"] for e in result["top_ports"]}
        assert protos[80] == "TCP"
        assert protos[53] == "UDP"
        assert protos[1] == "99"

    def test_workload_count_dedup_within_same_workload(self):
        """A workload with the same port listed twice counts only once."""
        workloads = [
            _workload("h1", [_port(445, 6), _port(445, 6)]),
        ]
        result = open_ports_surface(workloads)
        assert len(result["top_ports"]) == 1
        assert result["top_ports"][0]["workload_count"] == 1

    def test_workload_count_across_multiple_workloads(self):
        """Same port on multiple workloads → count equals number of workloads."""
        workloads = [
            _workload("h1", [_port(445, 6)]),
            _workload("h2", [_port(445, 6)]),
            _workload("h3", [_port(445, 6)]),
        ]
        result = open_ports_surface(workloads)
        assert result["top_ports"][0]["workload_count"] == 3
        assert result["workloads_with_services"] == 3

    def test_sorted_by_workload_count_desc(self):
        workloads = [
            _workload("h1", [_port(22, 6), _port(445, 6)]),
            _workload("h2", [_port(445, 6)]),
        ]
        result = open_ports_surface(workloads)
        counts = [e["workload_count"] for e in result["top_ports"]]
        assert counts == sorted(counts, reverse=True)
        assert result["top_ports"][0]["port"] == 445

    def test_top_n_limit(self):
        # 25 distinct ports; top_n=10 → only 10 returned
        workloads = [_workload("h1", [_port(p, 6) for p in range(1, 26)])]
        result = open_ports_surface(workloads, top_n=10)
        assert len(result["top_ports"]) == 10
        assert result["total_ports"] == 25

    def test_sample_hosts_collected(self):
        workloads = [_workload(f"host{i}", [_port(80, 6)]) for i in range(10)]
        result = open_ports_surface(workloads)
        entry = result["top_ports"][0]
        assert 1 <= len(entry["sample_hosts"]) <= 5

    def test_total_ports_counts_distinct_port_proto_pairs(self):
        workloads = [
            _workload("h1", [_port(80, 6), _port(80, 17)]),  # same port, diff proto
        ]
        result = open_ports_surface(workloads)
        assert result["total_ports"] == 2

    def test_missing_fields_in_port_entry_are_ignored(self):
        """Port entry with only some fields should not raise."""
        workloads = [_workload("h1", [{"port": 443, "protocol": 6, "extra": "ignored"}])]
        result = open_ports_surface(workloads)
        assert result["total_ports"] == 1

    def test_port_entry_without_protocol_skipped(self):
        """Entry missing 'port' or 'protocol' should be skipped defensively."""
        workloads = [_workload("h1", [{"process_name": "foo"}])]
        result = open_ports_surface(workloads)
        assert result["total_ports"] == 0

    def test_workloads_with_services_count(self):
        workloads = [
            _workload("h1", [_port(80, 6)]),
            _workload("h2", None),               # no services key
            _workload("h3", []),                 # empty list
        ]
        result = open_ports_surface(workloads)
        # h1 has open ports → counted; h2 no services; h3 empty list
        assert result["workloads_with_services"] == 1
        assert result["total_workloads"] == 3


# ---------------------------------------------------------------------------
# Piece B: enrichment + cache
# ---------------------------------------------------------------------------

from src.report.open_ports_enrichment import refresh_open_ports, load_open_ports_cache


class FakeApi:
    """Fake api whose get_workload counts calls and returns canned data."""

    def __init__(self, data: dict[str, dict] | None = None, raise_for: set[str] | None = None):
        self._data = data or {}
        self._raise_for = raise_for or set()
        self.call_count = 0
        self.called_hrefs: list[str] = []

    def get_workload(self, href: str) -> dict:
        self.call_count += 1
        self.called_hrefs.append(href)
        if href in self._raise_for:
            raise RuntimeError(f"simulated error for {href}")
        return self._data.get(href, {})


def _wl(href: str, hostname: str = "host") -> dict:
    return {"href": href, "hostname": hostname}


FIXED_NOW = 1_000_000.0  # arbitrary epoch seconds


class TestRefreshOpenPorts:
    def test_fetches_and_caches(self, tmp_path):
        cache_path = str(tmp_path / "cache.json")
        api = FakeApi(
            data={
                "/w/1": {"services": {"open_service_ports": [{"port": 80, "protocol": 6}]}},
            }
        )
        workloads = [_wl("/w/1", "host1")]
        result = refresh_open_ports(
            api, workloads,
            cache_path=cache_path,
            now=FIXED_NOW,
            rate_per_minute=6000,  # high limit → no wait in tests
        )
        assert api.call_count == 1
        assert len(result) == 1
        ports = result[0]["services"]["open_service_ports"]
        assert ports[0]["port"] == 80

        # Cache file should exist and contain the href
        cache = load_open_ports_cache(cache_path)
        assert "/w/1" in cache
        assert cache["/w/1"]["open_service_ports"][0]["port"] == 80

    def test_cache_hit_makes_zero_api_calls(self, tmp_path):
        cache_path = str(tmp_path / "cache.json")
        api = FakeApi(
            data={"/w/1": {"services": {"open_service_ports": [{"port": 443, "protocol": 6}]}}}
        )
        workloads = [_wl("/w/1", "host1")]

        # First call: populate the cache
        refresh_open_ports(api, workloads, cache_path=cache_path, now=FIXED_NOW, rate_per_minute=6000)
        assert api.call_count == 1

        # Second call within TTL: must make ZERO new api calls
        api2 = FakeApi(data={"/w/1": {"services": {"open_service_ports": [{"port": 999, "protocol": 6}]}}})
        result2 = refresh_open_ports(
            api2, workloads, cache_path=cache_path,
            now=FIXED_NOW + 3600,  # 1 hour later, still within default 24h TTL
            rate_per_minute=6000,
        )
        assert api2.call_count == 0, "Cache hit should make zero api calls"
        # Should return cached port (443), not the new fake (999)
        assert result2[0]["services"]["open_service_ports"][0]["port"] == 443

    def test_stale_cache_triggers_new_fetch(self, tmp_path):
        cache_path = str(tmp_path / "cache.json")
        api1 = FakeApi(
            data={"/w/1": {"services": {"open_service_ports": [{"port": 80, "protocol": 6}]}}}
        )
        workloads = [_wl("/w/1", "host1")]

        # First call
        refresh_open_ports(api1, workloads, cache_path=cache_path, now=FIXED_NOW, rate_per_minute=6000)

        # Call well beyond TTL
        api2 = FakeApi(
            data={"/w/1": {"services": {"open_service_ports": [{"port": 8080, "protocol": 6}]}}}
        )
        result = refresh_open_ports(
            api2, workloads, cache_path=cache_path,
            now=FIXED_NOW + 25 * 3600,  # 25 hours later (> 24h TTL)
            rate_per_minute=6000,
        )
        assert api2.call_count == 1
        assert result[0]["services"]["open_service_ports"][0]["port"] == 8080

    def test_max_workloads_cap(self, tmp_path):
        cache_path = str(tmp_path / "cache.json")
        workloads = [_wl(f"/w/{i}", f"host{i}") for i in range(10)]
        api = FakeApi(data={f"/w/{i}": {} for i in range(10)})
        result = refresh_open_ports(
            api, workloads, max_workloads=3, cache_path=cache_path,
            now=FIXED_NOW, rate_per_minute=6000,
        )
        assert len(result) == 3
        assert api.call_count == 3

    def test_api_error_for_one_href_continues(self, tmp_path):
        cache_path = str(tmp_path / "cache.json")
        api = FakeApi(
            data={"/w/2": {"services": {"open_service_ports": [{"port": 22, "protocol": 6}]}}},
            raise_for={"/w/1"},
        )
        workloads = [_wl("/w/1", "host1"), _wl("/w/2", "host2")]
        result = refresh_open_ports(
            api, workloads, cache_path=cache_path, now=FIXED_NOW, rate_per_minute=6000
        )
        assert len(result) == 2
        # host1 errored → empty ports
        h1 = next(r for r in result if r["href"] == "/w/1")
        assert h1["services"]["open_service_ports"] == []
        # host2 succeeded
        h2 = next(r for r in result if r["href"] == "/w/2")
        assert h2["services"]["open_service_ports"][0]["port"] == 22

    def test_missing_services_in_response_treated_as_empty(self, tmp_path):
        """API returns a dict with no 'services' key → ports treated as []."""
        cache_path = str(tmp_path / "cache.json")
        api = FakeApi(data={"/w/1": {"name": "foo"}})
        workloads = [_wl("/w/1", "host1")]
        result = refresh_open_ports(api, workloads, cache_path=cache_path, now=FIXED_NOW, rate_per_minute=6000)
        assert result[0]["services"]["open_service_ports"] == []

    def test_cache_persisted_between_calls(self, tmp_path):
        cache_path = str(tmp_path / "cache.json")
        api = FakeApi(
            data={"/w/1": {"services": {"open_service_ports": [{"port": 5985, "protocol": 6}]}}}
        )
        refresh_open_ports(api, [_wl("/w/1")], cache_path=cache_path, now=FIXED_NOW, rate_per_minute=6000)
        raw = load_open_ports_cache(cache_path)
        assert raw["/w/1"]["fetched_at"] == FIXED_NOW


# ---------------------------------------------------------------------------
# Piece C: config
# ---------------------------------------------------------------------------

from src.config_models import ReportSettings


class TestAttackSurfaceConfig:
    def test_default_disabled(self):
        s = ReportSettings()
        assert s.attack_surface.enabled is False

    def test_default_max_workloads(self):
        s = ReportSettings()
        assert s.attack_surface.max_workloads == 500

    def test_default_cache_ttl_hours(self):
        s = ReportSettings()
        assert s.attack_surface.cache_ttl_hours == 24

    def test_can_enable(self):
        s = ReportSettings(attack_surface={"enabled": True})
        assert s.attack_surface.enabled is True

    def test_max_workloads_min_1(self):
        with pytest.raises(Exception):
            ReportSettings(attack_surface={"max_workloads": 0})

    def test_cache_ttl_min_1(self):
        with pytest.raises(Exception):
            ReportSettings(attack_surface={"cache_ttl_hours": 0})
