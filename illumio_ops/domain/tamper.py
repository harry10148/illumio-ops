"""Tamper investigation (spec §6.5.4): what a tamper event says, how a host's events are spaced, what happened
around the first one, and what to run on the host. Pure; the service reads events and annotations.

Lab facts (spec §6.6 F4, P3 Task 0): confirmed events carry no process; signal events list process, PID and
kernel functions (comma-joined strings, e.g. "nfnetlink_rcv_batch,nf_tables_deltable"). Four lab hosts cycle
at a median of 10.1 minutes with quartiles within a minute of it: another firewall manager fighting the VEN
over its table (dev.lab.local was NetBird, 2026-10-02).
"""
from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise
from typing import Any, Literal

from illumio_ops.domain.flows import parse_time
from illumio_ops.domain.values import TamperAction, TamperPattern

_KERNEL_ACTIONS: Mapping[str, TamperAction] = {
    "nf_tables_newrule": TamperAction.ADD_RULE, "nf_tables_delrule": TamperAction.DELETE_RULE,
    "nf_tables_newchain": TamperAction.ADD_CHAIN, "nf_tables_delchain": TamperAction.DELETE_CHAIN,
    "nf_tables_newtable": TamperAction.ADD_TABLE, "nf_tables_deltable": TamperAction.DELETE_TABLE,
}
_IGNORED_KERNEL = frozenset({"nfnetlink_rcv_batch"})  # the batch wrapper around the real call

TAMPER_ACTION_KEYS: Mapping[TamperAction, str] = {
    TamperAction.ADD_RULE: "tamper_action_add_rule", TamperAction.DELETE_RULE: "tamper_action_delete_rule",
    TamperAction.ADD_CHAIN: "tamper_action_add_chain", TamperAction.DELETE_CHAIN: "tamper_action_delete_chain",
    TamperAction.ADD_TABLE: "tamper_action_add_table", TamperAction.DELETE_TABLE: "tamper_action_delete_table",
}


@dataclass(frozen=True)
class TamperReading:
    at: datetime
    classification: str | None
    process: str | None
    pid: int | None
    actions: tuple[TamperAction | str, ...]  # an unknown kernel function is kept as it came
    tamper_type: str | None
    num_events: int | None
    revert_succeeded: bool | None
    has_process_info: bool  # confirmed-type events never carry the process: the page says so


def _actions(kernel_functions: Any) -> tuple[TamperAction | str, ...]:
    out: list[TamperAction | str] = []
    for entry in kernel_functions or ():
        for name in str(entry).split(","):
            name = name.strip()
            if name and name not in _IGNORED_KERNEL:
                out.append(_KERNEL_ACTIONS.get(name, name))
    return tuple(out)


def interpret(raw: Mapping[str, Any]) -> list[TamperReading]:
    """One reading per signal-type sub-event, or one for a confirmed-type event."""
    at = parse_time(raw.get("timestamp"))
    notes = raw.get("notifications") or []
    info = (notes[0].get("info") or {}) if notes and isinstance(notes[0], Mapping) else {}
    classification = info.get("event_classification")
    events = [e for e in info.get("events") or () if isinstance(e, Mapping)]
    if events:
        return [TamperReading(
            at=parse_time(e["timestamp"]) if e.get("timestamp") else at, classification=classification,
            process=e.get("process_name"), pid=e.get("process_id"), actions=_actions(e.get("kernel_functions")),
            tamper_type=e.get("tamper_type"), num_events=None, revert_succeeded=None,
            has_process_info=bool(e.get("process_name"))) for e in events]
    return [TamperReading(at=at, classification=classification, process=None, pid=None, actions=(), tamper_type=None,
                          num_events=info.get("num_events"), revert_succeeded=info.get("tampering_revert_succeeded"),
                          has_process_info=False)]


@dataclass(frozen=True)
class PatternResult:
    kind: TamperPattern
    n: int
    median_minutes: float | None
    q1: float | None
    q3: float | None


REGULAR_MIN_EVENTS = 6
REGULAR_SPREAD = 0.25   # the interquartile range at most this share of the median interval
BURST_MEDIAN_MINUTES = 2.0


def classify(times: Sequence[datetime]) -> PatternResult:
    """By the gaps between a host's events: a regular cycle (n >= 6, quartiles within a quarter of the
    median), a burst (median gap <= 2 minutes: a person or a script), else sporadic; fewer than 3 events
    are too few to tell. Calibrated on lab's 60 days (P3 plan Task 0)."""
    ordered = sorted(times)
    gaps = [(b - a) / timedelta(minutes=1) for a, b in pairwise(ordered)]
    if len(ordered) < 3:
        median = statistics.median(gaps) if gaps else None
        return PatternResult(TamperPattern.TOO_FEW, len(ordered), median, None, None)
    median = statistics.median(gaps)
    q1, _, q3 = statistics.quantiles(gaps, n=4) if len(gaps) >= 2 else (median, median, median)
    if len(ordered) >= REGULAR_MIN_EVENTS and (q3 - q1) <= REGULAR_SPREAD * median:
        kind = TamperPattern.REGULAR_CYCLE
    elif median <= BURST_MEDIAN_MINUTES:
        kind = TamperPattern.BURST
    else:
        kind = TamperPattern.SPORADIC
    return PatternResult(kind, len(ordered), median, q1, q3)


