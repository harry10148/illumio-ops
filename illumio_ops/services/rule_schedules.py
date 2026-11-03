"""Rule scheduling (UI redesign spec §4.5; 5.x rule_scheduler semantics): schedules kept per PCE, and the engine the
rule_schedules_tick job runs every five minutes — each schedule's desired state (domain.rule_schedule) against the
PCE's, switched on the draft and provisioned with the optional write key when they differ.

Kept from 5.x: a target or its rule set with an unprovisioned draft is skipped this round (no switch on top of a
change nobody reviewed); a target the PCE no longer has is marked deleted and the others go on; an expiry is removed
only once the target is disabled and provisioned (5.x review BUG-1); the fixed-English note in the description is
written when a schedule is made and removed when it ends. The PCE's refusals are recorded as it gave them."""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal, cast

from loguru import logger
from pydantic import BaseModel, Field, TypeAdapter

from illumio_ops.domain.rule_schedule import (
    Expiry,
    Plan,
    Weekly,
    desired,
    next_change,
    preview,
    strip_notes,
    with_note,
)
from illumio_ops.pce import policy_write as pw
from illumio_ops.pce.client import (
    PceBudgetExhausted,
    PceClient,
    PceResponse,
    PceTransportError,
)
from illumio_ops.services.context import AppContext
from illumio_ops.store import rule_schedules as store

RUNS_KEEP = timedelta(days=30)
PROVISION_NOTE = "illumio-ops rule schedule"
DETAIL_MAX = 300
PCE_ERRORS = (PceTransportError, PceBudgetExhausted, pw.PolicyReadError)

PlanField = Annotated[Weekly | Expiry, Field(discriminator="kind")]
_PLAN: TypeAdapter[Weekly | Expiry] = TypeAdapter(cast(Any, PlanField))


class NoWriteKey(Exception):
    """The write key is not set: nothing can be written."""


class DraftPending(Exception):
    """The target or its rule set has a change not yet provisioned."""


class NotProvisioned(Exception):
    """The target is not in the active policy."""


class AlreadyScheduled(Exception):
    """The target already has a schedule."""


class PceRefused(Exception):
    def __init__(self, status: int | None, detail: str) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status
        self.detail = detail


class RunView(BaseModel):
    at: datetime
    schedule_id: int | None
    name: str
    action: str
    result: str
    status: int | None
    detail: str | None


class ScheduleView(BaseModel):
    id: int
    href: str
    is_ruleset: bool
    name: str
    ruleset_name: str
    summary: str
    plan: PlanField
    paused: bool
    pce_status: Literal["active", "deleted", "unknown"]
    live: Literal["enabled", "disabled", "unknown"]
    last_checked_at: datetime | None
    last_run: RunView | None
    next_change: datetime | None
    preview_key: str
    preview_params: dict[str, str]


class ScheduleOverview(BaseModel):
    schedules: int
    switched_24h: int
    failed_24h: int
    skipped_now: int  # schedules whose latest check was skipped for a pending draft
    next_change: datetime | None
    write_key: bool


class TickResult(BaseModel):
    checked: int = 0
    switched: int = 0
    failed: int = 0
    skipped: int = 0


class DeleteResult(BaseModel):
    note_cleared: bool
    provisioned: bool
    status: int | None
    detail: str | None


def plan_of(raw: str) -> Plan:
    return _PLAN.validate_json(raw)


def _detail(r: PceResponse) -> str:
    return r.body.decode("utf-8", errors="replace")[:DETAIL_MAX]


def _has_key(ctx: AppContext) -> bool:
    p = ctx.settings.current().pce
    return bool(p.write_api_key and p.write_api_secret)


def _ident(ctx: AppContext) -> tuple[str, str]:
    p = ctx.settings.current().pce
    return p.url, p.org_id


