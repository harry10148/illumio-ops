"""The lateral movement page (P6c): the hourly exposure result read as stored, hosts named, detections only where
traffic is collected; in lightweight mode the graph's management ports pulled from the PCE and held 30 minutes."""
import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest

from illumio_ops.domain.deny import DenyProposal
from illumio_ops.domain.exposure import EdgeIn
from illumio_ops.domain.filter import EndpointFilter, PortProto
from illumio_ops.domain.lateral import GRAPH_CLASSES
from illumio_ops.domain.values import CapabilityState, EdgeState
from illumio_ops.services import lateral_view
from illumio_ops.services.ondemand import OnDemandResult
from illumio_ops.store.flowdb import analysis, capabilities, workloads
from illumio_ops.store.flowdb.analysis import DetectionWrite
from tests_v6.services.collect.conftest import configured_ctx

NOW = datetime(2026, 10, 30, 12, tzinfo=UTC)
DB = "/orgs/1/workloads/db"
WEB = "/orgs/1/workloads/web"
BARE = "/orgs/1/workloads/bare"


def _wl(href, hostname):
    return workloads.WorkloadRow(
        href=href, hostname=hostname, name=None, managed=1, enforcement_mode="selective", visibility_level=None,
        os_id=None, ven_version=None, ven_href=None, label_set=None, online=1, risk_exposure=None, risk_percent=None,
        risk_updated_at=None, fetched_at="x")


def _result(at=NOW, *, groups=True):
    r = {"computed_at": at.isoformat(), "observation_from": (at - timedelta(days=30)).isoformat(),
         "observation_to": at.isoformat(), "hops": 3, "nodes": 3, "edges_now": 2, "edges_enforced": 1,
         "unknown_edges": 0,
         "hosts": [{"key": WEB, "reach_now": 2, "reach_enforced": 1, "pivot_now": False, "pivot_enforced": False},
                   {"key": BARE, "reach_now": 1, "reach_enforced": 0, "pivot_now": True, "pivot_enforced": False},
                   {"key": "ip:10.9.9.9", "reach_now": 1, "reach_enforced": 0, "pivot_now": False,
                    "pivot_enforced": False}],
         "assets": [{"key": DB, "sources_now": 2, "sources_enforced": 1, "paths": [[WEB, BARE, DB]],
                     "cuts": [{"kind": "edge", "src": BARE, "dst": DB, "ports": [[3389, 6]], "before": 2, "after": 0}]}],
         "cross_env": [], "cross_env_total": 0, "footholds": [], "limits_hit": []}
    if groups:
        r["groups"] = {"app": {"groups": ["web", "db"], "edges": [["web", "db", 1, "allowed"]]}}
    return r


def _store(ctx, at=NOW, **kw):
    with ctx.flows().connect() as conn:
        analysis.write_result(conn, "exposure", params={}, result=_result(at, **kw), at=at)
        analysis.set_run(conn, "exposure", status={"state": "ok"}, ok_at=at)
        conn.commit()


@pytest.fixture
def ctx(tmp_path):
    c = configured_ctx(tmp_path, mode="full")
    with c.flows().connect() as conn:
        workloads.replace_inventory(conn, [_wl(DB, "fin-db"), _wl(WEB, "web-01"), _wl(BARE, None)])
        conn.commit()
    return c


@pytest.fixture(autouse=True)
def _no_held():
    lateral_view.drop()
    yield
    lateral_view.drop()


def test_not_computed(ctx):
    v = lateral_view.view(ctx, now=NOW)
    assert v.state == "not_computed" and v.exposure is None and v.source is None


def test_collection_off(tmp_path):
    c = configured_ctx(tmp_path, mode="full", enabled=False)
    with c.flows().connect() as conn:
        analysis.set_run(conn, "exposure", status={"state": "collection_off"})
        conn.commit()
    assert lateral_view.view(c, now=NOW).state == "collection_off"


def test_stale_after_two_hours(ctx):
    _store(ctx, at=NOW - timedelta(hours=3))
    v = lateral_view.view(ctx, now=NOW)
    assert v.state == "ok" and v.source == "stored" and v.stale
    _store(ctx, at=NOW - timedelta(minutes=30))
    assert not lateral_view.view(ctx, now=NOW).stale


