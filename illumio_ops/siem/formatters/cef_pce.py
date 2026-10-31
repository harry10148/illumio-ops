"""CEF that mirrors the PCE's own syslog export (`cef_pce`).

Evidence: tests_v6/siem/fixtures/pce_native_cef_pairs.json — real pairs joined on
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

import json
import re
from datetime import UTC, datetime
from typing import Any

from illumio_ops.siem.formatters.base import Formatter
from illumio_ops.siem.formatters.ops import ops_cef
from illumio_ops.siem.records import SiemRecord

# audit: info→1 / warning→3 / err→4 observed; the rest are ASSUMPTION
# (monotone fill between observed points, never observed on a real PCE).
_AUDIT_SEVERITY = {
    "debug": 0, "info": 1, "informational": 1, "notice": 2,
    "warning": 3, "warn": 3, "err": 4, "error": 4,
    "critical": 5, "crit": 5, "alert": 6, "emerg": 7, "emergency": 7,
}
_PROTO = {6: "tcp", 17: "udp", 1: "icmp"}
# resource_changes is not sent unbounded.  Observed on PCE 26.2.20 (fixture
# pairs): cs2 carries the first 3,995 characters; the remainder is appended
# after cs1 as `cs3=<rest> cs3Label=resource_changes_2` (7,420-char case);
# when even two chunks cannot hold it (10,338-char case) every entry goes
# out without its `changes` key.  A third chunk was never observed —
# ASSUMPTION that the PCE stops at two.
_CS2_CHUNK = 3995


_KEY_LIKE = re.compile(r"(\s[A-Za-z0-9_]+)=")


def _clean(value: object) -> str:
    return str(value).replace("\r", " ").replace("\n", " ")


def _clean_value(value: object) -> str:
    """An extension value in the graylog dialect: unescaped like the PCE's own line, except an '=' after a space and
    a word, which a CEF parser reads as the start of another key — a label or description could otherwise forge
    `act=blocked` (P7 security review). The PCE does not do this; its lines are not parsed as CEF on arrival."""
    return _KEY_LIKE.sub(r"\1\\=", _clean(value))


def _escape_arcsight(value: object) -> str:
    """CEF extension-value escaping per the ArcSight spec: backslash, equals,
    and line breaks.  ArcSight unescapes on parse, so cs2/cs4 JSON comes out
    clean on the other side."""
    value = str(value).replace("\\", "\\\\").replace("=", "\\=")
    return value.replace("\r", "\\r").replace("\n", "\\n")


def _rt_epoch_ms(ts: str) -> str:
    dt = _parse_ts(ts)
    return str(int(dt.timestamp() * 1000)) if dt else ""


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
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _rt_audit(ts: str) -> str:
    """PCE writes `Sep 11 2026 09:05:05.941 +0000`.  We drop the ` +0000`:
    Graylog's CEF codec (7.1, verified 2026-09-12 by sending both forms to
    the illumio-ops input) silently discards the whole line when rt carries
    a zone suffix, while the millisecond form parses to the right instant.
    The PCE never hits this because its lines arrive through a syslog input
    that does not parse CEF at all.  Value is UTC either way."""
    dt = _parse_ts(ts)
    if dt is None:
        return ""
    return dt.strftime("%b %d %Y %H:%M:%S.") + f"{dt.microsecond // 1000:03d}"


def _compact_json(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _resource_changes_chunks(rc: list[Any]) -> tuple[str, str]:
    """(cs2 value, cs3 continuation) following the PCE's own chunking."""
    text = _compact_json(rc)
    if len(text) > 2 * _CS2_CHUNK:
        slim = [{k: v for k, v in e.items() if k != "changes"} if isinstance(e, dict) else e for e in rc]
        text = _compact_json(slim)
    return text[:_CS2_CHUNK], text[_CS2_CHUNK:2 * _CS2_CHUNK]


def _href_tail(href: object) -> str:
    return str(href or "").rstrip("/").rsplit("/", 1)[-1]


def _actor(created_by: object) -> tuple[str, str]:
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


