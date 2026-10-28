"""The inventory keeps each VEN's heartbeat, policy sync and health (P5b-2 Task 1: the VEN status report)."""
import json

import pytest
import responses

from illumio_ops.services.collect.inventory import run_inventory_cycle
from illumio_ops.store.flowdb import workloads

from .conftest import NOW, configured_ctx
from .test_inventory import SUMMARY, WL, _workload

STATUS = {"status": "active", "last_heartbeat_on": "2026-10-24T08:40:00.000Z",
          "security_policy_sync_state": "syncing", "security_policy_refresh_at": "2026-10-24T08:00:00.000Z",
          "security_policy_applied_at": "2026-10-24T07:00:00.000Z", "managed_since": "2026-01-02T03:04:05.000Z",
          "fw_config_current": False, "agent_health": [{"type": "ven.out_of_sync", "severity": "warning"}]}


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    from illumio_ops.pce import collections
    monkeypatch.setattr(collections, "_sleep", lambda s: None)


def _row(ctx, href):
    with ctx.flows().connect() as conn:
        return next(w for w in workloads.all_workloads(conn) if w.href == href)


@responses.activate
def test_agent_status_fields_stored(tmp_path):
    ctx = configured_ctx(tmp_path)
    w = _workload(1, risk=None)
    w["agent"] = {"status": {**STATUS, "security_policy_received_at": "2026-10-24T08:30:00.000Z"}}
    responses.add(responses.GET, WL, json=[w])
    responses.add(responses.GET, SUMMARY, json={})
    run_inventory_cycle(ctx, now=NOW)
    r = _row(ctx, "/orgs/1/workloads/w-1")
    assert r.agent_status == "active" and r.policy_sync_state == "syncing" and r.fw_config_current == 0
    assert r.last_heartbeat_at.startswith("2026-10-24T08:40:00") and r.policy_received_at.startswith("2026-10-24T08:30")
    assert r.policy_applied_at.startswith("2026-10-24T07:00") and r.managed_since.startswith("2026-01-02T03:04:05")
    assert json.loads(r.agent_health_json) == [{"type": "ven.out_of_sync", "severity": "warning"}]


@responses.activate
def test_received_falls_back_to_refresh_at(tmp_path):
    ctx = configured_ctx(tmp_path)
    w = _workload(1, risk=None)
    w["agent"] = {"status": STATUS}
    responses.add(responses.GET, WL, json=[w])
    responses.add(responses.GET, SUMMARY, json={})
    run_inventory_cycle(ctx, now=NOW)
    assert _row(ctx, "/orgs/1/workloads/w-1").policy_received_at.startswith("2026-10-24T08:00")


@responses.activate
def test_unmanaged_has_no_agent_status(tmp_path):
    ctx = configured_ctx(tmp_path)
    responses.add(responses.GET, WL, json=[_workload(1, risk=None)])  # no "agent" block
    responses.add(responses.GET, SUMMARY, json={})
    run_inventory_cycle(ctx, now=NOW)
    r = _row(ctx, "/orgs/1/workloads/w-1")
    assert (r.agent_status, r.last_heartbeat_at, r.policy_sync_state, r.agent_health_json) == (None, None, None, None)


def test_old_rows_have_unknown_status(tmp_path):
    """A row written before the 0008 columns existed reads as unknown, not as offline or in sync."""
    ctx = configured_ctx(tmp_path)
    with ctx.flows().connect() as conn:
        conn.execute("INSERT INTO workloads (href, managed, fetched_at) VALUES ('/orgs/1/workloads/old', 1, 'x')")
        conn.commit()
        r = next(w for w in workloads.all_workloads(conn) if w.href == "/orgs/1/workloads/old")
    assert (r.agent_status, r.last_heartbeat_at, r.fw_config_current) == (None, None, None)