def _run(ctx: AppContext, row: sqlite3.Row | None, *, href: str, name: str, at: datetime, action: store.Action,
         result: store.Result, status: int | None = None, detail: str | None = None) -> None:
    url, org = _ident(ctx) if row is None else (row["pce_url"], row["org_id"])
    with ctx.db() as conn:
        store.add_run(conn, pce_url=url, org_id=org, schedule_id=row["id"] if row is not None else None, href=href,
                      name=name, at=at, action=action, result=result, status=status, detail=detail)
        conn.commit()


def _checked(ctx: AppContext, row: sqlite3.Row, *, pce_status: str, live: str, at: datetime) -> None:
    with ctx.db() as conn:
        store.set_checked(conn, row["id"], pce_status=pce_status, live=live, at=at)
        conn.commit()


def _switch(client: PceClient, href: str, enabled: bool) -> PceResponse | None:
    """Enable or disable on the draft and provision; None when done, else the PCE's refusing answer. When the PCE
    would need other unprovisioned objects to go live with it, the draft is put back and DependenciesPending raised."""
    r = pw.set_fields(client, href, {"enabled": enabled})
    if r.status != 204:
        return r
    try:
        p = pw.provision(client, pw.ruleset_of(href), PROVISION_NOTE)
    except pw.DependenciesPending:
        pw.set_fields(client, href, {"enabled": not enabled})
        raise
    return None if p.status == 201 else p


def _clear_note(client: PceClient, href: str, draft: PceResponse) -> PceResponse | None:
    desc = str((draft.json() or {}).get("description") or "")
    clean = strip_notes(desc)
    if clean == desc:
        return None
    r = pw.set_fields(client, href, {"description": clean})
    if r.status != 204:
        return r
    try:
        p = pw.provision(client, pw.ruleset_of(href), PROVISION_NOTE)
    except pw.DependenciesPending:
        return None  # cleared in the draft; provisioning it would take others' changes live
    return None if p.status == 201 else p


Outcome = Literal["switched", "failed", "skipped", "none"]


def _check_one(ctx: AppContext, client: PceClient, row: sqlite3.Row, at: datetime) -> Outcome:
    href, name = row["href"], row["name"]
    plan = plan_of(row["plan_json"])
    draft = pw.get_draft(client, href)
    if draft.status == 404:
        if row["pce_status"] != "deleted":
            _run(ctx, row, href=href, name=name, at=at, action="not_found", result="skipped", status=404)
        _checked(ctx, row, pce_status="deleted", live="unknown", at=at)
        return "skipped"
    if draft.status != 200:
        _run(ctx, row, href=href, name=name, at=at, action="error", result="failed", status=draft.status,
             detail=_detail(draft))
        return "failed"
    if pw.draft_pending(client, href):
        with ctx.db() as conn:
            last = store.last_run(conn, row["id"])
        if last is None or last["action"] != "skip_draft":  # once while it stays so, not every five minutes
            _run(ctx, row, href=href, name=name, at=at, action="skip_draft", result="skipped")
        return "skipped"
    want = desired(plan, at)
    try:
        return _apply(ctx, client, row, plan, draft, want, at)
    except pw.DependenciesPending as dep:
        _run(ctx, row, href=href, name=name, at=at, action="skip_draft", result="skipped",
             detail="needs unprovisioned objects: " + ", ".join(dep.hrefs))
        return "skipped"


