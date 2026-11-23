"""VEN fleet traffic update rate writes and their history."""
import base64
import json
import re
from datetime import UTC, datetime, timedelta

import pytest
import responses

from illumio_ops.services import fleet_write
from illumio_ops.store import fleet_actions as action_store
from illumio_ops.store.flowdb import workloads
from tests.services.collect.conftest import configured_ctx

NOW = datetime(2026, 10, 27, 1, tzinfo=UTC)
API = "https://pce.example.com:8443/api/v2"
VIS, IDLE = (f"/orgs/1/workloads/{n}" for n in ("db", "idle-01"))


def _wl(href, hostname, mode, label_set=None):
    return workloads.WorkloadRow(
        href=href, hostname=hostname, name=None, managed=1, enforcement_mode=mode, visibility_level=None, os_id=None,
        ven_version=None, ven_href=None, label_set=label_set, online=1, risk_exposure=None, risk_percent=None,
        risk_updated_at=None, fetched_at=NOW.strftime("%Y-%m-%dT%H:%M:%S.000Z"), last_heartbeat_at=(NOW - timedelta(minutes=3)).strftime(
            "%Y-%m-%dT%H:%M:%S.000Z"))


def _ctx(tmp_path, *, write=True):
    c = configured_ctx(tmp_path, mode="full")
    if write:
        c.settings.update(c.settings.current().revision,
                          lambda d: d["pce"].update(write_api_key="wk", write_api_secret="ws"))
    with c.flows().connect() as conn:
        workloads.replace_inventory(conn, [_wl(VIS, "db", "visibility_only"), _wl(IDLE, "idle-01", "idle")])
        conn.commit()
    return c


@pytest.fixture
def ctx(tmp_path):
    return _ctx(tmp_path)


def _user(call):
    return base64.b64decode(call.request.headers["Authorization"].split()[1]).decode().split(":")[0]


def _rows(ctx):
    with ctx.db() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM fleet_actions ORDER BY id")]


def test_no_write_key_refuses_and_records(tmp_path):
    ctx = _ctx(tmp_path, write=False)
    with pytest.raises(fleet_write.NoWriteKey):
        fleet_write.increase_rate(ctx, [VIS], by="a", now=NOW)
    assert [(r["result"], r["detail"]) for r in _rows(ctx)] == [("refused", "no_write_key")]


# ── traffic update rate ──────────────────────────────────────────────────────

@responses.activate
def test_increase_rate_one_call_for_the_batch_with_the_write_key(ctx):
    responses.add(responses.POST, f"{API}/orgs/1/workloads/set_flow_reporting_frequency", status=204)
    out = fleet_write.increase_rate(ctx, [VIS, IDLE, "ip:10.0.0.9"], by="admin", now=NOW)
    assert [(r.key, r.status) for r in out.results] == [("ip:10.0.0.9", "skipped"), (VIS, "ok"), (IDLE, "ok")]
    [call] = responses.calls
    assert json.loads(call.request.body) == {"workloads": [{"href": VIS}, {"href": IDLE}]} and _user(call) == "wk"
    assert out.until == NOW + timedelta(minutes=10)
    assert sorted(r["result"] for r in _rows(ctx) if r["action"] == "traffic_rate") == ["ok", "ok", "skipped"]


@responses.activate
def test_increase_rate_refused_says_so_for_every_host(ctx):
    responses.add(responses.POST, re.compile(r".*/set_flow_reporting_frequency"), status=406,
                  json=[{"token": "invalid_uri"}])
    out = fleet_write.increase_rate(ctx, [VIS, IDLE], by="admin", now=NOW)
    assert {r.status for r in out.results} == {"failed"} and out.until is None
    assert "406" in (out.results[0].detail or "")


@responses.activate
def test_history_keeps_old_enforcement_rows_and_reads_this_pce_newest_first(ctx):
    with ctx.db() as conn:
        action_store.add(conn, pce_url="https://pce.example.com:8443", org_id="1", batch_id="old-batch",
                         at=NOW - timedelta(days=1), by="admin", action="enforcement", workload_href=VIS,
                         hostname="db", previous_mode="visibility_only", target_mode="full", result="ok", detail=None)
    responses.add(responses.POST, re.compile(r".*/set_flow_reporting_frequency"), status=204)
    fleet_write.increase_rate(ctx, [VIS], by="admin", now=NOW)
    h = fleet_write.history(ctx)
    assert [(a.action, a.previous_mode, a.target_mode, a.result) for a in h] == [
        ("traffic_rate", None, None, "ok"), ("enforcement", "visibility_only", "full", "ok")]
