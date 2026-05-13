from __future__ import annotations

import re
from datetime import datetime, timezone

from src.siem.formatters.base import Formatter

_SEVERITY_MAP = {
    "info": 3,
    "warning": 6,
    "warn": 6,
    "error": 8,
    "err": 8,
    "critical": 10,
    "crit": 10,
}
_PCE_VERSION = "3.11"

_PROTO_MAP = {6: "tcp", 17: "udp", 1: "icmp"}


def _proto_to_str(proto) -> str:
    if proto is None:
        return ""
    if isinstance(proto, str):
        return proto
    return _PROTO_MAP.get(int(proto), str(proto))


def _cef_escape(value: str) -> str:
    """Escape CEF extension field values: backslash, pipe, equals, newline."""
    value = value.replace("\\", "\\\\")
    value = value.replace("|", "\\|")
    value = value.replace("=", "\\=")
    value = value.replace("\n", "\\n")
    value = value.replace("\r", "\\r")
    return value


def _ts_to_epoch_ms(ts_str: str) -> int:
    if ts_str.endswith("Z"):
        ts_str = ts_str[:-1] + "+00:00"
    dt = datetime.fromisoformat(ts_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


class CEFFormatter(Formatter):
    def format_event(self, event: dict) -> str:
        sev_str = str(event.get("severity", "info")).lower()
        sev_num = _SEVERITY_MAP.get(sev_str, 3)
        event_type = _cef_escape(str(event.get("event_type", "unknown")))

        header = (
            f"CEF:0|Illumio|PCE|{_PCE_VERSION}"
            f"|{event_type}|{event_type}|{sev_num}"
        )

        ts = event.get("timestamp", "")
        ext_parts = []
        if ts:
            ext_parts.append(f"rt={_ts_to_epoch_ms(ts)}")
        ext_parts.append(f"dvchost={_cef_escape(str(event.get('pce_fqdn', '')))}")
        ext_parts.append(f"externalId={_cef_escape(str(event.get('pce_event_id', '')))}")
        ext_parts.append(f"outcome={_cef_escape(str(event.get('status', '')))}")

        return header + "|" + " ".join(ext_parts)

    def format_flow(self, flow: dict) -> str:
        # Support both flat (normalized) and nested (raw PCE API) forms
        svc    = flow.get("service") or {}
        src    = flow.get("src") or {}
        dst    = flow.get("dst") or {}
        src_wl = src.get("workload") or {}
        dst_wl = dst.get("workload") or {}

        src_ip = flow.get("src_ip") or src.get("ip", "")
        dst_ip = flow.get("dst_ip") or dst.get("ip", "")
        port   = flow.get("port") or svc.get("port") or 0
        proto  = _proto_to_str(flow.get("protocol") or svc.get("proto"))
        action = flow.get("action") or flow.get("policy_decision") or "unknown"
        ts     = (flow.get("first_detected")
                  or (flow.get("timestamp_range") or {}).get("first_detected", ""))

        header = f"CEF:0|Illumio|PCE|{_PCE_VERSION}|traffic.flow|traffic.flow|3"
        ext = []

        # ── Timing ──────────────────────────────────────────────────────────
        if ts:
            ext.append(f"rt={_ts_to_epoch_ms(ts)}")

        # ── Network 5-tuple ─────────────────────────────────────────────────
        ext.append(f"src={_cef_escape(str(src_ip))}")
        ext.append(f"dst={_cef_escape(str(dst_ip))}")
        ext.append(f"dpt={port}")
        ext.append(f"proto={_cef_escape(proto)}")

        # ICMP type/code (service.icmp_type / icmp_code or top-level)
        icmp_type = svc.get("icmp_type") if svc else flow.get("type")
        icmp_code = svc.get("icmp_code") if svc else flow.get("code")
        if icmp_type is not None:
            ext.append(f"icmpType={icmp_type}")
        if icmp_code is not None:
            ext.append(f"icmpCode={icmp_code}")

        # ── Policy decision (pd) ─────────────────────────────────────────────
        ext.append(f"act={_cef_escape(str(action))}")

        # ── Source workload (src_hostname, src_labels) ───────────────────────
        src_host = (flow.get("src_hostname")
                    or src_wl.get("hostname") or src_wl.get("name") or "")
        if src_host:
            ext.append(f"shost={_cef_escape(src_host)}")

        src_labels = _format_labels(
            flow.get("src_labels") or src_wl.get("labels") or [])
        if src_labels:
            ext.append(f"cs1Label=srcLabels cs1={_cef_escape(src_labels)}")

        # ── Destination workload (dst_hostname, dst_labels, fqdn) ────────────
        dst_host = (flow.get("dst_hostname")
                    or dst_wl.get("hostname") or dst_wl.get("name") or "")
        if dst_host:
            ext.append(f"dhost={_cef_escape(dst_host)}")

        dst_fqdn = flow.get("fqdn") or dst.get("fqdn") or ""
        if dst_fqdn:
            ext.append(f"destinationDnsDomain={_cef_escape(dst_fqdn)}")

        dst_labels = _format_labels(
            flow.get("dst_labels") or dst_wl.get("labels") or [])
        if dst_labels:
            ext.append(f"cs2Label=dstLabels cs2={_cef_escape(dst_labels)}")

        # ── Process & user (pn / un) ─────────────────────────────────────────
        proc = svc.get("process_name") or flow.get("pn") or ""
        if proc:
            ext.append(f"cs3Label=process cs3={_cef_escape(proc)}")

        user = svc.get("user_name") or flow.get("un") or ""
        if user:
            ext.append(f"suser={_cef_escape(user)}")

        # ── Traffic counters (count / bytes) ─────────────────────────────────
        cnt = flow.get("num_connections") or flow.get("count") or flow.get("flow_count")
        if cnt is not None:
            ext.append(f"cnt={cnt}")

        bytes_in  = flow.get("dst_dbi") or flow.get("dst_bi")
        bytes_out = flow.get("dst_dbo") or flow.get("dst_bo")
        if bytes_in is not None:
            ext.append(f"in={bytes_in}")
        if bytes_out is not None:
            ext.append(f"out={bytes_out}")

        # ── Flow direction (dir): I=inbound(0) O=outbound(1) ─────────────────
        dir_raw = flow.get("dir") or flow.get("flow_direction") or ""
        if dir_raw:
            ext.append(f"deviceDirection={'1' if dir_raw in ('O', 'outbound') else '0'}")

        # ── Connection state (state: A/C/T/S/N or active/closed…) ────────────
        state = flow.get("state") or ""
        if state:
            ext.append(f"cs4Label=state cs4={_cef_escape(state)}")

        # ── Network profile ──────────────────────────────────────────────────
        net_name = (flow.get("network")
                    if isinstance(flow.get("network"), str)
                    else (flow.get("network") or {}).get("name") or "")
        if net_name:
            ext.append(f"cs5Label=network cs5={_cef_escape(net_name)}")

        # ── PCE host ─────────────────────────────────────────────────────────
        pce_fqdn = flow.get("pce_fqdn") or ""
        if pce_fqdn:
            ext.append(f"dvchost={_cef_escape(pce_fqdn)}")

        return header + "|" + " ".join(ext)


def _format_labels(labels) -> str:
    """Format PCE label list [{"key":k,"value":v}] or dict {k:v} as 'k:v k:v'."""
    if isinstance(labels, dict):
        return " ".join(f"{k}:{v}" for k, v in labels.items() if k and v)
    parts = []
    for lbl in labels:
        k = lbl.get("key", "")
        v = lbl.get("value", "")
        if k and v:
            parts.append(f"{k}:{v}")
    return " ".join(parts)