def test_names_never_hrefs(ctx, monkeypatch):
    monkeypatch.setattr("illumio_ops.services.hosts.host_addresses", lambda c, hrefs: {BARE: "10.0.0.5"} if BARE in hrefs else {})
    _store(ctx)
    v = lateral_view.view(ctx, now=NOW)
    assert v.names[DB] == "fin-db" and v.names[WEB] == "web-01" and v.names[BARE] == "10.0.0.5"
    assert v.names["ip:10.9.9.9"] == "10.9.9.9"
    assert not any(n.startswith("/orgs/") for n in v.names.values())


def test_result_before_groups_still_shown(ctx):
    _store(ctx, groups=False)
    v = lateral_view.view(ctx, now=NOW)
    assert v.exposure is not None and v.exposure.groups == {}


def test_detections_only_when_collected(ctx, tmp_path):
    with ctx.flows().connect() as conn:
        analysis.upsert_detections(conn, [DetectionWrite(
            detector="fanout", fingerprint=f"fanout|{WEB}", subject_key=WEB, severity="high",
            first_seen=NOW - timedelta(minutes=30), last_seen=NOW - timedelta(minutes=5), critical_asset=True,
            summary_json=json.dumps({"targets": 12, "window_minutes": 60}), segment_json="{}",
            confidence_json="{}")], dedup={"fanout": timedelta(hours=1)}, late=False, at=NOW)
    v = lateral_view.view(ctx, now=NOW)
    assert v.detections_available and v.detections_total == 1
    [d] = v.detections
    assert d.subject_name == "web-01" and d.critical_asset and d.title_key and d.params["host"] == "web-01"
    light = configured_ctx(tmp_path / "light", mode="lightweight")
    lv = lateral_view.view(light, now=NOW)
    assert not lv.detections_available and lv.detections == [] and lv.state == "lightweight"


def test_ransomware_unsupported_flag(ctx):
    with ctx.flows().connect() as conn:
        capabilities.record(conn, "ransomware_risk", CapabilityState.UNSUPPORTED, None, NOW)
        conn.commit()
    assert lateral_view.view(ctx, now=NOW).ransomware_unsupported


def test_previous_pce_refused(ctx):
    from illumio_ops.services.collect.guard import BindingMismatch, ensure_binding
    with ctx.flows().connect() as conn:
        ensure_binding(conn, ctx.settings.current().pce, NOW)
        conn.commit()
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["pce"].update(url="https://pce-b.example:8443"))
    with pytest.raises(BindingMismatch):
        lateral_view.view(ctx, now=NOW)


def test_compute_refused_outside_lightweight(ctx):
    with pytest.raises(ValueError):
        lateral_view.compute(ctx, 7, now=NOW)


# ── lightweight ───────────────────────────────────────────────────────────────

@pytest.fixture
def light(tmp_path):
    c = configured_ctx(tmp_path, mode="lightweight")
    with c.flows().connect() as conn:
        workloads.replace_inventory(conn, [_wl(DB, "fin-db"), _wl(WEB, "web-01")])
        conn.commit()
    c.settings.update(c.settings.current().revision,
                      lambda d: d["lateral"].update({"critical_assets": [{"key": "app", "value": "Finance"}]}))
    return c


@pytest.fixture
def pulls(monkeypatch):
    log = {"specs": [], "windows": []}

    @contextmanager
    def fake_pull(ctx, *, start, end, spec=None, now=None):
        log["specs"].append(spec)
        log["windows"].append((start, end))
        yield OnDemandResult(ctx=ctx, rows=7, windows=1, truncated=[], earliest=start, capped_total=False,
                             unread_from=None)
    monkeypatch.setattr(lateral_view, "pull_period", fake_pull)
    edges = [EdgeIn(WEB, DB, 3389, 6, EdgeState.POTENTIALLY_BLOCKED)]
    monkeypatch.setattr(lateral_view, "graph_edges", lambda ctx, lc, since: list(edges))
    return log


