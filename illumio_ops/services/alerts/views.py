"""What the Alerts pages show: the current PCE's alerts with their sentence and delivery state, one alert's
detail, its evidence (the analysis segment run now), its notes, and the policy that applies to an evidence row."""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from illumio_ops.domain.alertcategory import AlertCategory, category, category_filter
from illumio_ops.domain.beyond_vendor import beyond_vendor
from illumio_ops.domain.segment import EventSegment, FlowSegment
from illumio_ops.domain.values import AlertRuleType, DetectorKind, Language, Severity
from illumio_ops.i18n import translate
from illumio_ops.services.alerts.messages import (
    alert_view,
    caveats,
    console_url,
    display_zone,
    rule_title,
    summary,
)
from illumio_ops.services.analysis.explain import (
    Endpoint,
    PolicyExplanation,
    explain_flow,
)
from illumio_ops.services.collect.guard import BindingMismatch, require_same_pce
from illumio_ops.services.context import AppContext
from illumio_ops.services.coverage import Coverage
from illumio_ops.services.eventsource import event_detail
from illumio_ops.services.flowsource import query_flows
from illumio_ops.services.hosts import QuarantineEligibility
from illumio_ops.services.reports.common import DETECTOR_NAME_KEYS
from illumio_ops.store import alerts as store
from illumio_ops.store.flowdb import analysis as detection_store
from illumio_ops.store.flowdb import events as event_store

PAGE = 50
EVIDENCE_LIMIT = 200
TIMELINE_BEFORE = timedelta(hours=24)  # how far before the alert's first sight the timeline reaches
TIMELINE_LIMIT = 20                    # detections, and events, each


class DeliveryView(BaseModel):
    channel: str
    status: str
    attempts: int
    last_error: str | None
    sent_at: datetime | None


class AlertItem(BaseModel):
    id: int
    fired_at: datetime
    severity: Severity
    rule_id: str
    rule_type: AlertRuleType
    rule_name: str
    subject_key: str
    summary: str
    caveats: list[str]
    late: bool
    grouped: bool
    deliveries: list[DeliveryView]
    category: AlertCategory
    src: str | None  # the source and destination the alert's parameters name (none for rule-wide alerts)
    dst: str | None


class AlertCounts(BaseModel):
    """The period's alerts per severity and how many were marked as known, before the page's filters."""
    critical: int
    high: int
    medium: int
    low: int
    grouped: int


class AlertList(BaseModel):
    items: list[AlertItem]
    total: int
    page: int
    page_size: int
    counts: AlertCounts


class TimelineEntry(BaseModel):
    at: datetime
    kind: Literal["alert", "detection", "event"]
    text: str


class NoteView(BaseModel):
    id: int
    body: str
    created_by: str
    created_at: datetime


class AlertDetail(AlertItem):
    params: dict[str, Any]
    facts: dict[str, Any]
    confidence: dict[str, Any]
    first_seen: datetime
    last_seen: datetime
    evidence_kind: Literal["flow", "event"] | None
    console_link: str | None
    notes: list[NoteView]
    timeline: list[TimelineEntry]
    beyond_vendor: list[str]
    quarantine: QuarantineEligibility


class AlertEvidence(BaseModel):
    kind: Literal["flow", "event"] | None
    rows: list[dict[str, Any]]
    limit_hit: bool
    coverage: Coverage | None


class AlertQuery(BaseModel):
    days: int = Field(default=7, ge=1, le=3650)
    type: AlertRuleType | None = None
    category: AlertCategory | None = None
    unprocessed: bool = False
    severity: Severity | None = None
    rule: str | None = Field(default=None, max_length=64)
    page: int = Field(default=1, ge=1, le=100000)


class ExplainRequest(BaseModel):
    src_href: str | None
    src_ip: str = Field(min_length=1, max_length=64)
    dst_href: str | None
    dst_ip: str = Field(min_length=1, max_length=64)
    port: int = Field(ge=0, le=65535)
    proto: int = Field(ge=0, le=255)


class NotFlowAlert(Exception):
    """Only an alert whose evidence is flows has a policy to explain."""


def _pce(ctx: AppContext) -> tuple[str, str]:
    p = ctx.settings.current().pce
    return p.url, p.org_id


def _deliveries(rows: list[sqlite3.Row]) -> list[DeliveryView]:
    return [DeliveryView(channel=d["channel"], status=d["status"], attempts=d["attempts"], last_error=d["last_error"],
                         sent_at=datetime.fromisoformat(d["sent_at"]) if d["sent_at"] else None) for d in rows]


def _named(value: Any) -> str | None:
    return None if value in (None, "", []) else str(value)


def ends(params: dict[str, Any]) -> tuple[str | None, str | None]:
    """The source and destination an alert's parameters name: a host or source name, else a count of sources; a
    target, else a count of targets. Nothing is guessed when the parameters name neither."""
    src = _named(params.get("host")) or _named(params.get("source")) or _named(params.get("sources"))
    dst = _named(params.get("target")) or _named(params.get("targets"))
    return src, dst


