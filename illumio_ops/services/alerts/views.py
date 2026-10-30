"""What the Alerts pages show: the current PCE's alerts with their sentence and delivery state, one alert's
detail, its evidence (the analysis segment run now), its notes, and the policy that applies to an evidence row."""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from illumio_ops.domain.segment import EventSegment, FlowSegment
from illumio_ops.domain.values import AlertRuleType, Severity
from illumio_ops.services.alerts.messages import (
    alert_view,
    caveats,
    console_url,
    rule_title,
    summary,
)
from illumio_ops.services.analysis.explain import (
    Endpoint,
    PolicyExplanation,
    explain_flow,
)
from illumio_ops.services.context import AppContext
from illumio_ops.services.coverage import Coverage
from illumio_ops.services.eventsource import event_detail
from illumio_ops.services.flowsource import query_flows
from illumio_ops.store import alerts as store

PAGE = 50
EVIDENCE_LIMIT = 200


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


class AlertList(BaseModel):
    items: list[AlertItem]
    total: int
    page: int
    page_size: int


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


class AlertEvidence(BaseModel):
    kind: Literal["flow", "event"] | None
    rows: list[dict[str, Any]]
    limit_hit: bool
    coverage: Coverage | None


class AlertQuery(BaseModel):
    days: int = Field(default=7, ge=1, le=3650)
    type: AlertRuleType | None = None
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


def _item(ctx: AppContext, row: sqlite3.Row, deliveries: list[sqlite3.Row]) -> AlertItem:
    lang = ctx.settings.current().display.language
    v = alert_view(row)
    return AlertItem(id=v.id, fired_at=v.fired_at, severity=v.severity, rule_id=row["rule_id"],
                     rule_type=AlertRuleType(row["rule_type"]), rule_name=rule_title(v, lang),
                     subject_key=v.subject_key, summary=summary(v, lang), caveats=caveats(v, lang), late=v.late,
                     grouped=row["grouped_annotation"] is not None, deliveries=_deliveries(deliveries))


def list_alerts(ctx: AppContext, q: AlertQuery, *, now: datetime | None = None) -> AlertList:
    at = (now or datetime.now(UTC)).astimezone(UTC)
    url, org = _pce(ctx)
    with ctx.db() as conn:
        rows, total = store.list_alerts(conn, pce_url=url, org_id=org, since=at - timedelta(days=q.days),
                                        rule_type=q.type.value if q.type else None,
                                        severity=q.severity.value if q.severity else None, rule_id=q.rule,
                                        limit=PAGE, offset=(q.page - 1) * PAGE)
        found = store.deliveries(conn, [r["id"] for r in rows])
    by_alert: dict[int, list[sqlite3.Row]] = {}
    for d in found:
        by_alert.setdefault(d["alert_id"], []).append(d)
    return AlertList(items=[_item(ctx, r, by_alert.get(r["id"], [])) for r in rows], total=total, page=q.page,
                     page_size=PAGE)


def _link(ctx: AppContext, row: sqlite3.Row) -> str:
    """The PCE console's front page. A deep link to the workload (#/workloads/<uuid>) is not documented by Illumio
    and could not be confirmed on lab without a console sign-in (P4 acceptance), so none is made."""
    return console_url(ctx.settings.current().pce)


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
    return AlertDetail(
        **item.model_dump(), params=json.loads(row["params_json"]), facts=json.loads(row["facts_json"]),
        confidence=json.loads(row["confidence_json"]), first_seen=datetime.fromisoformat(row["first_seen"]),
        last_seen=datetime.fromisoformat(row["last_seen"]), evidence_kind=evidence["kind"] if evidence else None,
        console_link=_link(ctx, row),
        notes=[NoteView(id=n["id"], body=n["body"], created_by=n["created_by"],
                        created_at=datetime.fromisoformat(n["created_at"])) for n in notes])


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
