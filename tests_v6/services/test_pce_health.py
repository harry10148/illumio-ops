import pytest
import responses

from illumio_ops.domain.values import ProbeName
from illumio_ops.pce.client import PceNotConfigured
from illumio_ops.services import pce_health
from tests_v6.web.conftest import make_ctx

BASE = "https://pce.example.com:8443"


def _configure(ctx, **pce):
    values = {"url": BASE, "org_id": "1", "api_key": "k", "api_secret": "s"} | pce
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["pce"].update(values))


def test_probe_unconfigured_raises_and_writes_nothing(tmp_path):
    ctx = make_ctx(tmp_path)
    with pytest.raises(PceNotConfigured):
        pce_health.run_probe(ctx)
    assert pce_health.latest(ctx) is None


@responses.activate
def test_probe_writes_latest(tmp_path):
    ctx = make_ctx(tmp_path)
    _configure(ctx, deployment_type="saas")
    responses.add(responses.GET, f"{BASE}/api/v2/noop", status=204)
    results = pce_health.run_probe(ctx)
    assert [(r.name, r.ok) for r in results] == [(ProbeName.NOOP, True)]
    checked_at, stored = pce_health.latest(ctx)
    assert stored == results and checked_at.tzinfo is not None


@responses.activate
def test_second_probe_replaces_the_first(tmp_path):
    ctx = make_ctx(tmp_path)
    _configure(ctx, deployment_type="saas")
    responses.add(responses.GET, f"{BASE}/api/v2/noop", status=204)
    responses.add(responses.GET, f"{BASE}/api/v2/noop", status=401)
    pce_health.run_probe(ctx)
    pce_health.run_probe(ctx)
    _, stored = pce_health.latest(ctx)
    assert [(r.ok, r.category) for r in stored] == [(False, "auth_failed")]
    with ctx.db() as conn:
        assert conn.execute("SELECT count(*) FROM pce_probe").fetchone()[0] == 1


@responses.activate
def test_probe_of_previous_pce_is_not_written_after_switch(tmp_path):
    ctx = make_ctx(tmp_path)
    _configure(ctx, deployment_type="saas")

    def switch_while_answering(request):
        _configure(ctx, url="https://other.example.com:8443", org_id="2")
        return (204, {}, "")

    responses.add_callback(responses.GET, f"{BASE}/api/v2/noop", callback=switch_while_answering)
    pce_health.run_probe(ctx)
    assert pce_health.latest(ctx) is None


@responses.activate
def test_latest_ignores_result_of_other_pce(tmp_path):
    ctx = make_ctx(tmp_path)
    _configure(ctx, deployment_type="saas")
    responses.add(responses.GET, f"{BASE}/api/v2/noop", status=204)
    pce_health.run_probe(ctx)
    assert pce_health.latest(ctx) is not None
    _configure(ctx, org_id="2")  # same host, another organization
    assert pce_health.latest(ctx) is None
