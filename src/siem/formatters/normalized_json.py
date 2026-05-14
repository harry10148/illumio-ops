from __future__ import annotations

import orjson

from src.siem.formatters.base import Formatter
from src.siem.formatters.cef import (
    _PROTO_MAP,
    _extract_actor,
    _format_labels,
    _format_resource_changes,
    _proto_to_str,
)


def _omit_none(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None and v != ""}


class NormalizedJSONFormatter(Formatter):
    """Flat JSON using official Illumio field names.

    Handles both raw PCE API format (nested src/dst/service) and the flat
    official log format.  Output is a single JSON object with no nested
    keys — suitable for syslog_json and Splunk HEC auto-indexing.
    """

    def format_event(self, event: dict) -> str:
        action = event.get("action") or {}
        rc = event.get("resource_changes") or []

        out = {
            "timestamp":    event.get("timestamp", ""),
            "pce_fqdn":     event.get("pce_fqdn", ""),
            "event_type":   event.get("event_type", "unknown"),
            "severity":     event.get("severity", "info"),
            "status":       event.get("status", ""),
            "pce_event_id": (event.get("pce_event_id")
                             or event.get("uuid")
                             or event.get("href") or ""),
        }

        actor = _extract_actor(event.get("created_by") or {})
        if actor:
            out["suser"] = actor

        if action.get("src_ip"):
            out["src_ip"] = action["src_ip"]
        if action.get("api_method"):
            out["request_method"] = action["api_method"]
        if action.get("api_endpoint"):
            out["request"] = action["api_endpoint"]
        if action.get("http_status_code") is not None:
            out["http_status_code"] = action["http_status_code"]

        if rc:
            msg = _format_resource_changes(rc)
            if msg:
                out["resource_changes"] = msg

        return orjson.dumps(_omit_none(out)).decode("utf-8")

    def format_flow(self, flow: dict) -> str:
        svc    = flow.get("service") or {}
        src    = flow.get("src") or {}
        dst    = flow.get("dst") or {}
        src_wl = src.get("workload") or {}
        dst_wl = dst.get("workload") or {}

        src_ip = flow.get("src_ip") or src.get("ip", "")
        dst_ip = flow.get("dst_ip") or dst.get("ip", "")
        port   = flow.get("dst_port") or flow.get("port") or svc.get("port") or 0
        proto  = _proto_to_str(
            flow.get("proto") or flow.get("protocol") or svc.get("proto")
        )
        pd     = flow.get("pd") or flow.get("policy_decision") or "unknown"
        ts     = (flow.get("timestamp")
                  or flow.get("first_detected")
                  or (flow.get("timestamp_range") or {}).get("first_detected", ""))

        out: dict = {
            "timestamp": ts,
            "src_ip":    src_ip,
            "dst_ip":    dst_ip,
            "dst_port":  port,
            "proto":     proto,
            "pd":        pd,
        }

        # src workload
        src_hostname = (flow.get("src_hostname")
                        or src_wl.get("hostname") or src_wl.get("name") or "")
        if src_hostname:
            out["src_hostname"] = src_hostname
        src_href = flow.get("src_href") or src_wl.get("href") or ""
        if src_href:
            out["src_href"] = src_href
        src_labels = _format_labels(flow.get("src_labels") or src_wl.get("labels") or [])
        if src_labels:
            out["src_labels"] = src_labels

        # dst workload
        dst_hostname = (flow.get("dst_hostname")
                        or dst_wl.get("hostname") or dst_wl.get("name") or "")
        if dst_hostname:
            out["dst_hostname"] = dst_hostname
        dst_href = flow.get("dst_href") or dst_wl.get("href") or ""
        if dst_href:
            out["dst_href"] = dst_href
        dst_labels = _format_labels(flow.get("dst_labels") or dst_wl.get("labels") or [])
        if dst_labels:
            out["dst_labels"] = dst_labels

        fqdn = flow.get("fqdn") or dst.get("fqdn") or ""
        if fqdn:
            out["fqdn"] = fqdn

        pn = svc.get("process_name") or flow.get("pn") or ""
        if pn:
            out["pn"] = pn
        un = svc.get("user_name") or flow.get("un") or ""
        if un:
            out["un"] = un

        count = flow.get("count") or flow.get("num_connections") or flow.get("flow_count")
        if count is not None:
            out["count"] = count

        dst_dbi = flow.get("dst_dbi") or flow.get("dst_bi")
        dst_dbo = flow.get("dst_dbo") or flow.get("dst_bo")
        if dst_dbi is not None:
            out["dst_dbi"] = dst_dbi
        if dst_dbo is not None:
            out["dst_dbo"] = dst_dbo

        dst_tbi = flow.get("dst_tbi")
        dst_tbo = flow.get("dst_tbo")
        if dst_tbi is not None:
            out["dst_tbi"] = dst_tbi
        if dst_tbo is not None:
            out["dst_tbo"] = dst_tbo

        dir_raw = flow.get("dir") or flow.get("flow_direction") or ""
        if dir_raw:
            out["dir"] = "O" if dir_raw in ("O", "outbound") else "I"

        state = flow.get("state") or ""
        if state:
            out["state"] = state

        net = flow.get("network")
        net_name = (net if isinstance(net, str) else (net or {}).get("name") or "")
        if net_name:
            out["network"] = net_name

        cls = flow.get("class") or ""
        if cls:
            out["class"] = cls

        # ICMP
        icmp_type = flow.get("type") if flow.get("type") is not None else svc.get("icmp_type")
        icmp_code = flow.get("code") if flow.get("code") is not None else svc.get("icmp_code")
        if icmp_type is not None:
            out["type"] = icmp_type
        if icmp_code is not None:
            out["code"] = icmp_code

        for field in ("interval_sec", "ddms", "tdms", "pd_qualifier"):
            val = flow.get(field)
            if val is not None:
                out[field] = val

        pce_fqdn = flow.get("pce_fqdn") or ""
        if pce_fqdn:
            out["pce_fqdn"] = pce_fqdn

        return orjson.dumps(_omit_none(out)).decode("utf-8")
