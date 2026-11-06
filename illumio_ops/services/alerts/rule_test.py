"""Rule test on the alert rules page (UI redesign spec §5.1): one recent detection or event, evaluated against every
rule of its kind with the evaluation's own functions — the rule's verdict, the cooldown / throttle gate, the channels
it would be queued for. Nothing is written and nothing is sent: rule states, alerts and deliveries stay as they are.
Traffic, bandwidth, volume and system rules judge a period's totals, not one record, so they are not listed."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel

from illumio_ops.domain.alerting import gate, lateral_rule_reason
from illumio_ops.domain.alertrules import EventRule, LateralRule, event_matches
from illumio_ops.domain.values import DetectorKind, Language, ThresholdType
from illumio_ops.i18n import translate
from illumio_ops.services.alerts.channels import enabled_channels
from illumio_ops.services.alerts.evaluate import detection_fact, event_fact, inventory
from illumio_ops.services.collect.guard import require_same_pce
from illumio_ops.services.context import AppContext
from illumio_ops.services.eventsource import events_after, max_event_id
from illumio_ops.services.reports.common import DETECTOR_NAME_KEYS
from illumio_ops.store import alerts as store
from illumio_ops.store.flowdb import analysis, ip_lists, policy_objects

Source = Literal["detection", "event"]
CANDIDATES = 20
GATE_KEYS = {"cooldown": "rule_test_cooldown", "throttle": "rule_test_throttle"}
MISS_KEYS = {"other_detector": "rule_test_other_detector", "below_severity": "rule_test_below_severity",
             "not_critical": "rule_test_not_critical", "excluded": "rule_test_excluded"}


class RuleMatch(BaseModel):
    rule_id: str
    rule_name: str
    would_alert: bool
    reason_key: str | None  # why not, or a qualification (recorded only); None: it alerts and is sent
    params: dict[str, str]
    channels: list[str]


class RuleTestResult(BaseModel):
    source: Source
    record_id: int
    title: str
    items: list[RuleMatch]


class Candidate(BaseModel):
    source: Source
    record_id: int
    at: datetime
    title: str


class Candidates(BaseModel):
    items: list[Candidate]


def _name(rule: LateralRule | EventRule, lang: Language) -> str:
    return rule.name or translate(lang, rule.pack_key or "")


def _detection_title(row: object, lang: Language) -> str:
    kind = DetectorKind(row["detector"])  # type: ignore[index]
    key = DETECTOR_NAME_KEYS.get(kind)
    return f"{translate(lang, key) if key else kind.value} · {row['subject_key']}"  # type: ignore[index]


def _result(ctx: AppContext, rule: LateralRule | EventRule, subject: str, miss: str | None, *, now: datetime,
            params: dict[str, str] | None = None) -> RuleMatch:
    s = ctx.settings.current()
    lang = s.display.language
    name = _name(rule, lang)
    if not rule.enabled:
        return RuleMatch(rule_id=rule.id, rule_name=name, would_alert=False, reason_key="rule_test_disabled",
                         params={}, channels=[])
    if miss is not None:
        return RuleMatch(rule_id=rule.id, rule_name=name, would_alert=False, reason_key=miss, params=params or {},
                         channels=[])
    with ctx.db() as conn:
        state = store.rule_state(conn, rule.id, subject)
    g = gate(rule, state, now)
    if not g.allowed:
        return RuleMatch(rule_id=rule.id, rule_name=name, would_alert=False, reason_key=GATE_KEYS[g.reason],
                         params={}, channels=[])
    if not rule.notify:
        return RuleMatch(rule_id=rule.id, rule_name=name, would_alert=True, reason_key="rule_test_record_only",
                         params={}, channels=[])
    return RuleMatch(rule_id=rule.id, rule_name=name, would_alert=True, reason_key=None, params={},
                     channels=enabled_channels(s.alerts.channels))


def _detection(ctx: AppContext, record_id: int, now: datetime) -> RuleTestResult:
    s = ctx.settings.current()
    rules = [r for r in s.alerts.rules if isinstance(r, LateralRule)]
    with ctx.flows().connect() as conn:
        require_same_pce(conn, s.pce)
        row = analysis.detection_by_id(conn, record_id)
        if row is None:
            raise LookupError(record_id)
        names, labels = inventory(conn)
        nets = ip_lists.networks(conn, {h for r in rules if r.exclude for h in r.exclude.ip_lists})
        groups = policy_objects.label_groups(conn, {h for r in rules if r.exclude for h in r.exclude.label_groups})
    fact = detection_fact(row, start=("", 0), names=names, labels=labels, previous=None)
    items = []
    for rule in rules:
        why = lateral_rule_reason(rule, fact, ip_lists=nets, label_groups=groups)
        items.append(_result(ctx, rule, fact.fingerprint, MISS_KEYS[why] if why else None, now=now))
    return RuleTestResult(source="detection", record_id=record_id, title=_detection_title(row, s.display.language),
                          items=items)


def _event(ctx: AppContext, record_id: int, now: datetime) -> RuleTestResult:
    s = ctx.settings.current()
    found, _ = events_after(ctx, record_id - 1, limit=1)
    if not found or found[0].id != record_id:
        raise LookupError(record_id)
    fact = event_fact(found[0])
    items = []
    for rule in (r for r in s.alerts.rules if isinstance(r, EventRule)):
        subject = rule.id if rule.threshold is ThresholdType.COUNT else (fact.host_key or fact.event_type)
        if not event_matches(rule, fact.raw):
            items.append(_result(ctx, rule, subject, "rule_test_no_match", now=now))
        elif rule.threshold is ThresholdType.COUNT or rule.threshold_count > 1:
            items.append(_result(ctx, rule, subject, "rule_test_needs_count", now=now,
                                 params={"count": str(rule.threshold_count), "minutes": str(rule.window_minutes)}))
        else:
            items.append(_result(ctx, rule, subject, None, now=now))
    return RuleTestResult(source="event", record_id=record_id, title=f"{fact.event_type} · {fact.host_key or '—'}",
                          items=items)


def run(ctx: AppContext, source: Source, record_id: int, *, now: datetime | None = None) -> RuleTestResult:
    """LookupError: no such record (or not one collected live)."""
    at = (now or datetime.now(UTC)).astimezone(UTC)
    return _detection(ctx, record_id, at) if source == "detection" else _event(ctx, record_id, at)


def candidates(ctx: AppContext) -> Candidates:
    """The latest detections and live events to test with, newest first."""
    s = ctx.settings.current()
    lang = s.display.language
    with ctx.flows().connect() as conn:
        require_same_pce(conn, s.pce)
        dets = analysis.detections_since(conn, datetime.min.replace(tzinfo=UTC), limit=CANDIDATES)
    newest = max_event_id(ctx)
    evs, _ = events_after(ctx, max(newest - CANDIDATES, 0), limit=CANDIDATES)
    items = [Candidate(source="detection", record_id=int(r["id"]), at=datetime.fromisoformat(r["last_seen"]),
                       title=_detection_title(r, lang)) for r in dets]
    items += [Candidate(source="event", record_id=e.id, at=e.timestamp,
                        title=f"{e.event_type} · {e.hostname or e.host_key or '—'}") for e in evs]
    return Candidates(items=sorted(items, key=lambda c: c.at, reverse=True))


