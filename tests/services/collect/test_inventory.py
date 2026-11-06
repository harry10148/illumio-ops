"""Inventory and ransomware protection collection."""
from datetime import timedelta

import pytest
import responses

from illumio_ops.domain.values import IngestSource
from illumio_ops.services.collect import inventory
from illumio_ops.services.collect.inventory import (
    run_inventory_cycle,
    visibility_summary,
)
from illumio_ops.store.flowdb import capabilities, ingest_state

from .conftest import NOW, configured_ctx

API = "https://pce.example.com:8443/api/v2"
WL = f"{API}/orgs/1/workloads"
SUMMARY = f"{API}/orgs/1/reports/risk_summary"


def _workload(i, *, risk="critical", updated="2026-10-24T08:49:37Z", visibility="flow_summary"):
    return {
        "href": f"/orgs/1/workloads/w-{i}", "hostname": f"host-{i}", "name": None, "managed": True,
        "enforcement_mode": "visibility_only", "visibility_level": visibility, "os_id": "ubuntu-x86_64-noble",
        "online": True, "labels": [{"key": "app", "value": "Fin"}, {"key": "env", "value": "Prod"}],
        "ven": {"href": f"/orgs/1/vens/v-{i}", "version": "26.2.20-2063", "status": "active"},
        "risk_summary": None if risk is None else {"ransomware": {"workload_exposure_severity": risk,
                                                                  "ransomware_protection_percent": 0.0,
                                                                  "last_updated_at": updated}},
    }


def _details(n=3):
    return {"risk_details": {"ransomware": {"last_updated_at": "2026-10-24T08:49:37Z", "details": [
        {"href": f"/orgs/1/sec_policy/active/services/{k}", "name": f"S-{k}", "port": 445 + k, "proto": 6,
         "severity": "critical", "category": "admin", "protection_state": "unprotected",
         "port_status": "listening", "active_policy": "allowed", "draft_policy": "allowed",
         "recommendation": "", "os_platforms": ["windows"]} for k in range(n)]}}}


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    from illumio_ops.pce import collections
    monkeypatch.setattr(collections, "_sleep", lambda s: None)


def _rows(ctx, sql, *args):
    with ctx.flows().connect() as conn:
        return [dict(r) for r in conn.execute(sql, args)]


def _risk_calls():
    return [c for c in responses.calls if c.request.url.endswith("/risk_details")]


@responses.activate
def test_inventory_writes_visibility_and_risk(tmp_path):
    ctx = configured_ctx(tmp_path)
    responses.add(responses.GET, WL, json=[_workload(1), _workload(2, risk=None, visibility="flow_drops")])
    responses.add(responses.GET, SUMMARY, json={"ransomware": {"ransomware_protection_coverage_percent": 0.0}})
    responses.add(responses.GET, f"{WL}/w-1/risk_details", json=_details(3))
    run_inventory_cycle(ctx, now=NOW)
    rows = {r["href"]: r for r in _rows(ctx, "SELECT * FROM workloads")}
    w1 = rows["/orgs/1/workloads/w-1"]
    assert (w1["visibility_level"], w1["risk_exposure"], w1["ven_href"], w1["ven_version"]) == (
        "flow_summary", "critical", "/orgs/1/vens/v-1", "26.2.20-2063")
    assert w1["label_set"] is not None
    assert len(_rows(ctx, "SELECT * FROM ransomware_services")) == 3
    assert len(_risk_calls()) == 1  # w-2 has no ransomware summary: nothing to ask
    with ctx.flows().connect() as conn:
        caps = capabilities.all(conn)
        state = ingest_state.get(conn, IngestSource.INVENTORY)
    assert caps["ransomware_risk"].state == "supported" and caps["ransomware_org_summary"].state == "supported"
    assert state.last_ok_at == NOW and state.last_rows == 2


