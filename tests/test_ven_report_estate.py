"""Tests that VenStatusGenerator wires estate inventory analysis into module_results."""
from __future__ import annotations

import types
from unittest.mock import MagicMock


# Minimal workload fixture covering OS and enforcement diversity
_WORKLOADS = [
    {
        "hostname": "win-host",
        "os_id": "win-x86_64-server",
        "enforcement_mode": "selective",
        "interfaces": [
            {"name": "eth0", "address": "10.0.0.1",
             "network": {"href": "/orgs/1/networks/1", "name": "Corp"}},
        ],
        "labels": [],
        "agent": {
            "status": {
                "status": "active",
                "hours_since_last_heartbeat": 0.1,
                "security_policy_sync_state": "synced",
                "last_heartbeat_on": "2026-06-01T00:00:00Z",
                "agent_version": "21.5",
            }
        },
    },
    {
        "hostname": "linux-host",
        "os_id": "rhel-x86_64",
        "enforcement_mode": "full",
        "interfaces": [
            {"name": "eth0", "address": "10.0.0.2",
             "network": {"href": "/orgs/1/networks/1", "name": "Corp"}},
        ],
        "labels": [],
        "agent": {
            "status": {
                "status": "active",
                "hours_since_last_heartbeat": 0.5,
                "security_policy_sync_state": "synced",
                "last_heartbeat_on": "2026-06-01T00:00:00Z",
                "agent_version": "21.5",
            }
        },
    },
    {
        "hostname": "idle-host",
        "os_id": "ubuntu-x86_64",
        "enforcement_mode": "idle",
        "interfaces": [],
        "labels": [],
        "agent": {
            "status": {
                "status": "suspended",
                "hours_since_last_heartbeat": 72,
                "security_policy_sync_state": "staged",
                "last_heartbeat_on": "2026-05-29T00:00:00Z",
                "agent_version": "21.4",
            }
        },
    },
]


def _make_cm():
    return types.SimpleNamespace(config={"settings": {"timezone": "UTC"}})


def _make_api(workloads=_WORKLOADS):
    api = MagicMock()
    api.fetch_managed_workloads.return_value = workloads
    return api


def _generate(tmp_path, workloads=_WORKLOADS):
    from src.report.ven_status_generator import VenStatusGenerator
    gen = VenStatusGenerator(_make_cm(), api_client=_make_api(workloads))
    return gen.generate(output_dir=str(tmp_path))


class TestEstateInventoryWiring:
    def test_os_distribution_key_present(self, tmp_path):
        result = _generate(tmp_path)
        assert "os_distribution" in result.module_results

    def test_enforcement_distribution_key_present(self, tmp_path):
        result = _generate(tmp_path)
        assert "enforcement_distribution" in result.module_results

    def test_enforcement_by_network_key_present(self, tmp_path):
        result = _generate(tmp_path)
        assert "enforcement_by_network" in result.module_results

    def test_os_distribution_total(self, tmp_path):
        result = _generate(tmp_path)
        od = result.module_results["os_distribution"]
        assert od["total"] == len(_WORKLOADS)

    def test_os_distribution_families(self, tmp_path):
        result = _generate(tmp_path)
        by_family = result.module_results["os_distribution"]["by_family"]
        assert by_family.get("Windows", 0) == 1
        assert by_family.get("Linux", 0) == 2

    def test_enforcement_distribution_modes(self, tmp_path):
        result = _generate(tmp_path)
        by_mode = result.module_results["enforcement_distribution"]["by_mode"]
        assert by_mode.get("selective", 0) == 1
        assert by_mode.get("full", 0) == 1
        assert by_mode.get("idle", 0) == 1

    def test_enforcement_by_network_is_list(self, tmp_path):
        result = _generate(tmp_path)
        enf_net = result.module_results["enforcement_by_network"]
        assert isinstance(enf_net, list)

    def test_enforcement_by_network_corp_present(self, tmp_path):
        result = _generate(tmp_path)
        enf_net = result.module_results["enforcement_by_network"]
        net_names = {e["network"] for e in enf_net}
        assert "Corp" in net_names
