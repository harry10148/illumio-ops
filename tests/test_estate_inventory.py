"""Tests for estate_inventory pure analysis functions."""
from __future__ import annotations

import pytest

from src.report.analysis.estate_inventory import (
    enforcement_by_network,
    enforcement_distribution,
    os_distribution,
)

# ---------------------------------------------------------------------------
# Fixture: 5 workloads covering all edge cases
# ---------------------------------------------------------------------------
WORKLOADS = [
    # 0 - Windows, selective, two networks (Corporate + DMZ)
    {
        "os_id": "win-x86_64-client",
        "enforcement_mode": "selective",
        "online": True,
        "interfaces": [
            {"name": "eth0", "address": "10.0.0.1", "network": {"href": "/orgs/1/networks/1", "name": "Corporate"}},
            {"name": "eth1", "address": "172.16.0.1", "network": {"href": "/orgs/1/networks/2", "name": "DMZ"}},
        ],
    },
    # 1 - Linux, full, Corporate network
    {
        "os_id": "rhel-x86_64",
        "enforcement_mode": "full",
        "online": True,
        "interfaces": [
            {"name": "eth0", "address": "10.0.0.2", "network": {"href": "/orgs/1/networks/1", "name": "Corporate"}},
        ],
    },
    # 2 - Linux (ubuntu), visibility_only, Corporate network (same network twice on same workload → count once)
    {
        "os_id": "ubuntu-x86_64",
        "enforcement_mode": "visibility_only",
        "online": True,
        "interfaces": [
            {"name": "eth0", "address": "10.0.0.3", "network": {"href": "/orgs/1/networks/1", "name": "Corporate"}},
            {"name": "eth1", "address": "10.0.0.4", "network": {"href": "/orgs/1/networks/1", "name": "Corporate"}},
        ],
    },
    # 3 - missing os_id, idle, no interfaces field → "(no network)"
    {
        "enforcement_mode": "idle",
        "online": False,
    },
    # 4 - "other" os_id, missing enforcement_mode → "unknown" mode, network=None on interface
    {
        "os_id": "freebsd-x86_64",
        "online": True,
        "interfaces": [
            {"name": "eth0", "address": "192.168.1.1", "network": None},
        ],
    },
]


# ---------------------------------------------------------------------------
# os_distribution tests
# ---------------------------------------------------------------------------
class TestOsDistribution:
    def test_total(self):
        result = os_distribution(WORKLOADS)
        assert result["total"] == 5

    def test_by_os_id_contains_all_present(self):
        result = os_distribution(WORKLOADS)
        by_os = result["by_os_id"]
        assert by_os["win-x86_64-client"] == 1
        assert by_os["rhel-x86_64"] == 1
        assert by_os["ubuntu-x86_64"] == 1
        assert by_os["freebsd-x86_64"] == 1
        # missing os_id workload → key "" or some sentinel; check total sums to 5
        assert sum(by_os.values()) == 5

    def test_by_family_windows(self):
        result = os_distribution(WORKLOADS)
        assert result["by_family"]["Windows"] == 1

    def test_by_family_linux(self):
        result = os_distribution(WORKLOADS)
        # rhel + ubuntu = 2
        assert result["by_family"]["Linux"] == 2

    def test_by_family_unknown(self):
        result = os_distribution(WORKLOADS)
        # workload #3 has no os_id
        assert result["by_family"]["Unknown"] == 1

    def test_by_family_other(self):
        result = os_distribution(WORKLOADS)
        # freebsd → Other
        assert result["by_family"]["Other"] == 1

    def test_by_family_only_nonzero(self):
        result = os_distribution(WORKLOADS)
        # AIX and Solaris have zero workloads; must not appear
        assert "AIX" not in result["by_family"]
        assert "Solaris" not in result["by_family"]

    def test_by_os_id_sorted_desc(self):
        # Duplicate os_id to create a clear ordering
        wls = WORKLOADS + [{"os_id": "win-x86_64-client", "enforcement_mode": "full", "interfaces": []}]
        result = os_distribution(wls)
        counts = list(result["by_os_id"].values())
        assert counts == sorted(counts, reverse=True)

    def test_empty(self):
        result = os_distribution([])
        assert result["total"] == 0
        assert result["by_os_id"] == {}
        assert result["by_family"] == {}