@responses.activate
def test_inventory_keeps_previous_on_incomplete(tmp_path):
    ctx = configured_ctx(tmp_path)
    responses.add(responses.GET, WL, json=[_workload(1), _workload(2)])
    responses.add(responses.GET, SUMMARY, status=404)
    responses.add(responses.GET, f"{WL}/w-1/risk_details", json=_details(1))
    responses.add(responses.GET, f"{WL}/w-2/risk_details", json=_details(1))
    run_inventory_cycle(ctx, now=NOW)
    responses.reset()
    responses.add(responses.GET, WL, json=[_workload(i) for i in range(500)])
    responses.add(responses.GET, WL, status=406,
                  match=[responses.matchers.header_matcher({"Prefer": "respond-async"})])
    run_inventory_cycle(ctx, now=NOW + timedelta(hours=1))
    assert len(_rows(ctx, "SELECT * FROM workloads")) == 2
    with ctx.flows().connect() as conn:
        state = ingest_state.get(conn, IngestSource.INVENTORY)
    assert "incomplete" in state.last_error and state.consecutive_failures == 1 and state.last_ok_at == NOW


@responses.activate
def test_risk_details_fetched_only_when_updated_at_changes(tmp_path):
    ctx = configured_ctx(tmp_path)
    responses.add(responses.GET, WL, json=[_workload(1)])
    responses.add(responses.GET, SUMMARY, status=404)
    responses.add(responses.GET, f"{WL}/w-1/risk_details", json=_details(2))
    run_inventory_cycle(ctx, now=NOW)
    run_inventory_cycle(ctx, now=NOW + timedelta(hours=1))
    assert len(_risk_calls()) == 1
    responses.replace(responses.GET, WL, json=[_workload(1, updated="2026-10-24T12:49:37Z")])
    run_inventory_cycle(ctx, now=NOW + timedelta(hours=2))
    assert len(_risk_calls()) == 2


@responses.activate
def test_risk_details_path_is_risk_details_ransomware_details(tmp_path):
    ctx = configured_ctx(tmp_path)
    responses.add(responses.GET, WL, json=[_workload(1)])
    responses.add(responses.GET, SUMMARY, status=404)
    responses.add(responses.GET, f"{WL}/w-1/risk_details", json=_details(5))
    run_inventory_cycle(ctx, now=NOW)
    svc = _rows(ctx, "SELECT * FROM ransomware_services ORDER BY port")
    assert [s["name"] for s in svc] == [f"S-{k}" for k in range(5)]
    assert {s["protection_state"] for s in svc} == {"unprotected"} and svc[0]["category"] == "admin"


@responses.activate
def test_org_summary_404_marks_unsupported_not_failed(tmp_path):
    ctx = configured_ctx(tmp_path)
    responses.add(responses.GET, WL, json=[_workload(1, risk=None)])
    responses.add(responses.GET, SUMMARY, status=404)
    run_inventory_cycle(ctx, now=NOW)
    with ctx.flows().connect() as conn:
        assert capabilities.all(conn)["ransomware_org_summary"].state == "unsupported"
        assert ingest_state.get(conn, IngestSource.INVENTORY).last_error is None


@responses.activate
def test_risk_details_failure_does_not_fail_inventory(tmp_path):
    ctx = configured_ctx(tmp_path)
    responses.add(responses.GET, WL, json=[_workload(1)])
    responses.add(responses.GET, SUMMARY, status=404)
    responses.add(responses.GET, f"{WL}/w-1/risk_details", status=500)
    run_inventory_cycle(ctx, now=NOW)
    with ctx.flows().connect() as conn:
        assert ingest_state.get(conn, IngestSource.INVENTORY).last_error is None
        assert "1 of 1" in ingest_state.get(conn, IngestSource.RANSOMWARE).last_error


@responses.activate
def test_daily_snapshot_written_once_per_day(tmp_path):
    ctx = configured_ctx(tmp_path)
    responses.add(responses.GET, WL, json=[_workload(1)])
    responses.add(responses.GET, SUMMARY, status=404)
    responses.add(responses.GET, f"{WL}/w-1/risk_details", json=_details(2))
    run_inventory_cycle(ctx, now=NOW)
    run_inventory_cycle(ctx, now=NOW + timedelta(hours=3))
    assert len(_rows(ctx, "SELECT * FROM workload_snapshot_daily")) == 1
    assert len(_rows(ctx, "SELECT * FROM ransomware_snapshot_daily")) == 2
    run_inventory_cycle(ctx, now=NOW + timedelta(days=1))
    assert len(_rows(ctx, "SELECT * FROM workload_snapshot_daily")) == 2


