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
        """Format a PCE traffic flow as CEF.

        Accepts both raw PCE API format (nested src/dst/service) and
        the flat official log format. CEF standard fields carry the
        network 5-tuple; all other keys use the official Illumio field
        names so existing SIEM parsers work without remapping.
        """
        svc    = flow.get("service") or {}
        src    = flow.get("src") or {}
        dst    = flow.get("dst") or {}
        src_wl = src.get("workload") or {}
        dst_wl = dst.get("workload") or {}

        # ── Normalise from raw PCE API or flat form ──────────────────────────
        src_ip = flow.get("src_ip") or src.get("ip", "")
        dst_ip = flow.get("dst_ip") or dst.get("ip", "")
        port   = flow.get("dst_port") or flow.get("port") or svc.get("port") or 0
        proto_raw = flow.get("proto") or flow.get("protocol") or svc.get("proto")
        proto  = _proto_to_str(proto_raw)
        pd     = flow.get("pd") or flow.get("policy_decision") or "unknown"
        ts     = (flow.get("timestamp")
                  or flow.get("first_detected")
                  or (flow.get("timestamp_range") or {}).get("first_detected", ""))

        header = f"CEF:0|Illumio|PCE|{_PCE_VERSION}|traffic.flow|traffic.flow|3"
        ext = []

        # ── CEF standard: timing + network 5-tuple ───────────────────────────
        if ts:
            ext.append(f"rt={_ts_to_epoch_ms(ts)}")
        ext.append(f"src={_cef_escape(str(src_ip))}")
        ext.append(f"dst={_cef_escape(str(dst_ip))}")
        ext.append(f"dpt={port}")
        ext.append(f"proto={_cef_escape(proto)}")

        # ── Illumio original field names ─────────────────────────────────────

        # pd: policy decision
        ext.append(f"pd={_cef_escape(str(pd))}")

        # src workload
        src_hostname = (flow.get("src_hostname")
                        or src_wl.get("hostname") or src_wl.get("name") or "")
        if src_hostname:
            ext.append(f"src_hostname={_cef_escape(src_hostname)}")
        src_href = flow.get("src_href") or src_wl.get("href") or ""
        if src_href:
            ext.append(f"src_href={_cef_escape(src_href)}")
        src_labels = _format_labels(flow.get("src_labels") or src_wl.get("labels") or [])
        if src_labels:
            ext.append(f"src_labels={_cef_escape(src_labels)}")

        # dst workload
        dst_hostname = (flow.get("dst_hostname")
                        or dst_wl.get("hostname") or dst_wl.get("name") or "")
        if dst_hostname:
            ext.append(f"dst_hostname={_cef_escape(dst_hostname)}")
        dst_href = flow.get("dst_href") or dst_wl.get("href") or ""
        if dst_href:
            ext.append(f"dst_href={_cef_escape(dst_href)}")
        dst_labels = _format_labels(flow.get("dst_labels") or dst_wl.get("labels") or [])
        if dst_labels:
            ext.append(f"dst_labels={_cef_escape(dst_labels)}")

        # fqdn (destination)
        fqdn = flow.get("fqdn") or dst.get("fqdn") or ""
        if fqdn:
            ext.append(f"fqdn={_cef_escape(fqdn)}")

        # pn (process name), un (user name)
        pn = svc.get("process_name") or flow.get("pn") or ""
        if pn:
            ext.append(f"pn={_cef_escape(pn)}")
        un = svc.get("user_name") or flow.get("un") or ""
        if un:
            ext.append(f"un={_cef_escape(un)}")

        # count, bytes
        count = flow.get("count") or flow.get("num_connections") or flow.get("flow_count")
        if count is not None:
            ext.append(f"count={count}")
        dst_dbi = flow.get("dst_dbi") or flow.get("dst_bi")
        dst_dbo = flow.get("dst_dbo") or flow.get("dst_bo")
        if dst_dbi is not None:
            ext.append(f"dst_dbi={dst_dbi}")
        if dst_dbo is not None:
            ext.append(f"dst_dbo={dst_dbo}")

        # dir: I=inbound O=outbound
        dir_raw = flow.get("dir") or flow.get("flow_direction") or ""
        if dir_raw:
            dir_val = "O" if dir_raw in ("O", "outbound") else "I"
            ext.append(f"dir={dir_val}")

        # state
        state = flow.get("state") or ""
        if state:
            ext.append(f"state={_cef_escape(state)}")

        # network profile
        net_name = (flow.get("network")
                    if isinstance(flow.get("network"), str)
                    else (flow.get("network") or {}).get("name") or "")
        if net_name:
            ext.append(f"network={_cef_escape(net_name)}")

        # ICMP
        icmp_type = flow.get("type") if flow.get("type") is not None else svc.get("icmp_type")
        icmp_code = flow.get("code") if flow.get("code") is not None else svc.get("icmp_code")
        if icmp_type is not None:
            ext.append(f"type={icmp_type}")
        if icmp_code is not None:
            ext.append(f"code={icmp_code}")

        # class: transmission type U=Unicast M=Multicast B=Broadcast
        cls = flow.get("class") or ""
        if cls:
            ext.append(f"class={_cef_escape(cls)}")

        # dst_tbi / dst_tbo: total bytes (separate from delta)
        dst_tbi = flow.get("dst_tbi")
        dst_tbo = flow.get("dst_tbo")
        if dst_tbi is not None:
            ext.append(f"dst_tbi={dst_tbi}")
        if dst_tbo is not None:
            ext.append(f"dst_tbo={dst_tbo}")

        # interval_sec: sampling interval
        interval_sec = flow.get("interval_sec")
        if interval_sec is not None:
            ext.append(f"interval_sec={interval_sec}")

        # ddms / tdms: delta and total flow duration in ms
        ddms = flow.get("ddms")
        tdms = flow.get("tdms")
        if ddms is not None:
            ext.append(f"ddms={ddms}")
        if tdms is not None:
            ext.append(f"tdms={tdms}")

        # pd_qualifier: policy decision qualifier (0-3)
        pd_q = flow.get("pd_qualifier")
        if pd_q is not None:
            ext.append(f"pd_qualifier={pd_q}")

        # pce_fqdn
        pce_fqdn = flow.get("pce_fqdn") or ""
        if pce_fqdn:
            ext.append(f"pce_fqdn={_cef_escape(pce_fqdn)}")

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
