"""load_lateral_context: settings, inventory, labels and baseline age, read once for every analysis."""
from datetime import timedelta

from illumio_ops.domain.values import IngestSource
from illumio_ops.services.analysis.context import host_for, load_lateral_context
from illumio_ops.store.flowdb import ingest_state, ransomware, workloads
from illumio_ops.store.flowdb.labels import label_set_id
from tests_v6.services.collect.conftest import NOW, configured_ctx


def _wl(href, label_set, **kw):
    base = {"href": href, "hostname": href.rsplit("/", 1)[-1], "name": None, "managed": 1,
            "enforcement_mode": "visibility_only", "visibility_level": "enhanced_data_collection",
            "os_id": "ubuntu-x86_64-jammy", "ven_version": None, "ven_href": None, "label_set": label_set,
            "online": 1, "risk_exposure": None, "risk_percent": None, "risk_updated_at": None, "fetched_at": "x"}
    return workloads.WorkloadRow(**(base | kw))


def _lateral(ctx, **changes):
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["lateral"].update(changes))


def _inventory(ctx):
    with ctx.flows().connect() as conn:
        fin = label_set_id(conn, (("app", "Finance"), ("env", "Prod")))
        jump = label_set_id(conn, (("role", "Jump"),))
        label_set_id(conn, (("app", "Gone"),))  # seen on old flows only, no longer on any workload
        workloads.replace_inventory(conn, [_wl("/orgs/1/workloads/w1", fin), _wl("/orgs/1/workloads/w2", jump),
                                           _wl("/orgs/1/workloads/w3", None)])


def _covered(ctx, *ranges, watermark=NOW):
    with ctx.flows().connect() as conn:
        for a, b in ranges:
            ingest_state.add_coverage(conn, IngestSource.TRAFFIC, a, b)
        ingest_state.mark_ok(conn, IngestSource.TRAFFIC, NOW, watermark=watermark, rows=0)


def test_host_index_marks_critical_and_admin(tmp_path):
    ctx = configured_ctx(tmp_path)
    _lateral(ctx, critical_assets=[{"key": "app", "value": "Finance"}], admin_groups=[{"key": "role", "value": "Jump"}])
    _inventory(ctx)
    lc = load_lateral_context(ctx, now=NOW)
    w1, w2, w3 = (lc.hosts[f"/orgs/1/workloads/w{i}"] for i in (1, 2, 3))
    assert (w1.critical, w1.admin_group, w1.labels) == (True, False, {"app": "Finance", "env": "Prod"})
    assert (w2.critical, w2.admin_group) == (False, True) and (w3.critical, w3.admin_group) == (False, False)
    unmanaged = host_for(lc, "ip:10.9.9.9", ip="10.9.9.9", hostname=None)
    assert (unmanaged.managed, unmanaged.critical, unmanaged.admin_group) == (False, False, False)
    gone = host_for(lc, "/orgs/1/workloads/w9", ip="10.0.0.9", hostname="w9", labels={"app": "Finance"})
    assert gone.critical is True  # not in the inventory any more: judged by the labels the flow carried


def test_admin_ports_from_builtin_pce_and_settings(tmp_path):
    ctx = configured_ctx(tmp_path)
    _lateral(ctx, extra_admin_ports=[{"port": 8443, "proto": 6}], removed_admin_ports=[{"port": 23, "proto": None}])
    with ctx.flows().connect() as conn:
        ransomware.upsert_services(conn, "/orgs/1/workloads/w1", [
            {"name": "VNC", "port": 5900, "proto": 6, "severity": "high", "category": "admin"},
            {"name": "FTP", "port": 21, "proto": 6, "severity": "low", "category": "legacy"}],
            source_updated_at=None, at=NOW)
    lc = load_lateral_context(ctx, now=NOW)
    sources = {(e.port, e.source) for e in lc.admin_ports.entries}
    assert (5900, "pce") in sources and (8443, "added") in sources and (445, "builtin") in sources
    assert not any(e.port in (23, 21) for e in lc.admin_ports.entries)


def test_context_lightweight_mode_not_collected(tmp_path):
    assert load_lateral_context(configured_ctx(tmp_path, mode="lightweight"), now=NOW).collected is False
    assert load_lateral_context(configured_ctx(tmp_path / "b"), now=NOW).collected is True


def test_baseline_days_from_traffic_coverage(tmp_path):
    ctx = configured_ctx(tmp_path)
    assert load_lateral_context(ctx, now=NOW).baseline_days == 0
    _covered(ctx, (NOW - timedelta(days=10), NOW))
    lc = load_lateral_context(ctx, now=NOW)
    assert lc.baseline_days == 10 and lc.baseline_required == 30 and not lc.baseline_full()
    _covered(ctx, (NOW - timedelta(days=45), NOW - timedelta(days=10)))
    lc = load_lateral_context(ctx, now=NOW)
    assert lc.baseline_days == 30 and lc.baseline_full()


def test_baseline_days_ignores_disconnected_backfill_range(tmp_path):
    ctx = configured_ctx(tmp_path)
    _covered(ctx, (NOW - timedelta(days=30), NOW - timedelta(days=29)), (NOW - timedelta(days=2), NOW))
    assert load_lateral_context(ctx, now=NOW).baseline_days == 2


def test_baseline_not_full_while_initial_backfill_runs(tmp_path):
    ctx = configured_ctx(tmp_path)
    _covered(ctx, (NOW - timedelta(days=31), NOW))
    with ctx.flows().connect() as conn:
        ingest_state.set_progress(conn, IngestSource.BACKFILL, {"initial": {"finished": False}})
    lc = load_lateral_context(ctx, now=NOW)
    assert lc.baseline_backfilling and not lc.baseline_full()
    with ctx.flows().connect() as conn:
        ingest_state.set_progress(conn, IngestSource.BACKFILL, {"initial": {"finished": True}})
    assert load_lateral_context(ctx, now=NOW).baseline_full()


def test_known_labels_come_from_current_inventory(tmp_path):
    ctx = configured_ctx(tmp_path)
    _lateral(ctx, critical_assets=[{"key": "app", "value": "Finance"}, {"key": "app", "value": "Gone"}],
             admin_groups=[{"key": "role", "value": "Nope"}])
    _inventory(ctx)
    lc = load_lateral_context(ctx, now=NOW)
    assert ("app", "Gone") not in lc.known_labels and ("role", "Jump") in lc.known_labels
    assert set(lc.stale) == {("critical_assets", "app", "Gone"), ("admin_groups", "role", "Nope")}