@responses.activate
def test_visibility_summary_buckets(tmp_path):
    ctx = configured_ctx(tmp_path)
    levels = ["flow_summary", "enhanced_data_collection", "flow_drops", "flow_off", "brand_new_level"]
    responses.add(responses.GET, WL, json=[_workload(i, risk=None, visibility=v) for i, v in enumerate(levels)])
    responses.add(responses.GET, SUMMARY, status=404)
    run_inventory_cycle(ctx, now=NOW)
    with ctx.flows().connect() as conn:
        assert visibility_summary(conn) == {"sees_allowed": 2, "blocked_only": 1, "off": 1, "unknown": 1}


def test_inventory_job_interval_from_settings(tmp_path):
    from illumio_ops.jobs.scheduler import job_intervals
    ctx = configured_ctx(tmp_path, inventory_interval_seconds=7200)
    assert job_intervals(ctx.settings.current())["collect_inventory"] == 7200
    assert inventory.SOURCE == IngestSource.INVENTORY


IPL = f"{API}/orgs/1/sec_policy/active/ip_lists"


@responses.activate
def test_inventory_keeps_the_pce_ip_lists(tmp_path):
    # user 2026-10-31: an alert rule can leave out an IP list; its networks come from the inventory run
    ctx = configured_ctx(tmp_path)
    responses.add(responses.GET, WL, json=[_workload(1, risk=None)])
    responses.add(responses.GET, SUMMARY, status=404)
    responses.add(responses.GET, IPL, json=[
        {"href": "/orgs/1/sec_policy/active/ip_lists/7", "name": "Scanners",
         "ip_ranges": [{"from_ip": "10.9.0.0/16"}, {"from_ip": "10.9.9.0/24", "exclusion": True}]},
        {"href": "/orgs/1/sec_policy/active/ip_lists/8", "name": "Partners", "fqdns": [{"fqdn": "x.example"}]}])
    run_inventory_cycle(ctx, now=NOW)
    from illumio_ops.store.flowdb import ip_lists
    with ctx.flows().connect() as conn:
        assert ip_lists.names(conn) == [("/orgs/1/sec_policy/active/ip_lists/8", "Partners"),
                                        ("/orgs/1/sec_policy/active/ip_lists/7", "Scanners")]
        nets = ip_lists.networks(conn)["/orgs/1/sec_policy/active/ip_lists/7"]
    assert "10.9.0.0/21" in nets and not any(n.startswith("10.9.9.") for n in nets)


@responses.activate
def test_an_ip_list_failure_matches_nothing_until_the_next_read(tmp_path):
    # final review 2026-10-31: a list the PCE changed must not go on silencing alerts with its old networks; the
    # names stay for the editor, the networks go (an exclusion by the list then matches nothing: alerts, not silence)
    ctx = configured_ctx(tmp_path)
    responses.add(responses.GET, WL, json=[_workload(1, risk=None)])
    responses.add(responses.GET, SUMMARY, status=404)
    responses.add(responses.GET, IPL, json=[{"href": "/orgs/1/sec_policy/active/ip_lists/7", "name": "Scanners",
                                             "ip_ranges": [{"from_ip": "10.9.0.0/16"}]}])
    run_inventory_cycle(ctx, now=NOW)
    responses.replace(responses.GET, IPL, status=500)
    run_inventory_cycle(ctx, now=NOW + timedelta(hours=1))
    from illumio_ops.store.flowdb import ip_lists
    with ctx.flows().connect() as conn:
        assert [n for _, n in ip_lists.names(conn)] == ["Scanners"] and ip_lists.networks(conn) == {}
        assert ingest_state.get(conn, IngestSource.INVENTORY).last_error is None


SVC = f"{API}/orgs/1/sec_policy/active/services"
LGS = f"{API}/orgs/1/sec_policy/active/label_groups"
LABELS = f"{API}/orgs/1/labels"


