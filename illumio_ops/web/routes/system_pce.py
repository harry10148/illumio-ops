"""System › PCE connection: view and edit the connection, run and read health probes."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from flask import Blueprint
from pydantic import BaseModel, Field

from illumio_ops.domain.values import DeploymentType, ProbeName
from illumio_ops.pce.health import ProbeResult
from illumio_ops.services import pce_health
from illumio_ops.settings.secrets import MASK, redact
from illumio_ops.web.auth import get_ctx
from illumio_ops.web.contract import api_route, operation


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
OP_UPDATE = operation("system.pce.update", "PUT", "/api/system/pce", PceConnectionUpdate, PceConnection)
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
def update_connection(body: PceConnectionUpdate) -> PceConnection:
    fields = body.model_dump(mode="json", exclude={"revision"})
    # A blank or masked secret means "keep what is saved": the form never receives
    # the real values, so it cannot send them back.
    for secret in ("api_key", "api_secret"):
        if fields[secret] in ("", MASK):
            del fields[secret]

    def mutate(d: dict[str, Any]) -> None:
        d["pce"].update(fields)

    get_ctx().settings.update(body.revision, mutate)
    return _view()


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