def _item(ctx: AppContext, row: sqlite3.Row, deliveries: list[sqlite3.Row]) -> AlertItem:
    lang = ctx.settings.current().display.language
    v = alert_view(row)
    rule_type = AlertRuleType(row["rule_type"])
    params = json.loads(row["params_json"])
    src, dst = ends(params) if rule_type is AlertRuleType.LATERAL else (None, None)
    return AlertItem(id=v.id, fired_at=v.fired_at, severity=v.severity, rule_id=row["rule_id"],
                     rule_type=rule_type, rule_name=rule_title(v, lang),
                     subject_key=v.subject_key, summary=summary(v, lang), caveats=caveats(v, lang), late=v.late,
                     grouped=row["grouped_annotation"] is not None, deliveries=_deliveries(deliveries),
                     category=category(rule_type, params.get("detector")), src=src, dst=dst)


def list_alerts(ctx: AppContext, q: AlertQuery, *, now: datetime | None = None) -> AlertList:
    at = (now or datetime.now(UTC)).astimezone(UTC)
    url, org = _pce(ctx)
    since = at - timedelta(days=q.days)
    types, inside, outside = category_filter(q.category) if q.category else (None, None, None)
    with ctx.db() as conn:
        rows, total = store.list_alerts(conn, pce_url=url, org_id=org, since=since,
                                        rule_type=q.type.value if q.type else None, rule_types=types,
                                        detectors_in=inside, detectors_not_in=outside, ungrouped_only=q.unprocessed,
                                        severity=q.severity.value if q.severity else None, rule_id=q.rule,
                                        limit=PAGE, offset=(q.page - 1) * PAGE)
        found = store.deliveries(conn, [r["id"] for r in rows])
        counted = store.period_counts(conn, pce_url=url, org_id=org, since=since)
    by_alert: dict[int, list[sqlite3.Row]] = {}
    for d in found:
        by_alert.setdefault(d["alert_id"], []).append(d)
    counts = AlertCounts(**{k: counted.get(k, 0) for k in ("critical", "high", "medium", "low", "grouped")})
    return AlertList(items=[_item(ctx, r, by_alert.get(r["id"], [])) for r in rows], total=total, page=q.page,
                     page_size=PAGE, counts=counts)


def _link(ctx: AppContext, row: sqlite3.Row) -> str:
    """The PCE console's front page. A deep link to the workload (#/workloads/<uuid>) is not documented by Illumio
    and could not be confirmed on lab without a console sign-in (P4 acceptance), so none is made."""
    return console_url(ctx.settings.current().pce)


def _detection(ctx: AppContext, facts: dict[str, Any], subject: str) -> sqlite3.Row | None:
    """The detection a lateral alert was raised for, when it is still stored: the same id and the alert's subject (its
    fingerprint) — a flow store rebuilt after a PCE switch gives ids again to other detections."""
    det_id = facts.get("detection_id")
    if not isinstance(det_id, int):
        return None
    try:
        with ctx.flows().connect() as conn:
            require_same_pce(conn, ctx.settings.current().pce)
            row = detection_store.detection_by_id(conn, det_id)
    except BindingMismatch:
        return None
    return row if row is not None and row["fingerprint"] == subject else None


def _timeline(ctx: AppContext, row: sqlite3.Row, rule: str, detection: sqlite3.Row | None,
              lang: Language) -> list[TimelineEntry]:
    """The alert, and around it the same host's detections and PCE events from a day before it was first seen."""
    fired = datetime.fromisoformat(row["fired_at"])
    out = [TimelineEntry(at=fired, kind="alert", text=translate(lang, "timeline_alert", {"rule": rule}))]
    if detection is None:
        return out
    host = detection["subject_key"]
    start = datetime.fromisoformat(row["first_seen"]) - TIMELINE_BEFORE
    end = max(fired, datetime.fromisoformat(row["last_seen"]))
    try:
        with ctx.flows().connect() as conn:
            require_same_pce(conn, ctx.settings.current().pce)
            dets = detection_store.detections_of_subject(conn, host, start=start, end=end, limit=TIMELINE_LIMIT)
            evs = event_store.events_for_workload(conn, host, start=start, end=end, limit=TIMELINE_LIMIT)
    except BindingMismatch:
        return out
    for d in dets:
        name_key = DETECTOR_NAME_KEYS.get(DetectorKind(d["detector"]))
        out.append(TimelineEntry(at=datetime.fromisoformat(d["first_seen"]), kind="detection",
                                 text=translate(lang, "timeline_detection",
                                                {"detector": translate(lang, name_key) if name_key else d["detector"],
                                                 "severity": translate(lang, SEVERITY_WORDS[d["severity"]])})))
    for e in evs:
        cls = f" ({e['tamper_classification']})" if e["tamper_classification"] else ""
        out.append(TimelineEntry(at=datetime.fromisoformat(e["timestamp"]), kind="event",
                                 text=f"{e['event_type']}{cls}"))
    return sorted(out, key=lambda e: (e.at, e.kind != "detection"))


SEVERITY_WORDS = {"low": "severity_low", "medium": "severity_medium", "high": "severity_high",
                  "critical": "severity_critical"}