def _policy_objects():
    responses.add(responses.GET, SVC, json=[
        {"href": "/orgs/1/sec_policy/active/services/1", "name": "All Services", "service_ports": [{"proto": -1}]},
        {"href": "/orgs/1/sec_policy/active/services/2", "name": "Web",
         "service_ports": [{"port": 443, "proto": 6}, {"port": 8000, "to_port": 8100, "proto": 6}, {"proto": 1}]},
        {"href": "/orgs/1/sec_policy/active/services/3", "name": "Update",
         "windows_services": [{"service_name": "wuauserv"}, {"port": 135, "proto": 6, "service_name": "RpcSs"}]}])
    responses.add(responses.GET, LABELS, json=[
        {"href": "/orgs/1/labels/1", "key": "env", "value": "Prod"},
        {"href": "/orgs/1/labels/2", "key": "env", "value": "Staging"},
        {"href": "/orgs/1/labels/3", "key": "env", "value": "DR"}])
    responses.add(responses.GET, LGS, json=[
        {"href": "/orgs/1/sec_policy/active/label_groups/a", "name": "Live", "key": "env",
         "labels": [{"href": "/orgs/1/labels/1"}], "sub_groups": [{"href": "/orgs/1/sec_policy/active/label_groups/b"}]},
        {"href": "/orgs/1/sec_policy/active/label_groups/b", "name": "Standby", "key": "env",
         "labels": [{"href": "/orgs/1/labels/3"}], "sub_groups": [{"href": "/orgs/1/sec_policy/active/label_groups/a"}]}])


@responses.activate
def test_inventory_keeps_the_pce_services_and_label_groups(tmp_path):
    # 5.x parity 2026-11-06: flow conditions name PCE services (their ports) and label groups (their labels)
    ctx = configured_ctx(tmp_path)
    responses.add(responses.GET, WL, json=[_workload(1, risk=None)])
    responses.add(responses.GET, SUMMARY, status=404)
    _policy_objects()
    run_inventory_cycle(ctx, now=NOW)
    from illumio_ops.store.flowdb import policy_objects as po
    with ctx.flows().connect() as conn:
        assert [n for _, n in po.service_names(conn)] == ["All Services", "Update", "Web"]
        ports = po.service_ports(conn, [h for h, _ in po.service_names(conn)])
        assert ports["/orgs/1/sec_policy/active/services/1"] == ((None, None, None),)
        assert sorted(ports["/orgs/1/sec_policy/active/services/2"], key=str) == sorted(
            [(443, None, 6), (8000, 8100, 6), (None, None, 1)], key=str)
        assert ports["/orgs/1/sec_policy/active/services/3"] == ((135, None, 6),)  # a name alone has no port
        assert po.label_group_names(conn) == [("/orgs/1/sec_policy/active/label_groups/a", "Live", "env"),
                                              ("/orgs/1/sec_policy/active/label_groups/b", "Standby", "env")]
        groups = po.label_groups(conn, ["/orgs/1/sec_policy/active/label_groups/a"])
    # sub-groups expanded (a cycle between two groups stops)
    assert groups == {"/orgs/1/sec_policy/active/label_groups/a": ("env", frozenset({"Prod", "DR"}))}


@responses.activate
def test_a_policy_object_failure_matches_nothing_until_the_next_read(tmp_path):
    ctx = configured_ctx(tmp_path)
    responses.add(responses.GET, WL, json=[_workload(1, risk=None)])
    responses.add(responses.GET, SUMMARY, status=404)
    _policy_objects()
    run_inventory_cycle(ctx, now=NOW)
    responses.replace(responses.GET, SVC, status=500)
    responses.replace(responses.GET, LGS, status=500)
    run_inventory_cycle(ctx, now=NOW + timedelta(hours=1))
    from illumio_ops.store.flowdb import policy_objects as po
    with ctx.flows().connect() as conn:
        assert len(po.service_names(conn)) == 3 and po.service_ports(conn, [h for h, _ in po.service_names(conn)]) == {}
        assert po.label_groups(conn, ["/orgs/1/sec_policy/active/label_groups/a"]) == {
            "/orgs/1/sec_policy/active/label_groups/a": ("env", frozenset())}
        assert ingest_state.get(conn, IngestSource.INVENTORY).last_error is None
