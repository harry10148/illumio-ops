"""CEF that mirrors the PCE's own syslog export (`cef_pce`).

Evidence: tests/fixtures/pce_native_cef_pairs.json — real pairs joined on
event_href between the ops cache and pce.lab.local's syslog (PCE 26.2.20,
2026-09-11), plus a 3,000-line scan of the PCE stream in Graylog.  Every
rule below that the scan could not observe is marked ASSUMPTION.

Why a second CEF formatter instead of changing `cef`: the Signature ID
changes shape (event_type.status), severities change, and empty values
(`outcome=`) are emitted on purpose — any SOC rule written against the old
line would break, so the old line stays available.

Values are NOT CEF-escaped.  The PCE does not escape them either
(`suser=NT AUTHORITY\\SYSTEM` goes out verbatim) and cs2/cs4 carry JSON the
SOC must be able to parse as-is.  Only CR/LF are flattened, and `|` only in
the header.
"""
from __future__ import annotations

from datetime import datetime, timezone

import orjson

from src.siem.formatters.base import Formatter

# audit: info→1 / warning→3 / err→4 observed; the rest are ASSUMPTION
# (monotone fill between observed points, never observed on a real PCE).
_AUDIT_SEVERITY = {
    "debug": 0, "info": 1, "informational": 1, "notice": 2,
    "warning": 3, "warn": 3, "err": 4, "error": 4,
    "critical": 5, "crit": 5, "alert": 6, "emerg": 7, "emergency": 7,
}
# flows: allowed→1 / unknown→1 / potentially_blocked→3 observed;
# blocked→5 is ASSUMPTION (the LEEF export documents sev=5 for it).
_FLOW_SEVERITY = {"allowed": 1, "unknown": 1, "potentially_blocked": 3, "blocked": 5}
_FLOW_PD_NUMERIC = {0: "allowed", 1: "potentially_blocked", 2: "blocked"}
_PROTO = {6: "tcp", 17: "udp", 1: "icmp"}
_STATE = {"active": "A", "snapshot": "S", "closed": "C", "timed_out": "T", "new": "N"}  # new→N ASSUMPTION
_TRAFCLASS = {"unicast": "U", "broadcast": "B", "multicast": "M"}
# resource_changes is not sent unbounded.  Observed on PCE 26.2.20 (fixture
# pairs): cs2 carries the first 3,995 characters; the remainder is appended
# after cs1 as `cs3=<rest> cs3Label=resource_changes_2` (7,420-char case);
# when even two chunks cannot hold it (10,338-char case) every entry goes
# out without its `changes` key.  A third chunk was never observed —
# ASSUMPTION that the PCE stops at two.
_CS2_CHUNK = 3995


def _clean(value) -> str:
    return str(value).replace("\r", " ").replace("\n", " ")


def _header_field(value: str) -> str:
    return _clean(value).replace("|", "\\|")


def _title(sig: str) -> str:
    words = [w for w in sig.replace(".", " ").replace("_", " ").split() if w]
    return " ".join(w[:1].upper() + w[1:].lower() for w in words)


def _header(sig: str, name: str, sev: int, version: str) -> str:
    return f"CEF:0|Illumio|PCE|{_header_field(version)}|{_header_field(sig)}|{_header_field(name)}|{sev}|"


def _parse_ts(ts: str) -> datetime | None:
    if not ts:
        return None
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _rt_audit(ts: str) -> str:
    dt = _parse_ts(ts)
    if dt is None:
        return ""
    return dt.strftime("%b %d %Y %H:%M:%S.") + f"{dt.microsecond // 1000:03d} +0000"


def _rt_flow(ts: str) -> str:
    dt = _parse_ts(ts)
    return dt.strftime("%b %d %Y %H:%M:%S") if dt else ""


def _compact_json(obj) -> str:
    return orjson.dumps(obj).decode("utf-8")


def _resource_changes_chunks(rc) -> tuple[str, str]:
    """(cs2 value, cs3 continuation) following the PCE's own chunking."""
    text = _compact_json(rc)
    if len(text) > 2 * _CS2_CHUNK:
        slim = [{k: v for k, v in e.items() if k != "changes"} if isinstance(e, dict) else e for e in rc]
        text = _compact_json(slim)
    return text[:_CS2_CHUNK], text[_CS2_CHUNK:2 * _CS2_CHUNK]


def _href_tail(href) -> str:
    return str(href or "").rstrip("/").rsplit("/", 1)[-1]


