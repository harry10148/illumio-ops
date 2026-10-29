"""The single registry of value domains. Values are strings, never integer codes.

5.x encoded policy decisions six different ways (ints with conflicting
sentinels among them); v6 keeps one string vocabulary here and exports it to
the frontend through the API contracts.
"""
from __future__ import annotations

from enum import StrEnum


class PolicyDecision(StrEnum):
    ALLOWED = "allowed"
    POTENTIALLY_BLOCKED = "potentially_blocked"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class RuleAction(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    OVERRIDE_DENY = "override_deny"


class AlertRuleType(StrEnum):
    EVENT = "event"
    TRAFFIC = "traffic"
    BANDWIDTH = "bandwidth"
    VOLUME = "volume"
    SYSTEM = "system"
    LATERAL = "lateral"


class ThresholdType(StrEnum):
    """An event rule fires on the matches of one evaluation (immediate) or on a count within its window."""
    IMMEDIATE = "immediate"
    COUNT = "count"


class ChannelKind(StrEnum):
    SMTP = "smtp"
    LINE = "line"
    TELEGRAM = "telegram"
    TEAMS = "teams"
    WEBHOOK = "webhook"


class SystemCheck(StrEnum):
    """What a system rule watches: the PCE itself, and this product's own collection (5.x's watchdog and
    data-loss meta-alerts)."""
    PCE_HEALTH = "pce_health"
    COLLECTION_FAILING = "collection_failing"
    DATA_LOSS = "data_loss"
    JOB_FAILING = "job_failing"
    DISK_LOW = "disk_low"


class DeliveryStatus(StrEnum):
    """One alert on one channel. An alert that is not sent still has a row saying why."""
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    NOT_NOTIFIED = "not_notified"   # the rule records only
    GROUPED = "grouped"             # tampering with a known cause
    NO_CHANNEL = "no_channel"       # no channel was enabled


class DeploymentType(StrEnum):
    ON_PREM = "on_prem"
    SAAS = "saas"


class Language(StrEnum):
    EN = "en"
    ZH_TW = "zh_TW"


class ProbeName(StrEnum):
    NOOP = "noop"
    HEALTH = "health"
    NODE_AVAILABLE = "node_available"


class FlowDirection(StrEnum):
    """Which VEN reported the flow: outbound = the initiating side, inbound = the serving side."""
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class VisibilityLevel(StrEnum):
    FLOW_SUMMARY = "flow_summary"
    ENHANCED_DATA_COLLECTION = "enhanced_data_collection"
    FLOW_DROPS = "flow_drops"
    FLOW_OFF = "flow_off"


class TamperClassification(StrEnum):
    CONFIRMED = "confirmed"
    SIGNAL = "signal"


class IngestSource(StrEnum):
    TRAFFIC = "traffic"
    EVENTS = "events"
    INVENTORY = "inventory"
    RANSOMWARE = "ransomware"
    READINESS = "readiness"
    BACKFILL = "backfill"


class CollectionMode(StrEnum):
    """What data collection reads (spec §6.4): everything; events plus short-lived traffic for
    alerts; or no traffic at all (lightweight, the new-install default: flow reports query the PCE on demand)."""
    FULL = "full"
    ALERT = "alert"
    LIGHTWEIGHT = "lightweight"


class CapabilityState(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class DataOrigin(StrEnum):
    INGEST = "ingest"
    BACKFILL = "backfill"



class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


SEVERITY_ORDER: tuple[Severity, ...] = (Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL)


# PCE event severities (err / warning / info) as alert severities, for event rules set to "as the event".
EVENT_SEVERITY_TO_ALERT: dict[str, Severity] = {
    "err": Severity.HIGH, "error": Severity.HIGH, "warning": Severity.MEDIUM, "info": Severity.LOW,
}


def alert_severity_of_event(event_severity: str | None) -> Severity:
    return EVENT_SEVERITY_TO_ALERT.get((event_severity or "").strip().lower(), Severity.MEDIUM)


def raise_severity(s: Severity, steps: int = 1) -> Severity:
    """One or more levels up, never past critical (a precursor on the host raises a detection)."""
    return SEVERITY_ORDER[min(SEVERITY_ORDER.index(s) + steps, len(SEVERITY_ORDER) - 1)]


class DetectorKind(StrEnum):
    """The lateral-movement detectors of spec §6.5.1 and the allowed-traffic anomaly detectors of §6.5.8."""
    FANOUT = "fanout"
    NEW_ADMIN_CONNECTION = "new_admin_connection"
    PIVOT_CHAIN = "pivot_chain"
    BLOCKED_SURGE = "blocked_surge"
    NON_ADMIN_GROUP = "non_admin_group"
    CROSS_ENV = "cross_env"
    ACCOUNT_FANOUT = "account_fanout"
    UNEXPECTED_INITIATOR = "unexpected_initiator"
    # anomalies in allowed traffic (spec §6.5.8)
    PEER_DEVIATION = "peer_deviation"
    VOLUME_SURGE = "volume_surge"
    ACCOUNT_NEW_SOURCE = "account_new_source"
    SUSPICIOUS_TOOL = "suspicious_tool"
    NEW_PROCESS = "new_process"
    AUTH_TO_NON_DC = "auth_to_non_dc"
    NEW_DC_CLIENT = "new_dc_client"
    DIRECTORY_SURGE = "directory_surge"


class PortClass(StrEnum):
    """The three kinds of management port (spec §6.5.8): remote execution and control, directory and
    authentication, and databases. Each detector reads the classes it is about."""
    REMOTE = "remote"
    DIRECTORY = "directory"
    DATABASE = "database"


class DetectorState(StrEnum):
    """What a detector run can say besides its detections: "no detection" is only ever OK."""
    OK = "ok"
    DISABLED = "disabled"
    ACCUMULATING = "accumulating"
    NO_DATA = "no_data"
    COLLECTION_OFF = "collection_off"
    INCOMPLETE = "incomplete"


class SegmentDimension(StrEnum):
    # flows
    SRC_HOST = "src_host"
    DST_HOST = "dst_host"
    SRC_LABEL = "src_label"
    DST_LABEL = "dst_label"
    SERVICE = "service"
    INITIATOR_PROCESS = "initiator_process"
    INITIATOR_USER = "initiator_user"
    SERVICE_PROCESS = "service_process"
    SERVICE_USER = "service_user"
    DECISION = "decision"
    DIRECTION = "direction"
    # events
    EVENT_TYPE = "event_type"
    EVENT_HOST = "event_host"
    EVENT_SEVERITY = "event_severity"
    ACTOR = "actor"


class SegmentMetric(StrEnum):
    FLOWS = "flows"
    CONNECTIONS = "connections"
    DISTINCT_DST = "distinct_dst"
    DISTINCT_SRC = "distinct_src"
    DISTINCT_PORTS = "distinct_ports"
    BYTES = "bytes"
    EVENTS = "events"


class SegmentView(StrEnum):
    DETAIL = "detail"
    RANKING = "ranking"
    PREDICTED_BLOCK = "predicted_block"


class EdgeState(StrEnum):
    """An exposure-graph edge by the reported decision of its newest observation (blocked edges are
    not in the graph)."""
    ALLOWED = "allowed"
    POTENTIALLY_BLOCKED = "potentially_blocked"
    UNKNOWN = "unknown"


class TamperPattern(StrEnum):
    REGULAR_CYCLE = "regular_cycle"
    BURST = "burst"
    SPORADIC = "sporadic"
    TOO_FEW = "too_few"


class TamperAction(StrEnum):
    """What a signal-type tamper event did, from its kernel functions (spec §6.6 F4)."""
    ADD_RULE = "add_rule"
    DELETE_RULE = "delete_rule"
    ADD_CHAIN = "add_chain"
    DELETE_CHAIN = "delete_chain"
    ADD_TABLE = "add_table"
    DELETE_TABLE = "delete_table"


class PrecursorKind(StrEnum):
    TAMPER = "tamper"
    SUSPEND = "suspend"
    OFFLINE = "offline"


class RansomwareTrafficClass(StrEnum):
    """An unprotected high-risk service by its recent traffic (spec §6.5.6)."""
    PRIORITY = "priority"
    SAFE_TO_BLOCK = "safe_to_block"
    SUSPICIOUS = "suspicious"
    PROTECTED = "protected"
    UNKNOWN = "unknown"


class FocusKind(StrEnum):
    DETECTION = "detection"
    EXPOSURE_ASSET = "exposure_asset"
    PIVOT_HOST = "pivot_host"
    CROSS_ENV = "cross_env"
    TAMPER = "tamper"
    RANSOMWARE_PRIORITY = "ransomware_priority"
    VENDOR_CONTRADICTION = "vendor_contradiction"
    MODE_SWITCH_BLOCKER = "mode_switch_blocker"
    DATA_COVERAGE = "data_coverage"
    VISIBILITY = "visibility"
    COLLECTION_GAP = "collection_gap"
    SYSTEM_HEALTH = "system_health"
    SETUP_REQUIRED = "setup_required"
    STALE_SELECTOR = "stale_selector"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# The default management / lateral port set, as 5.x _LATERAL_PORTS (src/report/analysis/
# mod15_lateral_movement.py, 5.x f022272e), in the three classes of spec §6.5.8; settings add to and remove
# from it (spec §6.5.1).
LATERAL_PORTS_DEFAULT: tuple[tuple[int, str, PortClass], ...] = (
    (445, "SMB", PortClass.REMOTE), (135, "RPC", PortClass.REMOTE), (139, "NetBIOS", PortClass.REMOTE),
    (3389, "RDP", PortClass.REMOTE), (22, "SSH", PortClass.REMOTE), (5985, "WinRM-HTTP", PortClass.REMOTE),
    (5986, "WinRM-HTTPS", PortClass.REMOTE), (23, "Telnet", PortClass.REMOTE), (2049, "NFS", PortClass.REMOTE),
    (111, "RPC Portmapper", PortClass.REMOTE),
    # In the PCE's admin category too; here so a PCE that reports no ransomware-protection services counts them.
    (5900, "VNC", PortClass.REMOTE), (5938, "TeamViewer", PortClass.REMOTE),
    (88, "Kerberos", PortClass.DIRECTORY), (464, "Kerberos-PW", PortClass.DIRECTORY),
    (389, "LDAP", PortClass.DIRECTORY), (636, "LDAPS", PortClass.DIRECTORY), (3268, "LDAP-GC", PortClass.DIRECTORY),
    (3269, "LDAPS-GC", PortClass.DIRECTORY), (9389, "ADWS", PortClass.DIRECTORY),
    (1433, "MSSQL", PortClass.DATABASE), (3306, "MySQL", PortClass.DATABASE), (5432, "PostgreSQL", PortClass.DATABASE),
)
# Every built-in port is TCP; these services also run over UDP (Kerberos, kpasswd, CLDAP, RDP's UDP transport, NFS,
# the RPC portmapper, TeamViewer). Matching any protocol made a UDP reply that lands on an ephemeral port numbered
# 1433 or 5985 look like a management connection (2026-10-27, lab).
TCP, UDP = 6, 17
BUILTIN_UDP_PORTS: frozenset[int] = frozenset({88, 464, 389, 3389, 2049, 111, 5938})


def builtin_protocols(port: int) -> tuple[int, ...]:
    return (TCP, UDP) if port in BUILTIN_UDP_PORTS else (TCP,)


# The built-in directory ports and their protocols: the flow store counts each source's directory traffic per hour
# by them (it does not read settings).
DIRECTORY_PORTS: frozenset[tuple[int, int]] = frozenset(
    (p, proto) for p, _, c in LATERAL_PORTS_DEFAULT if c is PortClass.DIRECTORY for proto in builtin_protocols(p))

# Remote execution, reconnaissance and directory-attack tools whose connection to an internal host is worth
# a look (spec §6.5.8 D and E③), as normalize_process names them; settings replace the list.
DEFAULT_SUSPICIOUS_TOOLS: tuple[str, ...] = (
    "powershell.exe", "pwsh.exe", "wmic.exe", "psexec.exe", "psexesvc.exe", "paexec.exe", "winrs.exe",
    "certutil.exe", "mshta.exe", "rundll32.exe", "regsvr32.exe", "cscript.exe", "wscript.exe", "bitsadmin.exe",
    "rubeus.exe", "mimikatz.exe", "sharphound.exe", "adfind.exe", "nc", "ncat", "socat", "nmap", "masscan",
)

# REST API guide: flow_summary records allowed, blocked and potentially blocked connections;
# flow_drops only blocked and potentially blocked; flow_off nothing. Enhanced data collection
# adds byte counts on top of flow_summary. Anything else is unknown, never guessed.
_SEES_ALLOWED: dict[str, bool] = {
    VisibilityLevel.FLOW_SUMMARY: True,
    VisibilityLevel.ENHANCED_DATA_COLLECTION: True,
    VisibilityLevel.FLOW_DROPS: False,
    VisibilityLevel.FLOW_OFF: False,
}


def visibility_sees_allowed(level: str | None) -> bool | None:
    """Whether a VEN at this visibility level reports allowed traffic (None = unknown level)."""
    return _SEES_ALLOWED.get(level) if level is not None else None


# Draft policy decision is an OPEN domain: the PCE adds values (boundary and
# override-deny variants arrived after the base four), and neither the REST
# API guide nor the schema lists them all. Unknown values pass through
# unchanged so a PCE upgrade never makes data disappear. Known values: the
# four base decisions plus every variant observed in 5.x code paths.
KNOWN_DRAFT_POLICY_DECISIONS: frozenset[str] = frozenset({
    "allowed",
    "potentially_blocked",
    "blocked",
    "unknown",
    "blocked_by_boundary",
    "potentially_blocked_by_boundary",
    "blocked_by_override_deny",
    "potentially_blocked_by_override_deny",
    "allowed_across_boundary",
})


def parse_draft_policy_decision(raw: str) -> str:
    """Normalise case only; never reject a value the PCE sends."""
    return raw.strip().lower()


class ReportType(StrEnum):
    """Report types (spec §6.5 報表, §6.5.5); 5b and 5c add the 5.x types."""
    LATERAL_POSTURE = "lateral_posture"
    NEW_CONNECTIONS = "new_connections"
    UNMANAGED_ENDPOINTS = "unmanaged_endpoints"
    TRAFFIC = "traffic"
    SECURITY_RISK = "security_risk"
    NETWORK_INVENTORY = "network_inventory"
    APP_SUMMARY = "app_summary"
    VEN_STATUS = "ven_status"
    AUDIT = "audit"
    RANSOMWARE = "ransomware"
    READINESS = "readiness"
    POLICY_USAGE = "policy_usage"


class ReportFormat(StrEnum):
    HTML = "html"
    XLSX = "xlsx"


class ReportStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


_ENUMS: tuple[type[StrEnum], ...] = (
    PolicyDecision, RuleAction, AlertRuleType, DeploymentType, Language, ProbeName,
    FlowDirection, VisibilityLevel, TamperClassification, IngestSource, DataOrigin, CapabilityState,
    CollectionMode, Severity, DetectorKind, PortClass, DetectorState, SegmentDimension, SegmentMetric, SegmentView,
    EdgeState, TamperPattern, TamperAction, PrecursorKind, RansomwareTrafficClass, FocusKind, Confidence,
    ThresholdType, ChannelKind, SystemCheck, DeliveryStatus, ReportType, ReportFormat, ReportStatus,
)


def export_value_domains() -> dict[str, list[str]]:
    """Every value domain by class name, values sorted — the frontend's copy of this module."""
    out = {e.__name__: sorted(v.value for v in e) for e in _ENUMS}
    out["DraftPolicyDecision"] = sorted(KNOWN_DRAFT_POLICY_DECISIONS)
    return out
