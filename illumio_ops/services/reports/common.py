"""Text helpers shared by the report builders: translation, host names, ports, detector names, and the
previous-period comparison of a key metric."""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from itertools import islice
from typing import Any
from urllib.parse import quote_plus

from illumio_ops.domain.lateral import HostInfo
from illumio_ops.domain.policy import ActorRef, RuleRef
from illumio_ops.domain.report import HTML_ROW_CAP
from illumio_ops.domain.tamper import TAMPER_PATTERN_KEYS
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
    DetectorKind.DIRECTION_REVERSAL: "detector_name_direction_reversal",
    DetectorKind.NEW_PAIR_PORT: "detector_name_new_pair_port",
    DetectorKind.QUIET_HOST_WAKES: "detector_name_quiet_host_wakes",
    DetectorKind.DATA_STAGING: "detector_name_data_staging",
    DetectorKind.OFF_HOURS: "detector_name_off_hours",
}
PORT_CLASS_KEYS: Mapping[PortClass, str] = {
    PortClass.REMOTE: "rpt_port_class_remote", PortClass.DIRECTORY: "rpt_port_class_directory",
    PortClass.DATABASE: "rpt_port_class_database",
}
SEVERITY_KEYS = {"low": "severity_low", "medium": "severity_medium", "high": "severity_high",
                 "critical": "severity_critical"}
PROTOCOLS = {6: "TCP", 17: "UDP", 1: "ICMP"}
# The PCE's own values for a VEN's policy sync state and an event's outcome. A value outside these has no wording
# here and is shown as the PCE sent it.
SYNC_STATE_KEYS = {"applied": "rpt_sync_applied", "synced": "rpt_sync_applied", "syncing": "rpt_sync_syncing",
                   "staged": "rpt_sync_staged"}
EVENT_STATUS_KEYS = {"success": "rpt_status_success", "failure": "rpt_status_failure"}
# A policy decision where it is a name (a table cell, a state): plain words with the PCE's own word in brackets, the
# same table the console uses (web/src/terms.ts). decision_unknown is not reworded yet (stage 3b).
DECISION_KEYS = {"allowed": "term_decision_allowed", "potentially_blocked": "term_decision_potentially_blocked",
                 "blocked": "term_decision_blocked", "unknown": "decision_unknown"}
# The same decision inside a sentence: the PCE's own word alone (a sentence is not reworded).
DECISION_IN_SENTENCE_KEYS = {"allowed": "decision_allowed", "potentially_blocked": "decision_potentially_blocked",
                             "blocked": "decision_blocked", "unknown": "decision_unknown"}
MODE_KEYS = {"idle": "term_mode_idle", "visibility_only": "term_mode_visibility_only",
             "selective": "term_mode_selective", "full": "term_mode_full"}


def tr(lang: Language, msg: str, /, **params: object) -> str:
    return translate(lang, msg, {k: "" if v is None else str(v) for k, v in params.items()})


def utc_days_note(start: datetime, end: datetime, lang: Language) -> tuple[str, ...]:
    """The data note of a report that counts traffic over a period whose days are not UTC days: the PCE keeps
    traffic by UTC day (services/collect/windows.py), so the first and the last day are counted whole. Nothing when
    the period starts and ends at a UTC midnight."""
    def midnight(at: datetime) -> bool:
        u = at.astimezone(UTC)
        return (u.hour, u.minute, u.second, u.microsecond) == (0, 0, 0, 0)
    return () if midnight(start) and midnight(end) else (tr(lang, "rpt_quality_utc_days"),)


# What the console's host page opens (web/src/components/HostLink.tsx OPENS): a workload or an address, not a
# Kubernetes or container workload.
HOST_PAGE_KEY = re.compile(r"^(/orgs/\d+/workloads/|ip:)")


def host_url(base: str | None, key: str | None, section: str | None) -> str | None:
    """The address of a host's page in the console, the same one the web app's hostPath makes (its
    URLSearchParams leaves '*' and writes '~' as %7E; Python's urlencode does the opposite). None: no external
    address is set, or the key is not one the host page opens — the name stays text."""
    if not base or not key or not base.startswith(("http://", "https://")) or not HOST_PAGE_KEY.match(key):
        return None
    query = quote_plus(key, safe="*").replace("~", "%7E")
    return f"{base.rstrip('/')}/hosts?key={query}" + (f"#{section}" if section else "")