def _first(*values: Any) -> Any:
    for v in values:
        if v is not None:
            return v
    return None


def _labels_obj(labels: object) -> dict[str, str]:
    if isinstance(labels, dict):
        return {str(k): str(v) for k, v in labels.items() if k and v}
    out: dict[str, str] = {}
    for lbl in labels if isinstance(labels, list) else []:
        if isinstance(lbl, dict) and lbl.get("key") and lbl.get("value"):
            out[str(lbl["key"])] = str(lbl["value"])
    return out


class PceNativeCEFFormatter(Formatter):
    """PCE-shaped CEF in two dialects.

    graylog  — byte-for-byte the PCE's own line except rt's zone suffix
               (Graylog's CEF codec drops lines that carry it); values are
               not escaped; empty-valued keys are kept (`outcome=`).
    arcsight — same keys, order and Signature IDs, but rt as epoch
               milliseconds (unambiguous, no device-timezone guessing),
               values escaped per the CEF spec, empty-valued keys omitted.
               ArcSight limits cs1-cs6 to 4,000 characters, which is exactly
               why the PCE chunks resource_changes at 3,995 (see
               _resource_changes_chunks); the chunking is shared.
    """

    DIALECTS = ("graylog", "arcsight")

    def __init__(self, *, pce_fqdn: str = "", pce_version: str = "unknown",
                 dialect: str = "graylog") -> None:
        if dialect not in self.DIALECTS:
            raise ValueError(f"unknown CEF dialect {dialect!r}")
        self._pce_fqdn = pce_fqdn
        self._pce_version = pce_version or "unknown"
        self._dialect = dialect
        self._arcsight = dialect == "arcsight"
        self._v = _escape_arcsight if self._arcsight else _clean_value

    def _kv(self, ext: list[str], key: str, value: object) -> None:
        """Append key=value; the arcsight dialect skips empty values."""
        text = "" if value is None else str(value)
        if text == "" and self._arcsight:
            return
        ext.append(f"{key}={self._v(text)}")

    # ── audit events ────────────────────────────────────────────────────
    def format_event(self, event: dict[str, Any]) -> str:
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
        rt = _rt_epoch_ms(str(event.get("timestamp") or "")) if self._arcsight else _rt_audit(str(event.get("timestamp") or ""))
        if rt:
            ext.append(f"rt={rt}")
        self._kv(ext, "dvchost", dvchost)
        if duid:
            self._kv(ext, "duid", duid)
        self._kv(ext, "duser", duser)
        self._kv(ext, "dst", dst)
        self._kv(ext, "outcome", status or "")
        ext.append("cat=audit_events")
        if action is not None:
            if action.get("api_endpoint") is not None:
                self._kv(ext, "request", action["api_endpoint"])
            if action.get("api_method") is not None:
                self._kv(ext, "requestMethod", action["api_method"])
            if action.get("http_status_code") is not None:
                self._kv(ext, "reason", action["http_status_code"])
        rc = event.get("resource_changes") or []
        cs2, cs3 = _resource_changes_chunks(rc) if rc else ("", "")
        self._kv(ext, "cs2", cs2)
        if cs2 or not self._arcsight:
            ext.append("cs2Label=resource_changes")
        notes = event.get("notifications") or []
        cs4 = _compact_json(notes) if notes else ""
        self._kv(ext, "cs4", cs4)
        if cs4 or not self._arcsight:
            ext.append("cs4Label=notifications")
        ext.append("cn2=2")
        ext.append("cn2Label=schema-version")
        ext.append("cs1Label=event_href")
        self._kv(ext, "cs1", event.get("href") or event.get("pce_event_id") or "")
        if cs3:
            self._kv(ext, "cs3", cs3)
            ext.append("cs3Label=resource_changes_2")
        return head + " ".join(ext)

    def format_ops(self, rec: SiemRecord) -> str:
        """Every CEF format sends this product's own events in its own CEF (device illumio-ops), cef_pce included."""
        return ops_cef(rec)