def _beyond(ctx: AppContext, params: dict[str, Any], lang: Language) -> list[str]:
    tz, label = display_zone(ctx.settings.current().display)
    out = []
    for f in beyond_vendor(params):
        values = dict(f.params)
        if "at" in values:
            try:
                local = datetime.fromisoformat(values["at"]).astimezone(tz)
                values["at"] = f"{local.strftime('%Y-%m-%d %H:%M')} {label or local.strftime('%Z')}".rstrip()
            except ValueError:
                pass
        out.append(translate(lang, f.text_key, values))
    return out


def _quarantine(ctx: AppContext, detection: sqlite3.Row | None) -> QuarantineEligibility:
    from illumio_ops.services import (
        quarantine,  # the quarantine service reads the alert views' neighbours
    )

    none = QuarantineEligibility(eligible=False, reason="no_subject", no_enforcement=False, key=None, name=None)
    if detection is None:
        return none
    try:
        target = quarantine.eligibility(ctx, detection["subject_key"])
    except BindingMismatch:
        return none
    if target is None:
        return none
    return QuarantineEligibility(eligible=target.ok, reason=target.reason, no_enforcement=target.no_enforcement,
                                 key=target.key, name=target.name)


def alert_detail(ctx: AppContext, alert_id: int) -> AlertDetail | None:
    url, org = _pce(ctx)
    with ctx.db() as conn:
        row = store.get_alert(conn, alert_id, pce_url=url, org_id=org)
        if row is None:
            return None
        deliveries = store.deliveries(conn, [alert_id])
        notes = store.notes(conn, alert_id)
    item = _item(ctx, row, deliveries)
    evidence = json.loads(row["evidence_json"]) if row["evidence_json"] else None
    lang = ctx.settings.current().display.language
    params = json.loads(row["params_json"])
    facts = json.loads(row["facts_json"])
    detection = _detection(ctx, facts, row["subject_key"]) if item.rule_type is AlertRuleType.LATERAL else None
    return AlertDetail(
        **item.model_dump(), params=params, facts=facts,
        confidence=json.loads(row["confidence_json"]), first_seen=datetime.fromisoformat(row["first_seen"]),
        last_seen=datetime.fromisoformat(row["last_seen"]), evidence_kind=evidence["kind"] if evidence else None,
        console_link=_link(ctx, row),
        notes=[NoteView(id=n["id"], body=n["body"], created_by=n["created_by"],
                        created_at=datetime.fromisoformat(n["created_at"])) for n in notes],
        timeline=_timeline(ctx, row, item.rule_name, detection, lang),
        beyond_vendor=_beyond(ctx, params, lang) if item.rule_type is AlertRuleType.LATERAL else [],
        quarantine=_quarantine(ctx, detection))


def evidence_segment(ctx: AppContext, alert_id: int) -> tuple[str | None, dict[str, Any] | None] | None:
    url, org = _pce(ctx)
    with ctx.db() as conn:
        row = store.get_alert(conn, alert_id, pce_url=url, org_id=org)
    if row is None:
        return None
    if not row["evidence_json"]:
        return None, None
    evidence = json.loads(row["evidence_json"])
    return evidence["kind"], evidence["segment"]


def alert_evidence(ctx: AppContext, alert_id: int) -> AlertEvidence | None:
    found = evidence_segment(ctx, alert_id)
    if found is None:
        return None
    kind, segment = found
    if kind == "flow" and segment is not None:
        seg = FlowSegment.model_validate(segment)
        q = query_flows(ctx, seg.filter, limit=EVIDENCE_LIMIT, order="last_detected_desc")
        return AlertEvidence(kind="flow", rows=[r.model_dump(mode="json") for r in q.rows], limit_hit=q.limit_hit,
                             coverage=q.coverage)
    if kind == "event" and segment is not None:
        eseg = EventSegment.model_validate(segment).model_copy(update={"limit": EVIDENCE_LIMIT})
        e = event_detail(ctx, eseg)
        return AlertEvidence(kind="event", rows=[r.model_dump(mode="json", exclude={"raw"}) for r in e.rows],
                             limit_hit=e.limit_hit, coverage=e.coverage)
    return AlertEvidence(kind=None, rows=[], limit_hit=False, coverage=None)


def add_note(ctx: AppContext, alert_id: int, *, body: str, by: str) -> AlertDetail | None:
    if alert_detail(ctx, alert_id) is None:
        return None
    with ctx.db() as conn:
        store.add_note(conn, alert_id, body=body, created_by=by, at=datetime.now(UTC))
    return alert_detail(ctx, alert_id)


def explain(ctx: AppContext, alert_id: int, req: ExplainRequest) -> PolicyExplanation | None:
    found = evidence_segment(ctx, alert_id)
    if found is None:
        return None
    if found[0] != "flow":
        raise NotFlowAlert
    return explain_flow(ctx, Endpoint(href=req.src_href, ip=req.src_ip), Endpoint(href=req.dst_href, ip=req.dst_ip),
                        req.port, req.proto)
