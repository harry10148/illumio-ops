import pytest
import responses

from illumio_ops.domain.values import DeploymentType, ProbeName
from illumio_ops.pce.client import PceClient
from illumio_ops.pce.health import (
    health_status_from_body,
    pce_probe_category,
    probe_pce,
)

from .conftest import BASE, pce_settings

NOOP, HEALTH, NODE = (f"{BASE}/api/v2/{p}" for p in ("noop", "health", "node_available"))


@pytest.mark.parametrize(("status", "expected"), [
    (200, "ok"), (204, "ok"), (401, "auth_failed"), (403, "authorization_failed"),
    (429, "rate_limited"), (500, "server_error"), (0, "transport_error"), (404, "http_error"),
])
def test_pce_probe_category(status, expected):
    assert pce_probe_category(status) == expected


def test_health_status_from_body_list_picks_worst():
    assert health_status_from_body('[{"status":"normal"},{"status":"degraded"},{"status":"warning"}]') == "degraded"
    assert health_status_from_body('{"status":" Normal "}') == "normal"
    assert health_status_from_body("not json") == ""
    assert health_status_from_body("[]") == ""


def _client():
    return PceClient(pce_settings())


@responses.activate
def test_noop_401_stops_with_auth_failed():
    responses.add(responses.GET, NOOP, status=401)
    res = probe_pce(_client(), DeploymentType.ON_PREM)
    assert [(r.name, r.ok, r.status, r.category) for r in res] == [(ProbeName.NOOP, False, 401, "auth_failed")]


@responses.activate
def test_saas_probes_only_noop():
    responses.add(responses.GET, NOOP, status=204)
    res = probe_pce(_client(), DeploymentType.SAAS)
    assert [(r.name, r.ok) for r in res] == [(ProbeName.NOOP, True)]
    assert len(responses.calls) == 1


@responses.activate
def test_on_prem_all_healthy_including_node_available_202():
    responses.add(responses.GET, NOOP, status=204)
    responses.add(responses.GET, HEALTH, json=[{"status": "normal"}])
    responses.add(responses.GET, NODE, status=202)
    res = probe_pce(_client(), DeploymentType.ON_PREM)
    assert [(r.name, r.ok, r.category) for r in res] == [
        (ProbeName.NOOP, True, "ok"), (ProbeName.HEALTH, True, "ok"), (ProbeName.NODE_AVAILABLE, True, "ok")]


@responses.activate
def test_health_200_degraded_is_not_ok_and_stops():
    responses.add(responses.GET, NOOP, status=204)
    responses.add(responses.GET, HEALTH, json={"status": "degraded"})
    res = probe_pce(_client(), DeploymentType.ON_PREM)
    assert [(r.name, r.ok, r.category) for r in res][-1] == (ProbeName.HEALTH, False, "degraded")
    assert len(res) == 2


@responses.activate
def test_health_unparseable_body_is_unknown_not_healthy():
    responses.add(responses.GET, NOOP, status=204)
    responses.add(responses.GET, HEALTH, body=b"<html>")
    res = probe_pce(_client(), DeploymentType.ON_PREM)
    assert (res[-1].name, res[-1].ok, res[-1].category) == (ProbeName.HEALTH, False, "health_unknown")


@responses.activate
def test_health_204_is_endpoint_invalid():
    responses.add(responses.GET, NOOP, status=204)
    responses.add(responses.GET, HEALTH, status=204)
    res = probe_pce(_client(), DeploymentType.ON_PREM)
    assert (res[-1].ok, res[-1].category) == (False, "http_error")


@responses.activate
def test_node_available_404_fails():
    responses.add(responses.GET, NOOP, status=204)
    responses.add(responses.GET, HEALTH, json={"status": "normal"})
    responses.add(responses.GET, NODE, status=404)
    res = probe_pce(_client(), DeploymentType.ON_PREM)
    assert (res[-1].name, res[-1].ok, res[-1].status, res[-1].category) == (ProbeName.NODE_AVAILABLE, False, 404, "http_error")


def test_transport_error_becomes_probe_result():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    c = PceClient(pce_settings(url=f"http://127.0.0.1:{port}"))
    res = probe_pce(c, DeploymentType.ON_PREM)
    assert [(r.name, r.ok, r.status, r.category) for r in res] == [(ProbeName.NOOP, False, None, "refused")]
    assert res[0].detail_key
