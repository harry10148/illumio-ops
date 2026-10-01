"""Single definition of "lateral movement ports" for every report module.

mod15 (lateral movement graph) and the rules engine (B006/L006/L008/L010)
used to carry different lists: mod15 also counted MSSQL/MySQL/PostgreSQL,
LDAP and Kerberos, so ordinary app-to-database and directory traffic showed
up as "lateral movement" while the rules engine ignored it. Lateral here
means remote administration, remote execution and file sharing — the
protocols an attacker uses to hop between hosts.

``report_config.yaml``'s ``lateral_movement_ports`` overrides the port set;
service names come from the table below.
"""
from __future__ import annotations

DEFAULT_LATERAL_PORTS: dict[int, str] = {
    22: "SSH",
    23: "Telnet",
    111: "RPC Portmapper",
    135: "RPC",
    139: "NetBIOS",
    445: "SMB",
    2049: "NFS",
    3389: "RDP",
    5900: "VNC",
    5938: "TeamViewer",
    5985: "WinRM-HTTP",
    5986: "WinRM-HTTPS",
}


def lateral_ports(report_config: dict | None = None) -> dict[int, str]:
    """Port → service name, honouring ``lateral_movement_ports`` if set."""
    configured = (report_config or {}).get("lateral_movement_ports")
    if not configured:
        return dict(DEFAULT_LATERAL_PORTS)
    out: dict[int, str] = {}
    for p in configured:
        try:
            port = int(p)
        except (TypeError, ValueError):
            continue
        out[port] = DEFAULT_LATERAL_PORTS.get(port, f"TCP/{port}")
    return out or dict(DEFAULT_LATERAL_PORTS)