def unnamed_host(key: str, lang: Language) -> str | None:
    """Words for a workload href nothing names (its href means nothing to a reader): a workload not in the inventory
    has been removed; a Kubernetes or container workload is not one the inventory holds. None: not such an href."""
    if "/workloads/" in key:
        return tr(lang, "rpt_host_removed", id=key.rsplit("/", 1)[-1][-6:])
    if "/kubernetes_workloads/" in key or "/container_workloads/" in key:
        return tr(lang, "rpt_host_container", id=key.rsplit("/", 1)[-1][-6:])
    return None


def host_name(hosts: Mapping[str, HostInfo], key: str, lang: Language) -> str:
    """A host as an operator knows it: its hostname, else the address of an ip:<address> key, else what it is
    (unnamed_host)."""
    host = hosts.get(key)
    if host is not None and host.hostname:
        return host.hostname
    if key.startswith("ip:"):
        return key.removeprefix("ip:")
    return (unnamed_host(key, lang) if host is None else None) or key


def host_key(hosts: Mapping[str, Any], key: object) -> str | None:
    """`key` when it names a host — one the inventory holds, a workload of the PCE, an ip:<address> — else None (an
    account, a name with no key behind it): what a table's host_keys carry for that cell."""
    if not isinstance(key, str) or not key:
        return None
    return key if key in hosts or key.startswith(("ip:", "/orgs/")) else None


def host_keys(**columns: Iterable[str | None]) -> dict[str, tuple[str | None, ...]]:
    """TableBlock.host_keys from each host column's keys in the order of the table's rows: only the first
    HTML_ROW_CAP are kept (the HTML prints no more rows, and nothing else reads them)."""
    return {column: tuple(islice(keys, HTML_ROW_CAP)) for column, keys in columns.items()}


def mode_word(lang: Language, mode: str) -> str:
    """An enforcement mode as "plain words (PCE term)", the console's own wording (web/src/terms.ts modeWord); a
    mode this table does not know is shown as it is."""
    key = MODE_KEYS.get(mode)
    return tr(lang, key) if key else mode


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


def sync_state_name(lang: Language, state: str | None) -> str:
    key = SYNC_STATE_KEYS.get(state or "")
    return tr(lang, key) if key else state or "—"


def event_status_name(lang: Language, status: str | None) -> str:
    key = EVENT_STATUS_KEYS.get(status or "")
    return tr(lang, key) if key else status or "—"


def tamper_pattern_name(lang: Language, pattern: str | None) -> str:
    key = next((k for p, k in TAMPER_PATTERN_KEYS.items() if p.value == pattern), None)
    return tr(lang, key) if key else pattern or "—"


def rule_label(lang: Language, ruleset_name: str, description: str | None, href: str) -> str:
    """A rule as a reader can find it on the PCE: its ruleset and its description, or its id when it has none."""
    if description:
        return f"{ruleset_name}: {description}"
    return tr(lang, "rpt_rule_no_description", ruleset=ruleset_name, id=href.rsplit("/", 1)[-1])


def rule_id(r: RuleRef) -> str:
    return f"#{r.href.rsplit('/', 1)[-1]}"


def _actor(a: ActorRef) -> str:
    text = a.name or (f"{a.key}={a.value}" if a.key else None) or a.kind
    return f"−{text}" if a.exclusion else text


def rule_scope(r: RuleRef, any_text: str) -> str:
    """'consumers → providers：services' of a rule, as the policy usage report's tables say what a rule covers."""
    consumers = ", ".join(_actor(a) for a in r.consumers) or any_text
    providers = ", ".join(_actor(a) for a in r.providers) or any_text
    services = ", ".join(s.name or port_text(s.port, s.proto or 0) for s in r.services) or any_text
    return f"{consumers} → {providers}：{services}"