def _actor(created_by) -> tuple[str, str]:
    """(duid, duser). duid == "" means omit the key."""
    cb = created_by if isinstance(created_by, dict) else {}
    if "system" in cb or not cb:
        return "", "system"
    if isinstance(cb.get("user"), dict):
        u = cb["user"]
        return _href_tail(u.get("href")), str(u.get("username") or u.get("name") or "")
    if isinstance(cb.get("agent"), dict):
        agent = cb["agent"]
        ven = cb.get("ven") if isinstance(cb.get("ven"), dict) else {}
        return _href_tail((ven or {}).get("href") or agent.get("href")), str(agent.get("hostname") or "")
    for key in ("container_cluster", "service_account"):
        if isinstance(cb.get(key), dict):
            return _href_tail(cb[key].get("href")), str(cb[key].get("name") or "")
    return "", "system"


def _first(*values):
    for v in values:
        if v is not None:
            return v
    return None


def _labels_obj(labels) -> dict:
    if isinstance(labels, dict):
        return {str(k): str(v) for k, v in labels.items() if k and v}
    out: dict = {}
    for lbl in labels or []:
        if isinstance(lbl, dict) and lbl.get("key") and lbl.get("value"):
            out[str(lbl["key"])] = str(lbl["value"])
    return out


class PceNativeCEFFormatter(Formatter):
    def __init__(self, *, pce_fqdn: str = "", pce_version: str = "unknown"):
        self._pce_fqdn = pce_fqdn
        self._pce_version = pce_version or "unknown"

    # ── audit events ────────────────────────────────────────────────────
    def format_event(self, event: dict) -> str:
        event_type = str(event.get("event_type") or "unknown")
        status = event.get("status")
        sig = f"{event_type}.{status}" if status else event_type
        sev = _AUDIT_SEVERITY.get(str(event.get("severity") or "info").lower(), 1)
        head = _header(sig, _title(sig), sev, self._pce_version)

        dvchost = str(event.get("pce_fqdn") or self._pce_fqdn)
        action = event.get("action") if isinstance(event.get("action"), dict) else None
        src_ip = (action or {}).get("src_ip")
        dst = src_ip if src_ip and src_ip != "FILTERED" else dvchost
        duid, duser = _actor(event.get("created_by"))

        ext: list[str] = []
        rt = _rt_audit(str(event.get("timestamp") or ""))
        if rt:
            ext.append(f"rt={rt}")
        ext.append(f"dvchost={_clean(dvchost)}")
        if duid:
            ext.append(f"duid={_clean(duid)}")
        ext.append(f"duser={_clean(duser)}")
        ext.append(f"dst={_clean(dst)}")
        ext.append(f"outcome={_clean(status or '')}")
        ext.append("cat=audit_events")
        if action is not None:
            if action.get("api_endpoint") is not None:
                ext.append(f"request={_clean(action['api_endpoint'])}")
            if action.get("api_method") is not None:
                ext.append(f"requestMethod={_clean(action['api_method'])}")
            if action.get("http_status_code") is not None:
                ext.append(f"reason={_clean(action['http_status_code'])}")
        rc = event.get("resource_changes") or []
        cs2, cs3 = _resource_changes_chunks(rc) if rc else ("", "")
        ext.append(f"cs2={_clean(cs2)}")
        ext.append("cs2Label=resource_changes")
        notes = event.get("notifications") or []
        ext.append(f"cs4={_clean(_compact_json(notes)) if notes else ''}")
        ext.append("cs4Label=notifications")
        ext.append("cn2=2")
        ext.append("cn2Label=schema-version")
        ext.append("cs1Label=event_href")
        ext.append(f"cs1={_clean(event.get('href') or event.get('pce_event_id') or '')}")
        if cs3:
            ext.append(f"cs3={_clean(cs3)}")
            ext.append("cs3Label=resource_changes_2")
        return head + " ".join(ext)

    def format_flow(self, flow: dict) -> str:
        svc = flow.get("service") if isinstance(flow.get("service"), dict) else {}
        src = flow.get("src") if isinstance(flow.get("src"), dict) else {}
        dst = flow.get("dst") if isinstance(flow.get("dst"), dict) else {}
        src_wl = src.get("workload") if isinstance(src.get("workload"), dict) else None
        dst_wl = dst.get("workload") if isinstance(dst.get("workload"), dict) else None

        pd_raw = _first(flow.get("pd"), flow.get("policy_decision"))
        if isinstance(pd_raw, bool):
            pd_raw = None
        if isinstance(pd_raw, int):
            pd = _FLOW_PD_NUMERIC.get(pd_raw, "unknown")
        else:
            pd = str(pd_raw or "unknown")
            if pd not in _FLOW_SEVERITY:
                pd = "unknown"
        head = _header(f"flow_{pd}", _title(f"flow_{pd}"), _FLOW_SEVERITY[pd], self._pce_version)

        dir_raw = str(_first(flow.get("flow_direction"), flow.get("dir")) or "")
        outbound = dir_raw in ("outbound", "O")
        proto_raw = _first(flow.get("proto"), flow.get("protocol"), svc.get("proto"))
        proto = proto_raw if isinstance(proto_raw, str) else _PROTO.get(int(proto_raw), str(proto_raw)) if proto_raw is not None else ""
        port = _first(flow.get("dst_port"), flow.get("port"), svc.get("port"), 0)
        ts = _first(flow.get("timestamp"), flow.get("last_detected"),
                    (flow.get("timestamp_range") or {}).get("last_detected"), "")

        ext: list[str] = [f"act={pd}", "cat=flow_summary", f"deviceDirection={1 if outbound else 0}",
                          f"dpt={port}", f"src={_clean(_first(flow.get('src_ip'), src.get('ip'), ''))}",
                          f"dst={_clean(_first(flow.get('dst_ip'), dst.get('ip'), ''))}", f"proto={_clean(proto)}"]
        cnt = _first(flow.get("count"), flow.get("num_connections"), flow.get("flow_count"))
        if cnt is not None:
            ext.append(f"cnt={cnt}")
        tbi, tbo = flow.get("dst_tbi"), flow.get("dst_tbo")
        if tbi is not None and tbo is not None:
            ext.append(f"in={tbi}")
            ext.append(f"out={tbo}")
        rt = _rt_flow(str(ts or ""))
        if rt:
            ext.append(f"rt={rt}")
        user = _first(svc.get("user_name"), flow.get("un"))
        proc = _first(svc.get("process_name"), flow.get("pn"))
        svc_name = _first(svc.get("name"), flow.get("service_name"))
        if user:
            ext.append(f"{'suser' if outbound else 'duser'}={_clean(user)}")
        if svc_name:
            ext.append(f"destinationServiceName={_clean(svc_name)}")
        if proc:
            ext.append(f"{'sproc' if outbound else 'dproc'}={_clean(proc)}")
        if flow.get("interval_sec") is not None:
            ext.append(f"cn1={flow['interval_sec']}")
            ext.append("cn1Label=interval_sec")
        dbi = _first(flow.get("dst_dbi"), flow.get("dst_bi"))
        dbo = _first(flow.get("dst_dbo"), flow.get("dst_bo"))
        if dbi is not None and dbo is not None:
            ext += [f"cn2={dbi}", "cn2Label=dbi", f"cn3={dbo}", "cn3Label=dbo"]
        state = str(flow.get("state") or "")
        ext.append(f"cs2={_STATE.get(state, state if len(state) == 1 else '')}")
        ext.append("cs2Label=state")
        if src_wl is not None:
            ext.append(f"shost={_clean(_first(flow.get('src_hostname'), src_wl.get('hostname'), src_wl.get('name'), ''))}")
            ext.append(f"cs5={_clean(_first(flow.get('src_href'), src_wl.get('href'), ''))}")
            ext.append("cs5Label=src_href")
            labels = _labels_obj(_first(flow.get("src_labels"), src_wl.get("labels")))
            if labels:
                ext.append(f"cs3={_clean(_compact_json(labels))}")
                ext.append("cs3Label=src_labels")
        if dst_wl is not None:
            ext.append(f"dhost={_clean(_first(flow.get('dst_hostname'), dst_wl.get('hostname'), dst_wl.get('name'), ''))}")
            ext.append(f"cs6={_clean(_first(flow.get('dst_href'), dst_wl.get('href'), ''))}")
            ext.append("cs6Label=dst_href")
            labels = _labels_obj(_first(flow.get("dst_labels"), dst_wl.get("labels")))
            if labels:
                ext.append(f"cs4={_clean(_compact_json(labels))}")
                ext.append("cs4Label=dst_labels")
        ext.append(f"dvchost={_clean(flow.get('pce_fqdn') or self._pce_fqdn)}")

        msg: dict = {}
        if flow.get("icmp_type") is not None or flow.get("type") is not None:
            msg["icmp_type"] = _first(flow.get("icmp_type"), flow.get("type"), svc.get("icmp_type"))
            msg["icmp_code"] = _first(flow.get("icmp_code"), flow.get("code"), svc.get("icmp_code"))
        cls = flow.get("class") or _TRAFCLASS.get(str(flow.get("transmission") or "").lower(), "U")
        msg["trafclass_code"] = cls
        for k in ("ddms", "tdms"):
            if flow.get(k) is not None:
                msg[k] = flow[k]
        net = flow.get("network")
        net_name = net if isinstance(net, str) else (net or {}).get("name")
        if net_name:
            msg["network"] = net_name
        if flow.get("pd_qualifier") is not None:
            msg["pd_qualifier"] = flow["pd_qualifier"]
        ext.append(f"msg={_clean(_compact_json(msg))}")
        return head + " ".join(ext)
