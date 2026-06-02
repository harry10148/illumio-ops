"""Estate inventory pure analysis functions operating on PCE workload dicts."""
from __future__ import annotations

from collections import defaultdict

_CANONICAL_MODES = ("idle", "visibility_only", "selective", "full")

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _classify_family(os_id: str | None) -> str:
    """Map an os_id string to a high-level OS family name."""
    if not os_id:
        return "Unknown"
    s = os_id.lower()
    if s.startswith("win"):
        return "Windows"
    if any(tok in s for tok in ("linux", "rhel", "ubuntu", "centos", "debian", "suse", "oracle", "amazon")):
        return "Linux"
    if "aix" in s:
        return "AIX"
    if "solaris" in s or "sunos" in s:
        return "Solaris"
    return "Other"


def _workload_networks(workload: dict) -> set[str]:
    """Return the distinct network names reachable from a workload's interfaces.

    Returns ``{"(no network)"}`` when none can be resolved.
    """
    interfaces = workload.get("interfaces") or []
    names: set[str] = set()
    for iface in interfaces:
        net = iface.get("network") if isinstance(iface, dict) else None
        if net and isinstance(net, dict):
            name = net.get("name")
            if name:
                names.add(name)
    return names if names else {"(no network)"}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def os_distribution(workloads: list[dict]) -> dict:
    """Return OS-id counts, OS-family counts (non-zero only), and total workload count.

    ``by_os_id`` is sorted descending by count.
    ``by_family`` omits families with zero workloads.
    """
    raw_counts: dict[str, int] = defaultdict(int)
    family_counts: dict[str, int] = defaultdict(int)

    for wl in workloads:
        os_id = wl.get("os_id") or ""
        raw_counts[os_id] += 1
        family_counts[_classify_family(os_id)] += 1

    by_os_id = dict(sorted(raw_counts.items(), key=lambda kv: kv[1], reverse=True))
    by_family = {k: v for k, v in family_counts.items() if v > 0}

    return {"by_os_id": by_os_id, "by_family": by_family, "total": len(workloads)}


def enforcement_distribution(workloads: list[dict]) -> dict:
    """Return enforcement-mode counts and total workload count.

    Always includes the four canonical keys: idle, visibility_only, selective, full.
    Missing/None mode is counted under ``"unknown"``.
    """
    counts: dict[str, int] = {mode: 0 for mode in _CANONICAL_MODES}

    for wl in workloads:
        mode = wl.get("enforcement_mode") or None
        if not mode:
            mode = "unknown"
        counts[mode] = counts.get(mode, 0) + 1

    return {"by_mode": counts, "total": len(workloads)}


def enforcement_by_network(workloads: list[dict]) -> list[dict]:
    """Return per-network enforcement-mode breakdowns, sorted by total desc.

    A workload is attributed once per distinct network it touches.
    Workloads with no resolvable network are attributed to ``"(no network)"``.
    """
    # network_name → mode → count
    network_modes: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for wl in workloads:
        mode = wl.get("enforcement_mode") or "unknown"
        for net_name in _workload_networks(wl):
            network_modes[net_name][mode] += 1

    result = []
    for net_name, mode_counts in network_modes.items():
        total = sum(mode_counts.values())
        result.append({"network": net_name, "total": total, "by_mode": dict(mode_counts)})

    result.sort(key=lambda e: e["total"], reverse=True)
    return result