# Host-scoped: changes to the host or its VEN; org-scoped: policy provisions (spec §6.5.4 step 3).
HOST_TIMELINE_TYPES = ("workload.update", "workloads.update", "agent.request_policy",
                       "agent.upload_existing_ip_table_rules", "agent.goodbye", "agent.suspend", "agent.unsuspend",
                       "workload.online", "system_task.agent_offline_check", "agent.update")
ORG_TIMELINE_TYPES = ("sec_policy.create", "firewall_settings.update")
TIMELINE_EVENT_TYPES = HOST_TIMELINE_TYPES + ORG_TIMELINE_TYPES


@dataclass(frozen=True)
class TimelineEvent:
    at: datetime
    event_type: str
    summary: str


def timeline(events: Sequence[TimelineEvent], first_at: datetime, *, before: timedelta = timedelta(hours=24),
             after: timedelta = timedelta(hours=24)) -> list[TimelineEvent]:
    """The events of the listed types around the host's first tamper event, oldest first."""
    return sorted((e for e in events if e.event_type in TIMELINE_EVENT_TYPES
                   and first_at - before <= e.at <= first_at + after), key=lambda e: e.at)


@dataclass(frozen=True)
class Command:
    platform: Literal["linux_nftables", "linux_iptables_legacy", "windows"]
    purpose_key: str
    text: str


GUIDANCE_KEYS: Mapping[str, str] = {
    "nft_ruleset": "tamper_cmd_nft_ruleset", "nft_monitor": "tamper_cmd_nft_monitor",
    "nft_writer": "tamper_cmd_nft_writer", "ven_evidence": "tamper_cmd_ven_evidence",
    "audit_rule": "tamper_cmd_audit_rule", "audit_search": "tamper_cmd_audit_search",
    "win_platform_log": "tamper_cmd_win_platform_log",
}
# One-line commands to paste on the host (dev.lab.local, 2026-10-02; the VEN keeps the latest tampered rules
# under its data directory). Windows: the documentation names the VEN data directory, not where platform.log
# sits inside it, so the command finds it rather than assuming a path (P3 Task 12 ruling).
_LINUX = (
    Command("linux_nftables", GUIDANCE_KEYS["nft_ruleset"], "nft -s list ruleset"),
    Command("linux_nftables", GUIDANCE_KEYS["nft_monitor"],
            "nft monitor ruleset | while read -r l; do printf '%s %s\\n' \"$(date -Is)\" \"$l\"; done"),
    Command("linux_nftables", GUIDANCE_KEYS["nft_writer"],
            "bpftrace -e 'kprobe:nf_tables_newrule { printf(\"%s pid=%d comm=%s\\n\", strftime(\"%H:%M:%S\", nsecs), "
            "pid, comm); }'"),
    Command("linux_nftables", GUIDANCE_KEYS["ven_evidence"], "ls -l /opt/illumio_ven_data/etc/firewall/workload/*/tampered/"),
    Command("linux_iptables_legacy", GUIDANCE_KEYS["audit_rule"],
            "auditctl -a always,exit -F arch=b64 -S setsockopt -F a2=64 -k ilo_tamper"),
    Command("linux_iptables_legacy", GUIDANCE_KEYS["audit_search"], "ausearch -k ilo_tamper -i"),
)
_WINDOWS = (
    Command("windows", GUIDANCE_KEYS["win_platform_log"],
            "Get-ChildItem -Path C:\\ProgramData\\Illumio -Recurse -Filter platform.log | Select-Object FullName, LastWriteTime"),
)


def guidance(os_id: str | None) -> tuple[Command, ...]:
    return _WINDOWS if (os_id or "").lower().startswith("win") else _LINUX


@dataclass(frozen=True)
class Annotation:
    """An operator's "known cause" for a host's or a pattern's tampering (spec §6.5.4 step 5)."""
    id: int
    host_href: str | None
    pattern: TamperPattern | None
    process: str | None
    reason: str


def explained_by(reading: TamperReading, host_href: str, pattern: TamperPattern,
                 annotations: Sequence[Annotation]) -> int | None:
    """The first annotation whose every field that is set matches."""
    for a in annotations:
        if ((a.host_href is None or a.host_href == host_href) and (a.pattern is None or a.pattern is pattern)
                and (a.process is None or a.process == reading.process)):
            return a.id
    return None
