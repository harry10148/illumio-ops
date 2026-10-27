"""Text helpers shared by the report builders: translation, host names, ports, detector names, and the
previous-period comparison of a key metric."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from illumio_ops.domain.lateral import HostInfo
from illumio_ops.domain.values import DetectorKind, Language, PortClass
from illumio_ops.i18n import translate

DETECTOR_NAME_KEYS: Mapping[str, str] = {
    DetectorKind.FANOUT: "detector_name_fanout",
    DetectorKind.NEW_ADMIN_CONNECTION: "detector_name_new_admin_connection",
    DetectorKind.PIVOT_CHAIN: "detector_name_pivot_chain",
    DetectorKind.BLOCKED_SURGE: "detector_name_blocked_surge",
    DetectorKind.NON_ADMIN_GROUP: "detector_name_non_admin_group",
    DetectorKind.CROSS_ENV: "detector_name_cross_env",
    DetectorKind.ACCOUNT_FANOUT: "detector_name_account_fanout",
    DetectorKind.UNEXPECTED_INITIATOR: "detector_name_unexpected_initiator",
    DetectorKind.PEER_DEVIATION: "detector_name_peer_deviation",
    DetectorKind.VOLUME_SURGE: "detector_name_volume_surge",
    DetectorKind.ACCOUNT_NEW_SOURCE: "detector_name_account_new_source",
    DetectorKind.SUSPICIOUS_TOOL: "detector_name_suspicious_tool",
    DetectorKind.NEW_PROCESS: "detector_name_new_process",
    DetectorKind.AUTH_TO_NON_DC: "detector_name_auth_to_non_dc",
    DetectorKind.NEW_DC_CLIENT: "detector_name_new_dc_client",
    DetectorKind.DIRECTORY_SURGE: "detector_name_directory_surge",
}
PORT_CLASS_KEYS: Mapping[PortClass, str] = {
    PortClass.REMOTE: "rpt_port_class_remote", PortClass.DIRECTORY: "rpt_port_class_directory",
    PortClass.DATABASE: "rpt_port_class_database",
}
SEVERITY_KEYS = {"low": "severity_low", "medium": "severity_medium", "high": "severity_high",
                 "critical": "severity_critical"}
PROTOCOLS = {6: "TCP", 17: "UDP", 1: "ICMP"}


def tr(lang: Language, msg: str, /, **params: object) -> str:
    return translate(lang, msg, {k: "" if v is None else str(v) for k, v in params.items()})


def host_name(hosts: Mapping[str, HostInfo], key: str, lang: Language) -> str:
    """A host as an operator knows it: its hostname, else the address of an ip:<address> key; a workload no
    longer in the inventory is said to be removed (its href means nothing to a reader)."""
    host = hosts.get(key)
    if host is not None and host.hostname:
        return host.hostname
    if key.startswith("ip:"):
        return key.removeprefix("ip:")
    if host is None and "/workloads/" in key:
        return tr(lang, "rpt_host_removed", id=key.rsplit("/", 1)[-1][-6:])
    return key


def port_text(port: int | None, proto: int) -> str:
    name = PROTOCOLS.get(proto, str(proto))
    return name if port is None or port < 0 else f"{port}/{name}"


def ports_text(ports: Any) -> str:
    """The exposure graph's port lists: [[port, proto], ...] or [{port, proto}, ...]."""
    out = []
    for p in ports or ():
        port, proto = (p.get("port"), p.get("proto")) if isinstance(p, Mapping) else (p[0], p[1])
        out.append(port_text(port, int(proto or 0)))
    return ", ".join(out)


def detector_name(lang: Language, detector: str) -> str:
    key = DETECTOR_NAME_KEYS.get(detector)
    return tr(lang, key) if key else detector


def severity_name(lang: Language, severity: str) -> str:
    key = SEVERITY_KEYS.get(severity)
    return tr(lang, key) if key else severity