def _apply(ctx: AppContext, client: PceClient, row: sqlite3.Row, plan: Plan, draft: PceResponse,
           want: bool | Literal["expired"], at: datetime) -> Outcome:
    href, name = row["href"], row["name"]
    if want == "expired":
        refused = _switch(client, href, False)
        if refused is not None:
            _run(ctx, row, href=href, name=name, at=at, action="expire", result="failed", status=refused.status,
                 detail=_detail(refused))
            return "failed"
        note = _clear_note(client, href, draft)
        with ctx.db() as conn:
            store.delete(conn, row["id"])
            conn.commit()
        _run(ctx, None, href=href, name=name, at=at, action="expire", result="ok",
             detail=None if note is None else f"note not cleared: HTTP {note.status} {_detail(note)}")
        return "switched"
    active = pw.get_active(client, href)
    if active.status == 404:  # in the draft but not provisioned: nothing to switch
        _checked(ctx, row, pce_status="unknown", live="unknown", at=at)
        return "skipped"
    if active.status != 200:
        _run(ctx, row, href=href, name=name, at=at, action="error", result="failed", status=active.status,
             detail=_detail(active))
        return "failed"
    live = bool((active.json() or {}).get("enabled"))
    _checked(ctx, row, pce_status="active", live="enabled" if live else "disabled", at=at)
    if live == want:
        return "none"
    action: store.Action = "enable" if want else "disable"
    refused = _switch(client, href, bool(want))
    if refused is not None:
        _run(ctx, row, href=href, name=name, at=at, action=action, result="failed", status=refused.status,
             detail=_detail(refused))
        return "failed"
    _checked(ctx, row, pce_status="active", live="enabled" if want else "disabled", at=at)
    _run(ctx, row, href=href, name=name, at=at, action=action, result="ok")
    return "switched"


def tick(ctx: AppContext, *, now: datetime | None = None) -> TickResult:
    at = (now or datetime.now(UTC)).astimezone(UTC)
    out = TickResult()
    if not _has_key(ctx):
        return out  # the page says so; nothing can be written
    cfg = ctx.settings.current().pce
    ident = (cfg.url, cfg.org_id)
    with ctx.db() as conn:
        store.prune_runs(conn, at - RUNS_KEEP)
        rows = [r for r in store.list_for(conn, pce_url=cfg.url, org_id=cfg.org_id) if not r["paused"]]
        conn.commit()
    if not rows:
        return out
    with ctx.pce_write_client(cfg) as client:
        for row in rows:
            if _ident(ctx) != ident:
                logger.info("rule schedules: the PCE changed during the check; the rest waits for the next run")
                break
            out.checked += 1
            try:
                result = _check_one(ctx, client, row, at)
            except PCE_ERRORS as exc:
                _run(ctx, row, href=row["href"], name=row["name"], at=at, action="error", result="failed",
                     status=getattr(exc, "status", None), detail=f"{type(exc).__name__}: {exc}")
                result = "failed"
            if result == "switched":
                out.switched += 1
            elif result == "failed":
                out.failed += 1
            elif result == "skipped":
                out.skipped += 1
    return out


def _view(conn: sqlite3.Connection, row: sqlite3.Row, at: datetime) -> ScheduleView:
    plan = plan_of(row["plan_json"])
    last = store.last_run(conn, row["id"])
    key, params = preview(plan)
    return ScheduleView(
        id=row["id"], href=row["href"], is_ruleset=bool(row["is_ruleset"]), name=row["name"],
        ruleset_name=row["ruleset_name"], summary=row["summary"], plan=plan, paused=bool(row["paused"]),
        pce_status=row["pce_status"], live=row["live"],
        last_checked_at=datetime.fromisoformat(row["last_checked_at"]) if row["last_checked_at"] else None,
        last_run=None if last is None else _run_view(last), next_change=None if row["paused"] else next_change(plan, at),
        preview_key=key, preview_params=params)


def _run_view(r: sqlite3.Row) -> RunView:
    return RunView(at=datetime.fromisoformat(r["at"]), schedule_id=r["schedule_id"], name=r["name"],
                   action=r["action"], result=r["result"], status=r["status"], detail=r["detail"])


