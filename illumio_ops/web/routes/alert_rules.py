"""Alert rules: list with each rule's latest state, create / update / delete (the settings file holds them, so a
write is validated as a whole and guarded by its revision), preview, and the best-practice pack."""
from __future__ import annotations

import uuid
from typing import Any, Literal

from flask import Blueprint
from pydantic import BaseModel, Field

from illumio_ops.domain.alertpack import PACK_KEYS
from illumio_ops.domain.alertrules import AlertRule
from illumio_ops.services.alerts.rules import (
    RuleListItem,
    RulePreview,
    apply_pack,
    preview_rule,
    rule_list,
)
from illumio_ops.web.auth import get_ctx
from illumio_ops.web.contract import ApiFailure, api_route, operation


class RulesView(BaseModel):
    revision: int
    items: list[RuleListItem]
    pack_missing: int  # pack rules not in the list (deleted): "add what is missing" brings them back


class RuleWrite(BaseModel):
    revision: int
    rule: AlertRule


class RuleDelete(BaseModel):
    revision: int


class RulePreviewRequest(BaseModel):
    rule: AlertRule
    hours: int = Field(ge=1, le=168)


class PackApply(BaseModel):
    revision: int
    mode: Literal["append_missing", "replace"]


OP_LIST = operation("alert_rules.list", "GET", "/api/alert-rules", None, RulesView)
OP_CREATE = operation("alert_rules.create", "POST", "/api/alert-rules", RuleWrite, RulesView)
OP_UPDATE = operation("alert_rules.update", "PUT", "/api/alert-rules/<rule_id>", RuleWrite, RulesView)
OP_DELETE = operation("alert_rules.delete", "DELETE", "/api/alert-rules/<rule_id>", RuleDelete, RulesView)
OP_PREVIEW = operation("alert_rules.preview", "POST", "/api/alert-rules/preview", RulePreviewRequest, RulePreview)
OP_PACK = operation("alert_rules.pack", "POST", "/api/alert-rules/pack", PackApply, RulesView)

bp = Blueprint("alert_rules", __name__)


def _view() -> RulesView:
    ctx = get_ctx()
    s = ctx.settings.current()
    have = {r.pack_key for r in s.alerts.rules if r.pack_key}
    return RulesView(revision=s.revision, items=rule_list(ctx), pack_missing=len(PACK_KEYS - have))


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
