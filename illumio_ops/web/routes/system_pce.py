"""System › PCE connection: view and edit the connection, run and read health probes."""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from flask import Blueprint
from pydantic import BaseModel, Field

from illumio_ops.domain.values import DeploymentType, ProbeName
from illumio_ops.pce.health import ProbeResult
from illumio_ops.services import pce_health
from illumio_ops.services.collect.reset import pce_target_changed, reset_for_new_pce
from illumio_ops.settings.secrets import MASK, redact
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


class PceConnectionUpdate(BaseModel):
    revision: int
    url: str = Field(max_length=2048)
    org_id: str = Field(max_length=32)
    api_key: str = Field(max_length=512)
    api_secret: str = Field(max_length=1024)
    deployment_type: DeploymentType
    console_url: str | None = Field(max_length=2048)
    verify_tls: bool | str


class PceReset(BaseModel):
    cleared: list[str]
    archive_moved_to: str | None


class PceConnectionSaved(PceConnection):
    # Set when the save pointed the product at another PCE and its collected data was cleared.
    reset: PceReset | None


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
    fields = body.model_dump(mode="json", exclude={"revision"})
    # A blank or masked secret means "keep what is saved": the form never receives
    # the real values, so it cannot send them back.
    kept = [k for k in ("api_key", "api_secret") if fields[k] in ("", MASK)]
    for k in kept:
        del fields[k]
    # ...except when the destination or its TLS check changes: otherwise anyone holding
    # a session could point the saved credentials at their own host and read them off
    # the next connection test.
    saved = get_ctx().settings.current().pce
    moved = (body.url.rstrip("/") != saved.url or body.verify_tls != saved.verify_tls)
    if kept and moved and (saved.api_key or saved.api_secret):
        raise ApiFailure(400, "credentials_required", "err_credentials_required", field="api_key")
    # The service account must be able to read the CA bundle (systemd hides /root and /home).
    if isinstance(body.verify_tls, str) and body.verify_tls.startswith("/") and not os.access(body.verify_tls, os.R_OK):
        raise ApiFailure(400, "ca_bundle_unreadable", "err_ca_bundle_unreadable", field="verify_tls")
    other_pce = (body.url.rstrip("/"), body.org_id, body.deployment_type) != (saved.url, saved.org_id,
                                                                                saved.deployment_type)

    def mutate(d: dict[str, Any]) -> None:
        d["pce"].update(fields)

    ctx = get_ctx()
    new = ctx.settings.update(body.revision, mutate).pce
    # Cleared only after the save succeeded: a rejected save must not cost the collected data.
    # In between, the collectors refuse to write (their database is still bound to the old PCE).
    reset = None
    if saved.url and pce_target_changed(saved, new):
        report = reset_for_new_pce(ctx)
        reset = PceReset(cleared=report.cleared, archive_moved_to=report.archive_moved_to)
    elif other_pce:
        pce_health.forget(ctx)
    return PceConnectionSaved(**_view().model_dump(), reset=reset)


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