# ---------------------------------------------------------------------------
# enforcement_distribution tests
# ---------------------------------------------------------------------------
class TestEnforcementDistribution:
    def test_total(self):
        result = enforcement_distribution(WORKLOADS)
        assert result["total"] == 5

    def test_four_canonical_keys_always_present(self):
        result = enforcement_distribution(WORKLOADS)
        for key in ("idle", "visibility_only", "selective", "full"):
            assert key in result["by_mode"], f"canonical key '{key}' missing"

    def test_counts(self):
        result = enforcement_distribution(WORKLOADS)
        bm = result["by_mode"]
        assert bm["selective"] == 1
        assert bm["full"] == 1
        assert bm["visibility_only"] == 1
        assert bm["idle"] == 1

    def test_missing_mode_counted_as_unknown(self):
        result = enforcement_distribution(WORKLOADS)
        assert result["by_mode"].get("unknown", 0) == 1

    def test_canonical_keys_present_even_with_zero_count(self):
        # Only one workload with 'full'; idle/visibility_only/selective should all be 0
        result = enforcement_distribution([WORKLOADS[1]])
        bm = result["by_mode"]
        assert bm["idle"] == 0
        assert bm["visibility_only"] == 0
        assert bm["selective"] == 0
        assert bm["full"] == 1

    def test_empty(self):
        result = enforcement_distribution([])
        assert result["total"] == 0
        for key in ("idle", "visibility_only", "selective", "full"):
            assert result["by_mode"][key] == 0


# ---------------------------------------------------------------------------
# enforcement_by_network tests
# ---------------------------------------------------------------------------
class TestEnforcementByNetwork:
    def _by_name(self, results):
        return {entry["network"]: entry for entry in results}

    def test_returns_list(self):
        assert isinstance(enforcement_by_network(WORKLOADS), list)

    def test_known_networks_present(self):
        results = self._by_name(enforcement_by_network(WORKLOADS))
        assert "Corporate" in results
        assert "DMZ" in results

    def test_no_network_present(self):
        results = self._by_name(enforcement_by_network(WORKLOADS))
        assert "(no network)" in results

    def test_corporate_total(self):
        # wl#0 (selective), wl#1 (full), wl#2 (visibility_only) → 3
        results = self._by_name(enforcement_by_network(WORKLOADS))
        assert results["Corporate"]["total"] == 3

    def test_dmz_total(self):
        # Only wl#0 → 1
        results = self._by_name(enforcement_by_network(WORKLOADS))
        assert results["DMZ"]["total"] == 1

    def test_no_network_total(self):
        # wl#3 (no interfaces), wl#4 (network=None) → 2
        results = self._by_name(enforcement_by_network(WORKLOADS))
        assert results["(no network)"]["total"] == 2

    def test_multi_network_workload_counted_in_both(self):
        # wl#0 appears in Corporate AND DMZ
        results = self._by_name(enforcement_by_network(WORKLOADS))
        assert results["Corporate"]["by_mode"]["selective"] == 1
        assert results["DMZ"]["by_mode"]["selective"] == 1

    def test_same_network_deduped_per_workload(self):
        # wl#2 has two Corporate interfaces but should only count once in Corporate
        results = self._by_name(enforcement_by_network(WORKLOADS))
        assert results["Corporate"]["by_mode"]["visibility_only"] == 1

    def test_sorted_by_total_desc(self):
        results = enforcement_by_network(WORKLOADS)
        totals = [entry["total"] for entry in results]
        assert totals == sorted(totals, reverse=True)

    def test_empty(self):
        assert enforcement_by_network([]) == []
