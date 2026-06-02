"""Pure analysis: aggregate open service ports across workloads."""
from __future__ import annotations

from collections import defaultdict


_PROTO_NAMES: dict[int, str] = {6: "TCP", 17: "UDP"}
_MAX_SAMPLE_HOSTS = 5


def open_ports_surface(workloads: list[dict], top_n: int = 20) -> dict:
    """Aggregate open_service_ports across workloads.

    Args:
        workloads: List of workload dicts, each optionally containing
                   ``services.open_service_ports``.
        top_n: Maximum number of entries to include in ``top_ports``.

    Returns:
        Dict with keys: top_ports, total_ports, workloads_with_services,
        total_workloads.
    """
    # (port, protocol_int) -> set of workload hostnames that expose it
    port_workloads: dict[tuple[int, int], set[str]] = defaultdict(set)
    # (port, protocol_int) -> list of sample hostnames (capped)
    port_samples: dict[tuple[int, int], list[str]] = defaultdict(list)

    workloads_with_services = 0

    for wl in workloads:
        services = wl.get("services")
        if not isinstance(services, dict):
            continue
        osp = services.get("open_service_ports")
        if not isinstance(osp, list) or not osp:
            continue

        # Collect distinct (port, proto) pairs for this workload
        seen_this_wl: set[tuple[int, int]] = set()
        hostname = str(wl.get("hostname") or wl.get("href") or "")
        has_any = False

        for entry in osp:
            if not isinstance(entry, dict):
                continue
            port = entry.get("port")
            proto = entry.get("protocol")
            if port is None or proto is None:
                continue
            try:
                port = int(port)
                proto = int(proto)
            except (TypeError, ValueError):
                continue

            key = (port, proto)
            if key not in seen_this_wl:
                seen_this_wl.add(key)
                port_workloads[key].add(hostname)
                if len(port_samples[key]) < _MAX_SAMPLE_HOSTS:
                    port_samples[key].append(hostname)
                has_any = True

        if has_any:
            workloads_with_services += 1

    # Build sorted top_ports list
    all_keys = list(port_workloads.keys())
    all_keys.sort(key=lambda k: -len(port_workloads[k]))

    top_ports = []
    for key in all_keys[:top_n]:
        port, proto = key
        top_ports.append(
            {
                "port": port,
                "protocol": _PROTO_NAMES.get(proto, str(proto)),
                "workload_count": len(port_workloads[key]),
                "sample_hosts": port_samples[key],
            }
        )

    return {
        "top_ports": top_ports,
        "total_ports": len(all_keys),
        "workloads_with_services": workloads_with_services,
        "total_workloads": len(workloads),
    }