def test_lightweight_compute_pulls_admin_ports_only(light, pulls):
    v = lateral_view.compute(light, 7, now=NOW)
    assert v.state == "ok" and v.source == "pulled" and v.pull is not None and v.pull.rows == 7
    [spec] = pulls["specs"]
    from illumio_ops.services.analysis.context import load_lateral_context
    lc = load_lateral_context(light, now=NOW)
    graph_ports = {(e.port, e.proto) for e in lc.admin_ports.entries if e.category in GRAPH_CLASSES}
    assert spec.ports and {(p.port, p.proto) for p in spec.ports} == graph_ports
    start, end = pulls["windows"][0]
    assert end - start >= timedelta(days=7) and start.minute == 0
    assert v.exposure is not None and v.exposure.edges_now == 1


def test_lightweight_days_offered(light):
    v = lateral_view.view(light, now=NOW)
    assert v.lightweight_days == [1, 7, 30] and v.state == "lightweight"
    with pytest.raises(ValueError):
        lateral_view.compute(light, 5, now=NOW)


def test_lightweight_held_then_expired(light, pulls):
    lateral_view.compute(light, 7, now=NOW)
    assert lateral_view.view(light, now=NOW + timedelta(minutes=10)).source == "pulled"
    assert lateral_view.view(light, now=NOW + lateral_view.KEEP + timedelta(minutes=1)).state == "lightweight"


def test_lightweight_settings_change_drops_held(light, pulls):
    lateral_view.compute(light, 7, now=NOW)
    light.settings.update(light.settings.current().revision, lambda d: d["lateral"].update({"graph_hops": 2}))
    assert lateral_view.view(light, now=NOW).state == "lightweight"


TO_DB = DenyProposal(src=EndpointFilter(hrefs=(WEB,)), dst=EndpointFilter(hrefs=(DB,)),
                     ports=(PortProto(port=3389, proto=6),))


def test_simulate_lightweight_needs_compute(light, pulls):
    with pytest.raises(lateral_view.NotComputed):
        lateral_view.simulate(light, TO_DB, now=NOW)


def test_simulate_lightweight_uses_held_edges(light, pulls, monkeypatch):
    seen = {}

    def fake_sim(ctx, proposal, *, now=None, window=None, edges=None):
        seen.update(window=window, edges=edges)
        return "sim"
    monkeypatch.setattr(lateral_view, "simulate_deny", fake_sim)
    lateral_view.compute(light, 7, now=NOW)
    monkeypatch.setattr(lateral_view, "_named", lambda ctx, sim, pull: sim)
    assert lateral_view.simulate(light, TO_DB, now=NOW + timedelta(minutes=5)) == "sim"
    assert [(e.src, e.dst) for e in seen["edges"]] == [(WEB, DB)]
    assert seen["window"] == pulls["windows"][0]
    # the proposal's own traffic was pulled for the counts, with the proposal pushed to the PCE
    assert len(pulls["specs"]) == 2 and pulls["specs"][1].dst.hrefs == (DB,)


def test_port_names_for_paths(ctx):
    names = lateral_view.view(ctx, now=NOW).port_names
    assert names.get("3389/6") and names.get("445/6")


def test_simulate_waits_for_another_pull(light, pulls, monkeypatch):
    """Security review: one interactive pull from the PCE at a time — a simulation waits while the workbench (or the
    exposure computation) is reading, instead of a second download running beside it."""
    import threading

    from illumio_ops.services import ondemand
    monkeypatch.setattr(lateral_view, "_named", lambda ctx, sim, pull: sim)
    monkeypatch.setattr(lateral_view, "simulate_deny", lambda *a, **kw: "sim")
    lateral_view.compute(light, 7, now=NOW)
    done = threading.Event()
    with ondemand.INTERACTIVE_PULL:
        t = threading.Thread(target=lambda: (lateral_view.simulate(light, TO_DB, now=NOW), done.set()))
        t.start()
        assert not done.wait(0.5) and len(pulls["specs"]) == 1  # still waiting: nothing pulled
    assert done.wait(5) and len(pulls["specs"]) == 2
    t.join(5)