def schedules(ctx: AppContext, *, now: datetime | None = None) -> tuple[ScheduleOverview, list[ScheduleView]]:
    at = (now or datetime.now(UTC)).astimezone(UTC)
    url, org = _ident(ctx)
    with ctx.db() as conn:
        views = [_view(conn, r, at) for r in store.list_for(conn, pce_url=url, org_id=org)]
        recent = [r for r in store.runs(conn, pce_url=url, org_id=org, limit=1000)
                  if datetime.fromisoformat(r["at"]) >= at - timedelta(hours=24)]
    nexts = [v.next_change for v in views if v.next_change is not None]
    return ScheduleOverview(
        schedules=len(views),
        switched_24h=sum(1 for r in recent if r["result"] == "ok" and r["action"] in ("enable", "disable", "expire")),
        failed_24h=sum(1 for r in recent if r["result"] == "failed"),
        skipped_now=sum(1 for v in views if v.last_run is not None and v.last_run.action == "skip_draft"),
        next_change=min(nexts, default=None), write_key=_has_key(ctx)), views


def runs(ctx: AppContext, *, schedule_id: int | None = None, limit: int = 200) -> list[RunView]:
    url, org = _ident(ctx)
    with ctx.db() as conn:
        return [_run_view(r) for r in store.runs(conn, pce_url=url, org_id=org, limit=limit, schedule_id=schedule_id)]


def _own(ctx: AppContext, schedule_id: int) -> sqlite3.Row:
    url, org = _ident(ctx)
    with ctx.db() as conn:
        row = store.get(conn, schedule_id)
    if row is None or (row["pce_url"], row["org_id"]) != (url, org):
        raise LookupError(schedule_id)
    return row


def _write_note(client: PceClient, href: str, plan: Plan) -> None:
    """DraftPending (the description put back) when provisioning would take other unprovisioned objects live."""
    draft = pw.get_draft(client, href)
    if draft.status != 200:
        raise PceRefused(draft.status, _detail(draft))
    desc = str((draft.json() or {}).get("description") or "")
    r = pw.set_fields(client, href, {"description": with_note(desc, plan)})
    if r.status != 204:
        raise PceRefused(r.status, _detail(r))
    try:
        p = pw.provision(client, pw.ruleset_of(href), PROVISION_NOTE)
    except pw.DependenciesPending:
        pw.set_fields(client, href, {"description": desc})
        raise DraftPending from None
    if p.status != 201:
        raise PceRefused(p.status, _detail(p))


def create(ctx: AppContext, *, href: str, plan: Plan, name: str, ruleset_name: str, summary: str, by: str,
           now: datetime | None = None) -> ScheduleView:
    """Raises NoWriteKey, AlreadyScheduled, NotProvisioned, DraftPending, PceRefused (nothing saved then)."""
    at = (now or datetime.now(UTC)).astimezone(UTC)
    if not _has_key(ctx):
        raise NoWriteKey
    cfg = ctx.settings.current().pce
    href = pw.active_href(href)
    with ctx.db() as conn:
        if store.by_href(conn, pce_url=cfg.url, org_id=cfg.org_id, href=href) is not None:
            raise AlreadyScheduled
    with ctx.pce_write_client(cfg) as client:
        try:
            active = pw.get_active(client, href)
            if active.status == 404:
                raise NotProvisioned
            if active.status != 200:
                raise PceRefused(active.status, _detail(active))
            if pw.draft_pending(client, href):
                raise DraftPending
            _write_note(client, href, plan)
        except PCE_ERRORS as exc:
            raise PceRefused(getattr(exc, "status", None), f"{type(exc).__name__}: {exc}") from None
    live = "enabled" if (active.json() or {}).get("enabled") else "disabled"
    with ctx.db() as conn:
        sid = store.create(conn, pce_url=cfg.url, org_id=cfg.org_id, href=href, is_ruleset=pw.is_ruleset(href),
                           name=name, ruleset_name=ruleset_name, summary=summary, plan_json=plan.model_dump_json(),
                           paused=False, pce_status="active", by=by, at=at)
        store.set_checked(conn, sid, pce_status="active", live=live, at=at)
        conn.commit()
        row = store.get(conn, sid)
    assert row is not None
    _run(ctx, row, href=href, name=name, at=at, action="note", result="ok")
    with ctx.db() as conn:
        return _view(conn, row, at)


