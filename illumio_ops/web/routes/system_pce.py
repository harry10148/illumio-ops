"""System › PCE connection: view and edit the connection, run and read health probes."""
from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any, Literal

from flask import Blueprint
from pydantic import BaseModel, Field, ValidationError

from illumio_ops.domain.values import DeploymentType, ProbeName
from illumio_ops.pce.health import ProbeResult
from illumio_ops.services import pce_health
from illumio_ops.services.collect import same_pce
from illumio_ops.services.collect.guard import normalize_target
from illumio_ops.services.collect.reset import (
    move_to_new_address,
    pce_target_changed,
    reset_for_new_pce,
)
from illumio_ops.settings.schema import PceSettings
from illumio_ops.settings.secrets import MASK, redact
from illumio_ops.store.flowdb import binding
from illumio_ops.store.flowdb.db import FlowDbBusy
from illumio_ops.web.auth import get_ctx
from illumio_ops.web.contract import ApiFailure, api_route, operation


class PceConnection(BaseModel):
    revision: int
    url: str
    org_id: str
    api_key: str
    api_secret: str
    deployment_type: DeploymentType
    console_url: str | None
    verify_tls: bool | str
    # Optional key with write access, used only to enable Rule Hit Count (spec §6.5, P5c-2).
    write_api_key: str
    write_api_secret: str
    events_timeout_seconds: int | None  # None: the default for the deployment type (pce.events)


class PceConnectionUpdate(BaseModel):
    revision: int
    url: str = Field(max_length=2048)
    org_id: str = Field(max_length=32)
    api_key: str = Field(max_length=512)
    api_secret: str = Field(max_length=1024)
    deployment_type: DeploymentType
    console_url: str | None = Field(max_length=2048)
    verify_tls: bool | str
    write_api_key: str = Field(default="", max_length=512)
    write_api_secret: str = Field(default="", max_length=1024)
    clear_write_key: bool = False
    # Left out: unchanged (a client from before the field keeps the saved value); null: the default.
    events_timeout_seconds: int | None = None
    # When only the address changes (same org) and data has been collected: "keep" — the same PCE at a new address,
    # verified before anything is saved; "clear" — another PCE, its data cleared (decision D3, spec §6.4).
    data_choice: Literal["keep", "clear"] | None = None


class PceReset(BaseModel):
    cleared: list[str]
    archive_moved_to: str | None


class PceConnectionSaved(PceConnection):
    # Set when the save pointed the product at another PCE and its collected data was cleared.
    reset: PceReset | None
    # The same PCE at a new address: its data was kept and now belongs to the new address.
    kept_data: bool = False


class ProbeItem(BaseModel):
    name: ProbeName
    ok: bool
    status: int | None
    category: str
    detail_key: str


class ProbeRun(BaseModel):
    checked_at: datetime
    results: list[ProbeItem]


class LatestProbe(BaseModel):
    run: ProbeRun | None


OP_GET = operation("system.pce.get", "GET", "/api/system/pce", None, PceConnection)
OP_UPDATE = operation("system.pce.update", "PUT", "/api/system/pce", PceConnectionUpdate, PceConnectionSaved)
OP_PROBE = operation("system.pce.probe", "POST", "/api/system/pce/probe", None, ProbeRun)
OP_LATEST = operation("system.pce.latest", "GET", "/api/system/pce/latest", None, LatestProbe)

bp = Blueprint("system_pce", __name__)


def _view() -> PceConnection:
    s = get_ctx().settings.current()
    return PceConnection(revision=s.revision, **{k: v for k, v in redact(s)["pce"].items()
                                                 if k in PceConnection.model_fields})


def _items(results: list[ProbeResult]) -> list[ProbeItem]:
    return [ProbeItem(name=r.name, ok=r.ok, status=r.status, category=r.category, detail_key=r.detail_key)
            for r in results]


@api_route(bp, OP_GET)
def get_connection() -> PceConnection:
    return _view()


