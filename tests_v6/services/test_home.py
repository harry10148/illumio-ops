"""Home focus list (P6b): the hourly result read as stored, with a link per item; never "nothing to look at"
when it was not computed or a source failed."""
import json
from datetime import UTC, datetime, timedelta

import pytest

from illumio_ops.domain.filter import FlowCondition
from illumio_ops.domain.segment import FlowSegment
from illumio_ops.domain.values import SegmentView
from illumio_ops.services import home
from illumio_ops.store.flowdb import analysis
from tests_v6.services.collect.conftest import configured_ctx

NOW = datetime(2026, 10, 30, 12, tzinfo=UTC)


def _item(kind, target, *, segment=None, host_key=None):
    return {"kind": kind, "fingerprint": f"{kind}|x", "severity": "medium", "critical_asset": False,
            "confidence": "high", "title_key": "focus_title_tamper", "why_key": "focus_why_tamper",
            "params": {"host": "web01", "count": 3, "pattern": "burst"},
            "action": {"target": target, "segment": segment, "host_key": host_key}, "score": 1.0,
            "first_seen": NOW.isoformat(), "new_this_week": True, "weeks_persisting": 0}


def _store(ctx, items, *, at=NOW, status=None):
    with ctx.flows().connect() as conn:
        analysis.write_result(conn, "focus", params={}, result={
            "computed_at": at.isoformat(), "items": items, "sources_status": status or {"exposure": "ok"},
            "detections": {"total": 0, "considered": 0}, "traffic_computed_at": None}, at=at)
        conn.commit()


@pytest.fixture
def ctx(tmp_path):
    return configured_ctx(tmp_path, mode="full")


def test_focus_not_computed(ctx):
    v = home.focus_view(ctx, now=NOW)
    assert v.computed_at is None and v.items == [] and not v.stale


def test_focus_stale(ctx):
    _store(ctx, [], at=NOW - timedelta(hours=3))
    assert home.focus_view(ctx, now=NOW).stale
    _store(ctx, [], at=NOW - timedelta(minutes=30))
    assert not home.focus_view(ctx, now=NOW).stale


def test_focus_sources_status_carried(ctx):
    _store(ctx, [], status={"exposure": "error", "tamper": "ok"})
    assert home.focus_view(ctx, now=NOW).sources_status == {"exposure": "error", "tamper": "ok"}


def test_focus_links(ctx):
    week = FlowSegment(filter=FlowCondition().within(NOW - timedelta(days=7), NOW), view=SegmentView.DETAIL, limit=50)
    year = FlowSegment(filter=FlowCondition().within(NOW - timedelta(days=60), NOW), view=SegmentView.DETAIL, limit=50)
    _store(ctx, [
        _item("detection", "workbench", segment=week.model_dump(mode="json")),
        _item("detection", "workbench", segment=year.model_dump(mode="json")),
        _item("tamper", "host", host_key="/orgs/1/workloads/w1"),
        _item("exposure_asset", "lateral", host_key="ip:10.0.0.9"),
        _item("cross_env", "lateral"),
        _item("mode_switch_blocker", "workbench"),
        _item("setup_required", "settings_lateral"),
        _item("data_coverage", "settings_collection"),
        _item("system_health", "system_jobs"),
        _item("system_health", "system_pce"),
        _item("pivot_host", "lateral", host_key="/orgs/1/workloads/p1"),
        _item("vendor_contradiction", "lateral"),
    ])
    links = [i.link for i in home.focus_view(ctx, now=NOW).items]
    q = json.loads(links[0].query["q"])
    assert links[0].route == "/investigate" and q["mode"] == "flows" and q["start"].startswith("2026-10-23")
    assert links[1] is None  # longer than the workbench's 30 days
    assert (links[2].route, links[2].query) == ("/hosts", {"key": "/orgs/1/workloads/w1"})
    assert (links[3].route, links[3].query) == ("/lateral", {"asset": "ip:10.0.0.9"})
    assert (links[4].route, links[4].query) == ("/lateral", {"section": "cross_env"})
    mode_switch = json.loads(links[5].query["q"])
    assert mode_switch["condition"]["decisions"] == ["potentially_blocked"] and mode_switch["view"] == "ranking"
    assert [lk.route for lk in links[6:10]] == ["/system/lateral", "/system/collection", "/system/jobs", "/system/pce"]
    assert (links[10].route, links[10].query) == ("/lateral", {"host": "/orgs/1/workloads/p1"})
    assert (links[11].route, links[11].query) == ("/lateral", {"section": "footholds"})


def test_focus_hosts_named(ctx):
    """Lab acceptance 2026-10-30: items about a host the PCE sent no hostname for showed its href; the inventory's
    name, else an address it was seen with, is shown."""
    from illumio_ops.domain.values import DataOrigin
    from illumio_ops.store.flowdb import workloads
    from illumio_ops.store.flowdb.flows import upsert_flows
    from tests_v6.services.reports.test_findings import flow
    with ctx.flows().connect() as conn:
        workloads.replace_inventory(conn, [workloads.WorkloadRow(
            href="/orgs/1/workloads/k8s", hostname=None, name="k8s-node02", managed=1, enforcement_mode=None,
            visibility_level=None, os_id=None, ven_version=None, ven_href=None, label_set=None, online=1,
            risk_exposure=None, risk_percent=None, risk_updated_at=None, fetched_at="x")])
        upsert_flows(conn, [flow(src="x", dst="ghost", port=22)], origin=DataOrigin.INGEST, now=NOW)
        conn.execute("UPDATE flows SET dst_hostname = NULL WHERE dst_key = '/orgs/1/workloads/ghost'")
        ip = conn.execute("SELECT dst_ip FROM flows WHERE dst_key = '/orgs/1/workloads/ghost'").fetchone()[0]
        conn.commit()
    items = [_item("detection", "workbench") for _ in range(3)]
    items[0]["params"] = {"host": "/orgs/1/workloads/k8s", "targets": 4}
    items[1]["params"] = {"host": "/orgs/1/workloads/ghost", "account": "/orgs/1/workloads/ghost"}
    items[2]["params"] = {"host": "web01"}
    for i, it in enumerate(items):
        it["fingerprint"] = f"f{i}"
    _store(ctx, items)
    got = [i.params for i in home.focus_view(ctx, now=NOW).items]
    assert got == [{"host": "k8s-node02", "targets": 4}, {"host": ip, "account": ip}, {"host": "web01"}]


def test_focus_of_another_pce_refused(ctx):
    """Final review #1: a PCE switch whose clearing has not finished must not show the previous PCE's list."""
    from illumio_ops.services.collect.guard import BindingMismatch, ensure_binding
    with ctx.flows().connect() as conn:
        ensure_binding(conn, ctx.settings.current().pce, NOW)
        conn.commit()
    _store(ctx, [_item("tamper", "host", host_key="/orgs/1/workloads/w1")])
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["pce"].update(url="https://pce-b.example:8443"))
    with pytest.raises(BindingMismatch):
        home.focus_view(ctx, now=NOW)


def test_focus_detections_considered_carried(ctx):
    """Final review #7: the builder keeps the top 500 detections of a week; the page says when there were more."""
    with ctx.flows().connect() as conn:
        analysis.write_result(conn, "focus", params={}, result={
            "computed_at": NOW.isoformat(), "items": [], "sources_status": {},
            "detections": {"total": 600, "considered": 500}, "traffic_computed_at": None}, at=NOW)
        conn.commit()
    v = home.focus_view(ctx, now=NOW)
    assert (v.detections_total, v.detections_considered) == (600, 500)