def update(ctx: AppContext, schedule_id: int, plan: Plan, *, now: datetime | None = None) -> ScheduleView:
    at = (now or datetime.now(UTC)).astimezone(UTC)
    row = _own(ctx, schedule_id)
    if not _has_key(ctx):
        raise NoWriteKey
    with ctx.pce_write_client(ctx.settings.current().pce) as client:
        try:
            if pw.draft_pending(client, row["href"]):
                raise DraftPending
            _write_note(client, row["href"], plan)
        except PCE_ERRORS as exc:
            raise PceRefused(getattr(exc, "status", None), f"{type(exc).__name__}: {exc}") from None
    with ctx.db() as conn:
        store.update_plan(conn, schedule_id, plan.model_dump_json(), at)
        conn.commit()
        fresh = store.get(conn, schedule_id)
        assert fresh is not None
        return _view(conn, fresh, at)


def set_paused(ctx: AppContext, schedule_id: int, paused: bool, *, now: datetime | None = None) -> ScheduleView:
    """Local only: a paused schedule is not checked; the PCE is not touched."""
    at = (now or datetime.now(UTC)).astimezone(UTC)
    _own(ctx, schedule_id)
    with ctx.db() as conn:
        store.set_paused(conn, schedule_id, paused, at)
        conn.commit()
        row = store.get(conn, schedule_id)
        assert row is not None
        return _view(conn, row, at)


def delete(ctx: AppContext, schedule_id: int, *, by: str, now: datetime | None = None) -> DeleteResult:
    """The note is cleared from the description (and provisioned unless another change is pending there); the
    schedule goes either way, and the result says what the PCE did."""
    at = (now or datetime.now(UTC)).astimezone(UTC)
    row = _own(ctx, schedule_id)
    out = DeleteResult(note_cleared=False, provisioned=False, status=None, detail="no_write_key")
    if _has_key(ctx):
        with ctx.pce_write_client(ctx.settings.current().pce) as client:
            try:
                draft = pw.get_draft(client, row["href"])
                if draft.status != 200:
                    out = DeleteResult(note_cleared=False, provisioned=False, status=draft.status,
                                       detail=_detail(draft))
                else:
                    pending = pw.draft_pending(client, row["href"])
                    desc = str((draft.json() or {}).get("description") or "")
                    r = pw.set_fields(client, row["href"], {"description": strip_notes(desc)})
                    if r.status != 204:
                        out = DeleteResult(note_cleared=False, provisioned=False, status=r.status, detail=_detail(r))
                    elif pending:  # someone's change waits in that draft: leave provisioning to them
                        out = DeleteResult(note_cleared=True, provisioned=False, status=None, detail="draft_pending")
                    else:
                        try:
                            p = pw.provision(client, pw.ruleset_of(row["href"]), PROVISION_NOTE)
                        except pw.DependenciesPending as dep:  # cleared in the draft; leave provisioning to people
                            out = DeleteResult(note_cleared=True, provisioned=False, status=None,
                                               detail="needs unprovisioned objects: " + ", ".join(dep.hrefs))
                            p = None
                        if p is not None:
                            out = DeleteResult(note_cleared=True, provisioned=p.status == 201,
                                               status=None if p.status == 201 else p.status,
                                               detail=None if p.status == 201 else _detail(p))
            except PCE_ERRORS as exc:
                out = DeleteResult(note_cleared=False, provisioned=False, status=getattr(exc, "status", None),
                                   detail=f"{type(exc).__name__}: {exc}")
    with ctx.db() as conn:
        store.delete(conn, schedule_id)
        conn.commit()
    _run(ctx, None, href=row["href"], name=row["name"], at=at, action="note_cleared",
         result="ok" if out.note_cleared else "failed", status=out.status, detail=f"by {by}; {out.detail or ''}".strip("; "))
    return out

