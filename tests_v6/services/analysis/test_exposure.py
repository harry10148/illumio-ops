"""run_exposure: the graph built from the connection baseline, stored with the day's snapshot."""
import json
from dataclasses import replace
from datetime import timedelta

from illumio_ops.domain.flows import normalize_flow
from illumio_ops.domain.values import DataOrigin
from illumio_ops.services.analysis import exposure
from illumio_ops.services.analysis.exposure import run_exposure
from illumio_ops.services.analysis.hourly import run_hourly_analysis
from illumio_ops.store.flowdb import analysis, ransomware, workloads
from illumio_ops.store.flowdb.flows import upsert_flows
from illumio_ops.store.flowdb.labels import label_set_id
from tests_v6.services.collect.conftest import NOW, configured_ctx, raw_flow


def _flow(i, age_days, *, port=445, decision="potentially_blocked", dst=None):
    last = NOW - timedelta(days=age_days)
    r = normalize_flow(raw_flow(i, last - timedelta(minutes=5), last, port=port))
    if dst:
        r = replace(r, dst_href=dst, dst_ip=f"10.0.3.{i}")
    return replace(r, policy_decision=decision)


def _setup(tmp_path, **lateral):
    ctx = configured_ctx(tmp_path)
    if lateral:
        ctx.settings.update(ctx.settings.current().revision, lambda d: d["lateral"].update(lateral))
    return ctx


def _write(ctx, recs):
    with ctx.flows().connect() as conn:
        upsert_flows(conn, recs, origin=DataOrigin.INGEST, now=NOW)


def test_exposure_respects_observation_days(tmp_path):
    ctx = _setup(tmp_path)
    _write(ctx, [_flow(1, 1), _flow(2, 40), _flow(3, 2, port=8080)])  # 8080 is not a management port
    r = run_exposure(ctx, now=NOW)
    assert r.nodes == 2 and r.edges_now == 1  # src-1 → dst only
    assert r.observation_from == NOW - timedelta(days=30)
    ctx.settings.update(ctx.settings.current().revision,
                        lambda d: d["collection"]["retention"].update({"baseline_days": 7, "flow_days": 35}))
    assert run_exposure(ctx, now=NOW).observation_from == NOW - timedelta(days=7)  # baseline keeps only 7


def test_exposure_marks_critical_assets(tmp_path):
    ctx = _setup(tmp_path, critical_assets=[{"key": "app", "value": "Finance"}])
    with ctx.flows().connect() as conn:
        fin = label_set_id(conn, (("app", "Finance"),))
        workloads.replace_inventory(conn, [workloads.WorkloadRow(
            href="/orgs/1/workloads/dst", hostname="db", name=None, managed=1, enforcement_mode="selective",
            visibility_level=None, os_id=None, ven_version=None, ven_href=None, label_set=fin, online=1,
            risk_exposure=None, risk_percent=None, risk_updated_at=None, fetched_at="x")])
    _write(ctx, [_flow(1, 1, decision="allowed"), _flow(2, 1)])
    r = run_exposure(ctx, now=NOW)
    [asset] = r.assets
    assert (asset.key, asset.sources_now, asset.sources_enforced) == ("/orgs/1/workloads/dst", 2, 1)


def test_lightweight_mode_stores_collection_off(tmp_path):
    ctx = configured_ctx(tmp_path, mode="lightweight")
    assert run_exposure(ctx, now=NOW) is None
    with ctx.flows().connect() as conn:
        assert json.loads(analysis.get_run(conn, "exposure")["status_json"])["state"] == "collection_off"
        assert analysis.read_result(conn, "exposure") is None


def test_footholds_from_unprotected_listening(tmp_path):
    ctx = _setup(tmp_path)
    with ctx.flows().connect() as conn:
        ransomware.upsert_services(conn, "/orgs/1/workloads/dst", [
            {"name": "RDP", "port": 3389, "proto": 6, "severity": "critical", "category": "admin",
             "protection_state": "unprotected", "port_status": "listening"},
            {"name": "SMB", "port": 445, "proto": 6, "severity": "high", "category": "admin",
             "protection_state": "unprotected", "port_status": "inactive"}], source_updated_at=None, at=NOW)
    _write(ctx, [_flow(1, 1)])
    r = run_exposure(ctx, now=NOW)
    assert [(f.host, f.name) for f in r.footholds] == [("/orgs/1/workloads/dst", "RDP")]


def test_snapshot_written_for_today(tmp_path):
    ctx = _setup(tmp_path)
    _write(ctx, [_flow(1, 1)])
    run_exposure(ctx, now=NOW)
    with ctx.flows().connect() as conn:
        snap = json.loads(conn.execute("SELECT metrics_json FROM lateral_snapshot_daily WHERE day = ?",
                                       (NOW.date().isoformat(),)).fetchone()[0])
        stored = json.loads(analysis.read_result(conn, "exposure")["result_json"])
    assert snap["nodes"] == 2 and snap["edges_now"] == 1 and snap["assets_reachable_now"] == 0
    assert stored["nodes"] == 2 and stored["hops"] == 3


def test_stale_generation_drops_exposure(tmp_path, monkeypatch):
    ctx = _setup(tmp_path)
    _write(ctx, [_flow(1, 1)])
    real = exposure.compute_exposure

    def switch_meanwhile(*a, **kw):
        ctx.flows().reset()  # the operator switched PCE while the graph was being computed
        return real(*a, **kw)
    monkeypatch.setattr(exposure, "compute_exposure", switch_meanwhile)
    assert run_hourly_analysis(ctx, now=NOW)["exposure"] == "stale"
    with ctx.flows().connect() as conn:
        assert analysis.read_result(conn, "exposure") is None


def test_exposure_graph_excludes_directory_ports(tmp_path):
    """Spec §6.5.8: the graph draws remote-execution and database connections; Kerberos and LDAP would make
    every domain member reach the directory servers."""
    ctx = _setup(tmp_path)
    _write(ctx, [_flow(1, 1, port=389), _flow(2, 1, port=88), _flow(3, 1, port=1433, dst="/orgs/1/workloads/db"),
                 _flow(4, 1, port=445, dst="/orgs/1/workloads/fs")])
    r = run_exposure(ctx, now=NOW)
    assert r.edges_now == 2
