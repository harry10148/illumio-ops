"""This product's own events as CEF and as JSON (P7 defines them; spec §6.5 leaves the fields to P7).

CEF: the device is illumio-ops, never the PCE — a SOC must not attribute a detection to the PCE (the cef_pce header
names the PCE only for the audit events it relays). Always the ArcSight dialect (escaped values, rt in epoch
milliseconds: Graylog drops an rt with a zone suffix, 5.x 2026-09-12). Labels and facts go as JSON in cs fields, each
held to 3,995 characters like the PCE's own chunking (ArcSight's cs limit is 4,000); a cut is said in cs6."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from illumio_ops import __version__
from illumio_ops.domain.values import Severity
from illumio_ops.siem.records import Endpoint, SiemRecord

CS_LIMIT = 3995
CEF_SEVERITY = {None: 1, Severity.LOW: 3, Severity.MEDIUM: 5, Severity.HIGH: 8, Severity.CRITICAL: 10}
PROTO_NAMES = {6: "tcp", 17: "udp", 1: "icmp"}


def _compact(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str)


def _ms(value: datetime | None) -> str:
    return str(int(value.timestamp() * 1000)) if value else ""


def _iso(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None


def _head(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("=", "\\=").replace("\r", "\\r").replace("\n", "\\n")


def proto_name(proto: int | None) -> str:
    return "" if proto is None else PROTO_NAMES.get(proto, str(proto))


def facts_text(rec: SiemRecord) -> tuple[str, bool]:
    """The facts as compact JSON, cut to CS_LIMIT (and whether it was)."""
    text = _compact(dict(rec.facts)) if rec.facts else ""
    return (text[:CS_LIMIT], True) if len(text) > CS_LIMIT else (text, False)


def ops_cef(rec: SiemRecord) -> str:
    sev = CEF_SEVERITY.get(rec.severity, 1)
    head = f"CEF:0|Illumio|illumio-ops|{_head(__version__)}|{_head(rec.signature)}|{_head(rec.name or rec.signature)}|{sev}|"
    ext: list[str] = []

    def kv(key: str, value: object) -> None:
        text = "" if value is None else str(value)
        if text:
            ext.append(f"{key}={_escape(text)}")

    kv("rt", _ms(rec.time))
    kv("externalId", rec.external_id)
    kv("cat", f"illumio_ops_{rec.kind}")
    kv("msg", rec.summary)
    src, dst = rec.src or Endpoint(), rec.dst or Endpoint()
    kv("src", src.ip)
    kv("shost", src.host)
    kv("dst", dst.ip)
    kv("dhost", dst.host)
    kv("dpt", rec.port)
    kv("proto", proto_name(rec.proto))
    kv("act", rec.decision)
    kv("start", _ms(rec.first_seen))
    kv("end", _ms(rec.last_seen))
    kv("dvchost", rec.pce_fqdn)
    for n, (label, value) in enumerate((("src_labels", _compact(dict(src.labels)) if src.labels else ""),
                                        ("dst_labels", _compact(dict(dst.labels)) if dst.labels else ""),
                                        ("src_href", src.href or ""), ("dst_href", dst.href or "")), start=1):
        if value:
            kv(f"cs{n}", value[:CS_LIMIT])
            ext.append(f"cs{n}Label={label}")
    facts, cut = facts_text(rec)
    if facts:
        kv("cs5", facts)
        ext.append("cs5Label=facts")
    if cut:
        ext += ["cs6=true", "cs6Label=facts_truncated"]
    return head + " ".join(ext)


def _endpoint(prefix: str, e: Endpoint | None) -> dict[str, Any]:
    if e is None:
        return {}
    return {f"{prefix}_ip": e.ip, f"{prefix}_host": e.host, f"{prefix}_href": e.href,
            f"{prefix}_labels": dict(e.labels) or None}


def ops_json(rec: SiemRecord) -> str:
    out: dict[str, Any] = {
        "source": "illumio-ops", "kind": rec.kind, "id": rec.record_id, "external_id": rec.external_id,
        "time": _iso(rec.time), "signature": rec.signature, "name": rec.name,
        "severity": rec.severity.value if rec.severity else None, "summary": rec.summary,
        **_endpoint("src", rec.src), **_endpoint("dst", rec.dst),
        "port": rec.port, "proto": proto_name(rec.proto) or None, "decision": rec.decision,
        "first_seen": _iso(rec.first_seen), "last_seen": _iso(rec.last_seen),
        "facts": dict(rec.facts) or None, "pce_fqdn": rec.pce_fqdn,
    }
    return _compact({k: v for k, v in out.items() if v is not None and v != ""})
