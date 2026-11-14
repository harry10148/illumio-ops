"""Alert rules: list with each rule's latest state, create / update / delete (the settings file holds them, so a
write is validated as a whole and guarded by its revision), preview, and the best-practice pack."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from flask import Blueprint
from pydantic import BaseModel, Field

from illumio_ops.domain.alertpack import PACK_KEYS, best_practice_rules
from illumio_ops.domain.alertrules import AlertRule
from illumio_ops.domain.event_catalog import CATEGORY_KEYS, EVENT_DESC_KEYS, catalog
from illumio_ops.services.alerts import rule_test
from illumio_ops.services.alerts.rule_test import Candidates, RuleTestResult
from illumio_ops.services.alerts.rules import (
    RuleListItem,
    RulePreview,
    apply_pack,
    preview_rule,
    reset_rule_state,
    rule_list,
)
from illumio_ops.services.analysis.status import ConditionChoices, condition_choices
from illumio_ops.services.collect.guard import BindingMismatch
from illumio_ops.web.auth import get_ctx
from illumio_ops.web.contract import ApiFailure, api_route, operation


class RulesView(BaseModel):
    revision: int
    items: list[RuleListItem]
    pack_missing: int  # pack rules not in the list (deleted): "add what is missing" brings them back
    retention_days: int  # alert records kept; 0 = forever


class RetentionUpdate(BaseModel):
    revision: int
    retention_days: int = Field(ge=0, le=3650)


class EvaluateRequested(BaseModel):
    jobs: list[str]  # the scheduled jobs asked to run now
    requested_at: datetime


class RuleWrite(BaseModel):
    revision: int
    rule: AlertRule


class RuleDelete(BaseModel):
    revision: int


class RulePreviewRequest(BaseModel):
    rule: AlertRule
    hours: int = Field(ge=1, le=168)


class RuleTestRequest(BaseModel):
    source: Literal["detection", "event"]
    id: int = Field(ge=1)


class CatalogEventView(BaseModel):
    event_type: str
    description_key: str
    vendor_documented: bool
    status_filter: bool  # known to come with more than one status (domain/event_catalog.py)
    severity_filter: bool


class CatalogCategory(BaseModel):
    id: str
    label_key: str
    events: list[CatalogEventView]


class EventCatalog(BaseModel):
    categories: list[CatalogCategory]


class PackApply(BaseModel):
    revision: int
    mode: Literal["append_missing", "replace"]


class PackRule(BaseModel):
    rule: AlertRule  # as best_practice_rules(notify_new_defaults=True) builds it
    name_key: str    # the pack key: the i18n key of its name


class PackRules(BaseModel):
    rules: list[PackRule]


OP_LIST = operation("alert_rules.list", "GET", "/api/alert-rules", None, RulesView)
OP_CREATE = operation("alert_rules.create", "POST", "/api/alert-rules", RuleWrite, RulesView)
OP_UPDATE = operation("alert_rules.update", "PUT", "/api/alert-rules/<rule_id>", RuleWrite, RulesView)
OP_DELETE = operation("alert_rules.delete", "DELETE", "/api/alert-rules/<rule_id>", RuleDelete, RulesView)
OP_PREVIEW = operation("alert_rules.preview", "POST", "/api/alert-rules/preview", RulePreviewRequest, RulePreview)
OP_PACK = operation("alert_rules.pack", "POST", "/api/alert-rules/pack", PackApply, RulesView)
OP_TEST = operation("alert_rules.test", "POST", "/api/alert-rules/test", RuleTestRequest, RuleTestResult)
OP_CHOICES = operation("alert_rules.condition_choices", "GET", "/api/alert-rules/condition-choices", None,
                       ConditionChoices)
OP_RESET = operation("alert_rules.reset_state", "POST", "/api/alert-rules/<rule_id>/reset-state", None, RulesView)
OP_RETENTION = operation("alert_rules.retention", "PUT", "/api/alert-rules/retention", RetentionUpdate, RulesView)
OP_EVALUATE = operation("alert_rules.evaluate_now", "POST", "/api/alert-rules/evaluate-now", None, EvaluateRequested)
OP_EVENT_CATALOG = operation("alert_rules.event_catalog", "GET", "/api/alert-rules/event-catalog", None, EventCatalog)
OP_PACK_RULES = operation("alert_rules.pack_rules", "GET", "/api/alert-rules/pack-rules", None, PackRules)
OP_TEST_CANDIDATES = operation("alert_rules.test_candidates", "GET", "/api/alert-rules/test-candidates", None,
                               Candidates)

bp = Blueprint("alert_rules", __name__)


def _view() -> RulesView:
    ctx = get_ctx()
    s = ctx.settings.current()
    have = {r.pack_key for r in s.alerts.rules if r.pack_key}
    return RulesView(revision=s.revision, items=rule_list(ctx), pack_missing=len(PACK_KEYS - have),
                     retention_days=s.alerts.retention_days)


def _rules(d: dict[str, Any]) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = d["alerts"]["rules"]
    return rules


@api_route(bp, OP_LIST)
def list_rules() -> RulesView:
    return _view()


@api_route(bp, OP_CREATE)
def create_rule(body: RuleWrite) -> RulesView:
    rule = body.rule.model_dump(mode="json") | {"id": uuid.uuid4().hex, "pack_key": None}
    get_ctx().settings.update(body.revision, lambda d: _rules(d).append(rule))
    return _view()


@api_route(bp, OP_UPDATE)
def update_rule(body: RuleWrite, rule_id: str) -> RulesView:
    def mutate(d: dict[str, Any]) -> None:
        rules = _rules(d)
        for i, old in enumerate(rules):
            if old["id"] == rule_id:  # the id and the pack it came from never change
                rules[i] = body.rule.model_dump(mode="json") | {"id": rule_id, "pack_key": old["pack_key"]}
                return
        raise ApiFailure(404, "not_found", "err_not_found")
    get_ctx().settings.update(body.revision, mutate)
    return _view()


@api_route(bp, OP_DELETE)
def delete_rule(body: RuleDelete, rule_id: str) -> RulesView:
    def mutate(d: dict[str, Any]) -> None:
        rules = _rules(d)
        kept = [r for r in rules if r["id"] != rule_id]
        if len(kept) == len(rules):
            raise ApiFailure(404, "not_found", "err_not_found")
        d["alerts"]["rules"] = kept
    get_ctx().settings.update(body.revision, mutate)
    return _view()


@api_route(bp, OP_PREVIEW)
def preview(body: RulePreviewRequest) -> RulePreview:
    return preview_rule(get_ctx(), body.rule, hours=body.hours)


@api_route(bp, OP_PACK)
def apply(body: PackApply) -> RulesView:
    ctx = get_ctx()
    current = ctx.settings.current().alerts.rules
    # A pack rule added from here notifies: this is the operator's own choice, not an upgrade (spec §7).
    rules = apply_pack(current, mode=body.mode, notify_new_defaults=True)
    dumped = [r.model_dump(mode="json") for r in rules]
    ctx.settings.update(body.revision, lambda d: d["alerts"].__setitem__("rules", dumped))
    return _view()


@api_route(bp, OP_TEST)
def test_rules(body: RuleTestRequest) -> RuleTestResult:
    """Read-only: evaluates, never records or sends (services/alerts/rule_test.py)."""
    try:
        return rule_test.run(get_ctx(), body.source, body.id)
    except LookupError:
        raise ApiFailure(404, "not_found", "rule_test_not_found") from None
    except BindingMismatch:
        raise ApiFailure(409, "pce_switched", "wb_pce_switched") from None


@api_route(bp, OP_TEST_CANDIDATES)
def test_candidates() -> Candidates:
    try:
        return rule_test.candidates(get_ctx())
    except BindingMismatch:
        raise ApiFailure(409, "pce_switched", "wb_pce_switched") from None


@api_route(bp, OP_CHOICES)
def choices() -> ConditionChoices:
    """What a flow condition editor offers: the alert rule editor and the reports filter."""
    return condition_choices(get_ctx())


@api_route(bp, OP_EVENT_CATALOG)
def event_catalog() -> EventCatalog:
    """The event types the rule editor offers, by category; a rule may still name one it does not list."""
    by_category: dict[str, list[CatalogEventView]] = {c: [] for c in CATEGORY_KEYS}
    for e in catalog():
        by_category[e.category].append(CatalogEventView(
            event_type=e.event_type, description_key=EVENT_DESC_KEYS[e.event_type],
            vendor_documented=e.vendor_documented, status_filter=e.status_filter, severity_filter=e.severity_filter))
    return EventCatalog(categories=[CatalogCategory(id=c, label_key=CATEGORY_KEYS[c], events=events)
                                    for c, events in by_category.items() if events])


@api_route(bp, OP_PACK_RULES)
def pack_rules() -> PackRules:
    """The built-in pack's rules as the pack builds them, for the rule form to start from: not the settings file's
    copy (which the operator may have changed or deleted), and nothing is read from or written to it."""
    return PackRules(rules=[PackRule(rule=r, name_key=r.pack_key)
                            for r in best_practice_rules(notify_new_defaults=True) if r.pack_key is not None])


@api_route(bp, OP_RESET)
def reset_state(rule_id: str) -> RulesView:
    """Cooldown and throttle start over; what the rule has already seen stays seen (no history is alerted)."""
    ctx = get_ctx()
    if not any(r.id == rule_id for r in ctx.settings.current().alerts.rules):
        raise ApiFailure(404, "not_found", "err_not_found")
    reset_rule_state(ctx, rule_id)
    return _view()


@api_route(bp, OP_RETENTION)
def set_retention(body: RetentionUpdate) -> RulesView:
    get_ctx().settings.update(body.revision, lambda d: d["alerts"].__setitem__("retention_days", body.retention_days))
    return _view()


# The scheduled jobs that end in an alert evaluation (jobs/scheduler.py): events, traffic with the lateral and anomaly
# detectors, the system checks, and the PCE probe (its health check).
EVALUATING_JOBS = ("collect_events", "collect_traffic", "alerts_system", "pce_probe")
# APScheduler skips a run picked up later than its grace time (1 s by default) as missed: a run asked for now must not
# be dropped because the executor was busy for a moment. It stays on the job, where a late run also beats a skipped one.
EVALUATE_GRACE_SECONDS = 60


@api_route(bp, OP_EVALUATE)
def evaluate_now() -> EvaluateRequested:
    """Asks the scheduler's own jobs to run now (5.x "run now"): no second scheduler, no evaluation outside the jobs
    and their locks. A job already running finishes that pass instead."""
    ctx = get_ctx()
    if ctx.scheduler is None:
        raise ApiFailure(503, "jobs_not_running", "err_jobs_not_running")
    now = datetime.now(UTC)
    for job_id in EVALUATING_JOBS:
        ctx.scheduler.modify_job(job_id, next_run_time=now, misfire_grace_time=EVALUATE_GRACE_SECONDS)
    return EvaluateRequested(jobs=list(EVALUATING_JOBS), requested_at=now)
