"""The four record sources a SIEM destination reads after its cursor (P7): PCE audit events (live ones only: a
backfilled event is history, spec §7), this product's alerts (those that notify, of the configured PCE: an alert the
rule only records is not sent anywhere, spec §7) and detections, and the new-connection log. Each read opens and closes
its own connection: the dispatcher sends with none open, so a PCE switch never waits for a slow SIEM."""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from illumio_ops.domain.focus import DETECTION_TITLE_KEYS
from illumio_ops.domain.values import (
    DetectorKind,
    Language,
    PolicyDecision,
    Severity,
    SiemSource,
)
from illumio_ops.i18n import translate
from illumio_ops.services.alerts.messages import (
    alert_view,
    caveats,
    rule_title,
    summary,
)
from illumio_ops.services.context import AppContext
from illumio_ops.services.eventsource import (
    live_events_after,
    live_events_after_count,
    newest_event_id,
)
from illumio_ops.services.hosts import display_names
from illumio_ops.services.reports.common import DETECTOR_NAME_KEYS
from illumio_ops.services.reports.flowsections import DECISION_KEYS
from illumio_ops.settings.schema import SiemDestination
from illumio_ops.siem.mask import mask_event
from illumio_ops.siem.records import Endpoint, SiemRecord
from illumio_ops.store.flowdb.labels import label_sets
from illumio_ops.store.siem import FLOW_SOURCES

AUDIT, ALERTS, DETECTIONS, NEW_CONNECTIONS = "audit", "alerts", "detections", "new_connections"
CURSOR_SOURCES: Mapping[SiemSource, tuple[str, ...]] = {
    SiemSource.AUDIT: (AUDIT,), SiemSource.FINDINGS: (ALERTS, DETECTIONS),
    SiemSource.NEW_CONNECTIONS: (NEW_CONNECTIONS,)}
_PROTO = {6: "TCP", 17: "UDP", 1: "ICMP"}


def cursor_sources(dest: SiemDestination) -> list[str]:
    return [c for s in dest.sources for c in CURSOR_SOURCES[s]]