@api_route(bp, OP_UPDATE)
def update_connection(body: PceConnectionUpdate) -> PceConnectionSaved:
    fields = body.model_dump(mode="json", exclude={"revision", "clear_write_key", "data_choice"})
    if "events_timeout_seconds" not in body.model_fields_set:
        del fields["events_timeout_seconds"]
    # A blank or masked secret means "keep what is saved": the form never receives
    # the real values, so it cannot send them back.
    kept = [k for k in ("api_key", "api_secret") if fields[k] in ("", MASK)]
    write_kept = [k for k in ("write_api_key", "write_api_secret") if fields[k] in ("", MASK)]
    for k in kept + write_kept:
        del fields[k]
    if body.clear_write_key:
        fields.update(write_api_key="", write_api_secret="")
    # ...except when the destination or its TLS check changes: otherwise anyone holding
    # a session could point the saved credentials at their own host and read them off
    # the next connection test.
    saved = get_ctx().settings.current().pce
    moved = (body.url.rstrip("/") != saved.url or body.verify_tls != saved.verify_tls)
    if kept and moved and (saved.api_key or saved.api_secret):
        raise ApiFailure(400, "credentials_required", "err_credentials_required", field="api_key")
    if write_kept and not body.clear_write_key and moved and (saved.write_api_key or saved.write_api_secret):
        raise ApiFailure(400, "credentials_required", "err_credentials_required", field="write_api_key")
    # The service account must be able to read the CA bundle (systemd hides /root and /home).
    if isinstance(body.verify_tls, str) and body.verify_tls.startswith("/") and not os.access(body.verify_tls, os.R_OK):
        raise ApiFailure(400, "ca_bundle_unreadable", "err_ca_bundle_unreadable", field="verify_tls")
    other_pce = (body.url.rstrip("/"), body.org_id, body.deployment_type) != (saved.url, saved.org_id,
                                                                                saved.deployment_type)

    def mutate(d: dict[str, Any]) -> None:
        d["pce"].update(fields)

    ctx = get_ctx()
    if saved.url and _new_address_of_bound_store(saved, body):
        if body.data_choice is None:
            raise ApiFailure(409, "pce_target_needs_choice", "err_pce_target_needs_choice", field="url",
                             params={"old": saved.url, "new": body.url.rstrip("/")})
        if body.data_choice == "keep":
            return _keep_for_new_address(body, saved, fields, mutate)
    elif (body.data_choice == "keep" and saved.url
          and normalize_target(saved.url, saved.org_id)[1] != normalize_target(body.url, body.org_id)[1]):
        raise ApiFailure(400, "pce_keep_needs_same_org", "err_pce_keep_needs_same_org", field="org_id")
    new = ctx.settings.update(body.revision, mutate).pce
    # Cleared only after the save succeeded: a rejected save must not cost the collected data.
    # In between, the collectors refuse to write (their database is still bound to the old PCE).
    reset = None
    if saved.url and pce_target_changed(saved, new):
        try:
            report = reset_for_new_pce(ctx)
        except FlowDbBusy:  # saved; the next collector run finishes the switch (finish_pending_switch)
            raise ApiFailure(503, "pce_switch_pending", "err_pce_switch_pending") from None
        reset = PceReset(cleared=report.cleared, archive_moved_to=report.archive_moved_to)
    elif other_pce:
        pce_health.forget(ctx)
    return PceConnectionSaved(**_view().model_dump(), reset=reset)


def _bound() -> bool:
    with get_ctx().flows().connect() as conn:
        return binding.current(conn) is not None


def _new_address_of_bound_store(saved: PceSettings, body: PceConnectionUpdate) -> bool:
    """Only the address changes (same org) and data has been collected for the saved one: the operator says whether it
    is the same PCE (keep) or another (clear)."""
    old_url, old_org = normalize_target(saved.url, saved.org_id)
    new_url, new_org = normalize_target(body.url, body.org_id)
    return old_org == new_org and old_url != new_url and _bound()


def _keep_for_new_address(body: PceConnectionUpdate, saved: PceSettings, fields: dict[str, Any],
                          mutate: Any) -> PceConnectionSaved:
    """Verify that the new address is the same PCE before anything is saved; then save and rebind in one hold of the
    flow database's write lock, so no collector clears the data in between (finish_pending_switch re-checks)."""
    ctx = get_ctx()
    try:
        candidate = PceSettings.model_validate({**saved.model_dump(mode="json"), **fields})
    except ValidationError:
        candidate = None  # the save below reports the field, nothing is verified or written
    if candidate is not None:
        try:
            same_pce.verify(ctx, candidate)
        except same_pce.NothingToCompare:
            raise ApiFailure(409, "pce_same_unverifiable", "err_pce_same_nothing_to_compare") from None
        except same_pce.Unverifiable as exc:
            raise ApiFailure(409, "pce_same_unverifiable", "err_pce_same_unverifiable",
                             params={"reason": exc.reason}) from None
        except same_pce.NotTheSame as exc:
            raise ApiFailure(409, "pce_not_the_same", "err_pce_not_the_same",
                             params={"n": str(exc.asked)}) from None
    fdb = ctx.flows()
    with fdb.writing(fdb.generation) as conn:
        new = ctx.settings.update(body.revision, mutate).pce
        move_to_new_address(ctx, conn, saved, new, now=datetime.now(UTC))
    return PceConnectionSaved(**_view().model_dump(), reset=None, kept_data=True)


@api_route(bp, OP_PROBE)
def probe() -> ProbeRun:
    ctx = get_ctx()
    pce_health.run_probe(ctx)
    stored = pce_health.latest(ctx)
    if stored is None:
        raise RuntimeError("probe ran but no result was stored")
    return ProbeRun(checked_at=stored[0], results=_items(stored[1]))


@api_route(bp, OP_LATEST)
def latest_probe() -> LatestProbe:
    stored = pce_health.latest(get_ctx())
    if stored is None:
        return LatestProbe(run=None)
    return LatestProbe(run=ProbeRun(checked_at=stored[0], results=_items(stored[1])))
