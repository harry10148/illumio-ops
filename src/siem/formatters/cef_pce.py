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

    def format_flow(self, flow: dict) -> str:  # Task 2
        raise NotImplementedError