def _t(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _lang(ctx: AppContext) -> Language:
    return ctx.settings.current().display.language


def _pce_fqdn(ctx: AppContext) -> str:
    from urllib.parse import urlsplit
    return urlsplit(ctx.settings.current().pce.url).hostname or ""


def _endpoint(key: str, names: Mapping[str, str], **extra: Any) -> Endpoint:
    if key.startswith("ip:"):
        return Endpoint(ip=key[3:], **extra)
    if key.startswith("/orgs/"):
        return Endpoint(href=key, host=names.get(key), **extra)
    return Endpoint(host=key, **extra)


def _text(value: Any) -> str:
    if isinstance(value, list | tuple):
        return ", ".join(_text(x) for x in value)
    return "" if value is None else str(value)


# ── audit ────────────────────────────────────────────────────────────────────

def _audit(ctx: AppContext, after: int, limit: int, dest: SiemDestination) -> list[SiemRecord]:
    return [SiemRecord(kind="audit", record_id=e.id, time=e.timestamp, event=mask_event(e.event, mask_pii=dest.mask_pii))
            for e in live_events_after(ctx, after, limit)]


# ── alerts ───────────────────────────────────────────────────────────────────

def _alerts(ctx: AppContext, after: int, limit: int, dest: SiemDestination) -> list[SiemRecord]:
    pce = ctx.settings.current().pce
    with ctx.db() as conn:
        rows = conn.execute("SELECT * FROM alerts WHERE id > ? AND notify = 1 AND pce_url = ? AND org_id = ? "
                            "ORDER BY id LIMIT ?", (after, pce.url, pce.org_id, limit)).fetchall()
    if not rows:
        return []
    lang = _lang(ctx)
    names = display_names(ctx, {str(r["subject_key"]) for r in rows if str(r["subject_key"]).startswith("/orgs/")})
    fqdn = _pce_fqdn(ctx)
    out = []
    for r in rows:
        v = alert_view(r)
        text = " ".join([summary(v, lang), *caveats(v, lang)])
        out.append(SiemRecord(
            kind="alert", record_id=v.id, time=v.fired_at, signature=f"alert.{r['rule_type']}",
            name=rule_title(v, lang), severity=v.severity, summary=text,
            src=_endpoint(v.subject_key, names), first_seen=_t(r["first_seen"]), last_seen=_t(r["last_seen"]),
            facts={"rule_id": r["rule_id"], "subject": v.subject_key, "late": v.late, **dict(v.facts)},
            pce_fqdn=fqdn))
    return out


# ── detections ───────────────────────────────────────────────────────────────

def _detections(ctx: AppContext, after: int, limit: int, dest: SiemDestination) -> list[SiemRecord]:
    with ctx.flows().connect() as conn:
        rows = conn.execute("SELECT * FROM detections WHERE id > ? ORDER BY id LIMIT ?", (after, limit)).fetchall()
    if not rows:
        return []
    lang = _lang(ctx)
    names = display_names(ctx, {str(r["subject_key"]) for r in rows if str(r["subject_key"]).startswith("/orgs/")})
    fqdn = _pce_fqdn(ctx)
    out = []
    for r in rows:
        kind = DetectorKind(r["detector"])
        found = json.loads(r["summary_json"] or "{}")
        subject = str(r["subject_key"])
        values = {k: _text(x) for k, x in found.items()}
        values.update(host=names.get(subject, subject), account=subject, minutes=_text(found.get("window_minutes")))
        port = found.get("port") if isinstance(found.get("port"), int) else None
        proto = found.get("proto") if isinstance(found.get("proto"), int) else None
        out.append(SiemRecord(
            kind="detection", record_id=int(r["id"]), time=_t(r["last_seen"]) or datetime.now(UTC),
            signature=f"detection.{kind.value}", name=translate(lang, DETECTOR_NAME_KEYS[kind]),
            severity=Severity(r["severity"]), summary=translate(lang, DETECTION_TITLE_KEYS[kind], values),
            src=_endpoint(subject, names), port=port, proto=proto,
            decision=found.get("decision") if isinstance(found.get("decision"), str) else None,
            first_seen=_t(r["first_seen"]), last_seen=_t(r["last_seen"]),
            facts={"detector": kind.value, "occurrences": int(r["occurrences"]),
                   "critical_asset": bool(r["critical_asset"]), "late": bool(r["late"]), **found},
            pce_fqdn=fqdn))
    return out


# ── new connections ──────────────────────────────────────────────────────────

def _decision_clause(dest: SiemDestination) -> tuple[str, list[Any]]:
    decisions = [d.value for d in dest.new_connection_decisions]
    if not decisions:
        return "", []
    if PolicyDecision.UNKNOWN.value in decisions:  # a decision the flow did not carry reads as unknown
        return (f" AND (decision IN ({','.join('?' * len(decisions))}) OR decision IS NULL)", decisions)
    return f" AND decision IN ({','.join('?' * len(decisions))})", decisions


def _new_connections(ctx: AppContext, after: int, limit: int, dest: SiemDestination) -> list[SiemRecord]:
    clause, args = _decision_clause(dest)
    with ctx.flows().connect() as conn:
        rows = conn.execute(f"SELECT * FROM new_connection_log WHERE id > ?{clause} ORDER BY id LIMIT ?",
                            (after, *args, limit)).fetchall()
        sets = label_sets(conn, {s for r in rows for s in (r["src_label_set"], r["dst_label_set"]) if s is not None})
    if not rows:
        return []
    lang = _lang(ctx)
    fqdn = _pce_fqdn(ctx)
    out = []
    for r in rows:
        decision = r["decision"] or PolicyDecision.UNKNOWN.value
        src = _endpoint(r["src_key"], {r["src_key"]: r["src_hostname"]} if r["src_hostname"] else {},
                        labels=sets.get(r["src_label_set"], {}) if r["src_label_set"] is not None else {})
        dst = _endpoint(r["dst_key"], {r["dst_key"]: r["dst_hostname"]} if r["dst_hostname"] else {},
                        labels=sets.get(r["dst_label_set"], {}) if r["dst_label_set"] is not None else {})
        src = Endpoint(ip=src.ip or r["src_ip"], host=src.host, href=src.href, labels=src.labels)
        dst = Endpoint(ip=dst.ip or r["dst_ip"], host=dst.host, href=dst.href, labels=dst.labels)
        out.append(SiemRecord(
            kind="new_connection", record_id=int(r["id"]), time=_t(r["first_seen"]) or datetime.now(UTC),
            signature=f"new_connection.{decision}", name=translate(lang, "siem_new_connection_name"),
            summary=translate(lang, "siem_new_connection_summary", {
                "src": src.host or src.ip or "", "dst": dst.host or dst.ip or "",
                "port": f"{r['port']}/{_PROTO.get(int(r['proto']), str(r['proto']))}",
                "decision": translate(lang, DECISION_KEYS.get(decision, "decision_unknown"))}),
            src=src, dst=dst, port=int(r["port"]), proto=int(r["proto"]), decision=decision,
            first_seen=_t(r["first_seen"]), pce_fqdn=fqdn))
    return out


# ── the registry ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Source:
    name: str
    read: Callable[[AppContext, int, int, SiemDestination], list[SiemRecord]]
    max_sql: str           # the newest id (a new cursor starts there); "" for audit (EventSource reads events)
    pending_sql: str       # records a cursor at ? has not sent yet (without a destination's decision filter)
    in_flow_store: bool


SOURCES: Mapping[str, Source] = {
    AUDIT: Source(AUDIT, _audit, "", "", True),
    ALERTS: Source(ALERTS, _alerts, "SELECT COALESCE(MAX(id), 0) FROM alerts",
                   "SELECT COUNT(*) FROM alerts WHERE id > ? AND notify = 1 AND pce_url = ? AND org_id = ?", False),
    DETECTIONS: Source(DETECTIONS, _detections, "SELECT COALESCE(MAX(id), 0) FROM detections",
                       "SELECT COUNT(*) FROM detections WHERE id > ?", True),
    NEW_CONNECTIONS: Source(NEW_CONNECTIONS, _new_connections, "SELECT COALESCE(MAX(id), 0) FROM new_connection_log",
                            "SELECT COUNT(*) FROM new_connection_log WHERE id > ?", True),
}
assert {s for s in SOURCES if SOURCES[s].in_flow_store} == set(FLOW_SOURCES)


def _scalar(ctx: AppContext, source: Source, sql: str, args: tuple[Any, ...] = ()) -> int:
    conn: sqlite3.Connection
    with (ctx.flows().connect() if source.in_flow_store else ctx.db()) as conn:
        return int(conn.execute(sql, args).fetchone()[0])


def newest_id(ctx: AppContext, name: str) -> int:
    if name == AUDIT:
        return newest_event_id(ctx)
    return _scalar(ctx, SOURCES[name], SOURCES[name].max_sql)


def pending(ctx: AppContext, name: str, after: int) -> int:
    if name == AUDIT:
        return live_events_after_count(ctx, after)
    pce = ctx.settings.current().pce
    args: tuple[Any, ...] = (after, pce.url, pce.org_id) if name == ALERTS else (after,)
    return _scalar(ctx, SOURCES[name], SOURCES[name].pending_sql, args)
