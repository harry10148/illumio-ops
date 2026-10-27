"""Detections an operator marked known (spec §6.5.8 共通原則, as tampering's known causes §6.5.4): a later alert
about the same detection — or, with the subject scope, any of that detector's about the same host or account — is
still recorded but grouped, not sent."""
from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from illumio_ops.domain.alerting import Trigger
from illumio_ops.domain.values import AlertRuleType
from illumio_ops.services.context import AppContext
from illumio_ops.store import alerts as alert_store
from illumio_ops.store import detection_annotations as store


class KnownMark(BaseModel):
    scope: Literal["detection", "subject"]
    reason: str = Field(min_length=1, max_length=500)


class KnownView(BaseModel):
    id: int
    detector: str
    subject_key: str
    fingerprint: str | None
    reason: str
    created_by: str
    created_at: datetime


class KnownList(BaseModel):
    items: list[KnownView]


class NotLateralAlert(Exception):
    """Only an alert about a detection can mark it known."""


def _pce(ctx: AppContext) -> tuple[str, str]:
    p = ctx.settings.current().pce
    return p.url, p.org_id


def list_known(ctx: AppContext) -> KnownList:
    url, org = _pce(ctx)
    with ctx.db() as conn:
        rows = store.for_pce(conn, url, org)
    return KnownList(items=[KnownView(id=r["id"], detector=r["detector"], subject_key=r["subject_key"],
                                      fingerprint=r["fingerprint"], reason=r["reason"], created_by=r["created_by"],
                                      created_at=datetime.fromisoformat(r["created_at"])) for r in rows])


def mark_known(ctx: AppContext, alert_id: int, body: KnownMark, *, by: str) -> KnownList | None:
    """None: no such alert of the current PCE. NotLateralAlert: the alert is not about a detection."""
    url, org = _pce(ctx)
    with ctx.db() as conn:
        row = alert_store.get_alert(conn, alert_id, pce_url=url, org_id=org)
        if row is None:
            return None
        params = json.loads(row["params_json"])
        if row["rule_type"] != AlertRuleType.LATERAL.value or not params.get("detector") or not params.get("account"):
            raise NotLateralAlert
        store.add(conn, pce_url=url, org_id=org, detector=str(params["detector"]), subject_key=str(params["account"]),
                  fingerprint=row["subject_key"] if body.scope == "detection" else None, reason=body.reason,
                  created_by=by, at=datetime.now(UTC))
    return list_known(ctx)


def remove_known(ctx: AppContext, mark_id: int) -> KnownList | None:
    url, org = _pce(ctx)
    with ctx.db() as conn:
        if not store.remove(conn, mark_id, pce_url=url, org_id=org):
            return None
    return list_known(ctx)


def apply_known(triggers: Sequence[Trigger], marks: Sequence[KnownView]) -> list[Trigger]:
    """A lateral trigger a mark covers is grouped under it and carries its reason (recorded, not sent)."""
    out = []
    for t in triggers:
        detector, subject = t.params.get("detector"), t.params.get("account")
        found = next((m for m in marks if m.detector == detector and m.subject_key == subject
                      and m.fingerprint in (None, t.subject_key)), None)
        if found is None:
            out.append(t)
            continue
        out.append(Trigger(**{**t.__dict__, "params": {**dict(t.params), "known_reason": found.reason},
                              "grouped_annotation": found.id}))
    return out
