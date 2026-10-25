"""PCE health probes. Order and stop rules ported from 5.x src/analyzer.py (health cycle).

noop (authenticated, every deployment) -> on-prem only: /health must be 200 with
a body status that is known and not bad -> /node_available must be 200 or 202.
The first failing probe ends the run.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from illumio_ops.domain.values import DeploymentType, ProbeName
from illumio_ops.pce.client import PceClient, PceTransportError

_HEALTH_BAD_ORDER = ("critical", "error", "degraded", "warning")

# i18n keys for every category a probe can end in (literal strings: the dictionary gate reads them).
DETAIL_KEYS: dict[str, str] = {
    "ok": "probe_ok",
    "auth_failed": "probe_auth_failed",
    "authorization_failed": "probe_authorization_failed",
    "rate_limited": "probe_rate_limited",
    "server_error": "probe_server_error",
    "http_error": "probe_http_error",
    "transport_error": "probe_transport_other",
    "dns": "probe_transport_dns",
    "refused": "probe_transport_refused",
    "timeout": "probe_transport_timeout",
    "tls": "probe_transport_tls",
    "ca_bundle": "probe_transport_ca_bundle",
    "other": "probe_transport_other",
    "health_unknown": "probe_health_unknown",
    "warning": "probe_health_bad",
    "degraded": "probe_health_bad",
    "error": "probe_health_bad",
    "critical": "probe_health_bad",
}


@dataclass(frozen=True)
class ProbeResult:
    name: ProbeName
    ok: bool
    status: int | None
    category: str
    detail_key: str


def pce_probe_category(status: int) -> str:
    if 200 <= status < 300:
        return "ok"
    return {0: "transport_error", 401: "auth_failed", 403: "authorization_failed", 429: "rate_limited"}.get(
        status, "server_error" if 500 <= status < 600 else "http_error")


def _endpoint_category(status: int, accepted: tuple[int, ...]) -> str:
    """An endpoint-invalid 2xx (e.g. 204 from /health) is not success."""
    cat = pce_probe_category(status)
    return "http_error" if cat == "ok" and status not in accepted else cat


def health_status_from_body(text: str) -> str:
    """Status string from a /api/v2/health body; '' when unparseable (unknown, never healthy)."""
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return ""
    if isinstance(data, dict):
        return str(data.get("status") or "").strip().lower()
    if isinstance(data, list):
        statuses = [str(n.get("status") or "").strip().lower() for n in data if isinstance(n, dict)]
        statuses = [s for s in statuses if s]
        for bad in _HEALTH_BAD_ORDER:
            if bad in statuses:
                return bad
        return statuses[0] if statuses else ""
    return ""


def _result(name: ProbeName, status: int | None, category: str) -> ProbeResult:
    return ProbeResult(name, category == "ok", status, category, DETAIL_KEYS[category])


def probe_pce(client: PceClient, deployment: DeploymentType) -> list[ProbeResult]:
    out: list[ProbeResult] = []
    for name, path, accepted in (
        (ProbeName.NOOP, "/noop", None),
        (ProbeName.HEALTH, "/health", (200,)),
        (ProbeName.NODE_AVAILABLE, "/node_available", (200, 202)),
    ):
        try:
            r = client.request("GET", path, org_scoped=False, timeout=10)
        except PceTransportError as exc:
            out.append(_result(name, None, exc.kind))
            return out
        category = pce_probe_category(r.status) if accepted is None else _endpoint_category(r.status, accepted)
        if category == "ok" and name is ProbeName.HEALTH:
            body = health_status_from_body(r.body.decode("utf-8", errors="replace"))
            if body == "":
                category = "health_unknown"
            elif body in _HEALTH_BAD_ORDER:
                category = body
        out.append(_result(name, r.status, category))
        if category != "ok" or deployment is DeploymentType.SAAS:
            return out
    return out
