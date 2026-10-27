"""The findings engine over the flow store (P5b-1 Task 2): 5.x B001–B009 and L001–L010, one period read."""
from datetime import UTC, datetime, timedelta

import pytest

from illumio_ops.domain.filter import FilterSpec
from illumio_ops.domain.flows import normalize_flow
from illumio_ops.domain.values import DataOrigin, Language, Severity
from illumio_ops.services.reports import findings
from illumio_ops.store.flowdb import analysis
from illumio_ops.store.flowdb.flows import upsert_flows
from tests_v6.services.collect.conftest import configured_ctx, raw_flow

NOW = datetime(2026, 10, 27, 1, 0, tzinfo=UTC)
SPEC = FilterSpec(start=datetime(2026, 10, 20, tzinfo=UTC), end=datetime(2026, 10, 27, tzinfo=UTC))
_n = iter(range(1, 1_000_000))


def flow(*, src=None, dst="db", port=445, proto=6, decision="allowed", src_env="Dev", dst_env="Dev", src_app="Web",
         dst_app="DB", user=None, unmanaged_src=False, unmanaged_dst=False, bytes_=None, conns=1):
    i = next(_n)
    first = datetime(2026, 10, 22, 3, tzinfo=UTC) + timedelta(seconds=i)
    raw = raw_flow(i, first, first + timedelta(minutes=5), port=port, user=user)
    raw["service"]["proto"] = proto
    raw["policy_decision"] = decision
    raw["num_connections"] = conns
    src_name = src or f"s{i}"
    if unmanaged_src:
        raw["src"] = {"ip": f"10.9.{i // 250 % 250}.{i % 250}"}
    else:
        raw["src"]["workload"].update(href=f"/orgs/1/workloads/{src_name}", hostname=src_name,
                                      labels=[{"key": "env", "value": src_env}, {"key": "app", "value": src_app}])
    if unmanaged_dst:
        raw["dst"] = {"ip": f"203.0.113.{i % 250}"}
    else:
        raw["dst"]["workload"].update(href=f"/orgs/1/workloads/{dst}", hostname=dst,
                                      labels=[{"key": "env", "value": dst_env}, {"key": "app", "value": dst_app}])
        raw["dst"]["ip"] = f"10.0.2.{abs(hash(dst)) % 250}"
    if bytes_ is not None:
        raw["dst_bi"], raw["dst_bo"] = bytes_, 0
    return normalize_flow(raw)


@pytest.fixture
def ctx(tmp_path):
    return configured_ctx(tmp_path)


def _write(ctx, flows):
    with ctx.flows().connect() as conn:
        upsert_flows(conn, flows, origin=DataOrigin.INGEST, now=NOW)


def run(ctx, **thresholds):
    t = ctx.settings.current().reports.rule_thresholds.model_copy(update=thresholds)
    return {o.rule_id: o for o in findings.run_rules(ctx, SPEC, t, Language.EN, now=NOW)}


def test_b001_cross_env_without_ip_heuristic(ctx):
    _write(ctx, [flow(port=445, src_env="Dev", dst_env="Prod"), flow(port=445)])
    o = run(ctx)["B001"]
    assert o.severity is Severity.CRITICAL and o.params["n_cross_env"] == 1 and o.params["n_total"] == 2


def test_b001_allowed_same_env_high_and_pb_medium(tmp_path):
    a = configured_ctx(tmp_path / "a")
    _write(a, [flow(port=3389)])
    assert run(a)["B001"].severity is Severity.HIGH
    b = configured_ctx(tmp_path / "b")
    _write(b, [flow(port=3389, decision="potentially_blocked")])
    assert run(b)["B001"].severity is Severity.MEDIUM


def test_b001_blocked_and_udp_reply_ignored(ctx):
    _write(ctx, [flow(port=445, decision="blocked"), flow(port=445, proto=17)])
    assert "B001" not in run(ctx)


def test_b002_high_remote_access_allowed(ctx):
    _write(ctx, [flow(port=5900)])
    assert run(ctx)["B002"].severity is Severity.HIGH


def test_b003_medium_port_pb(ctx):
    _write(ctx, [flow(port=22, decision="potentially_blocked"), flow(port=80)])
    o = run(ctx)["B003"]
    assert o.severity is Severity.MEDIUM and o.params["n_flows"] == 1


def test_b004_unmanaged_sources(ctx):
    _write(ctx, [flow(port=443, unmanaged_src=True) for _ in range(3)])
    assert run(ctx, unmanaged_connection=2)["B004"].params["n_flows"] == 3
    assert "B004" not in run(ctx, unmanaged_connection=3)


def test_b005_low_policy_coverage(ctx):
    _write(ctx, [flow(port=443, decision="potentially_blocked") for _ in range(3)] + [flow(port=443)])
    o = run(ctx)["B005"]
    assert o.severity is Severity.MEDIUM and o.params["coverage_pct"] == "25.0"


def test_b006_fanout_on_management_ports(ctx):
    _write(ctx, [flow(src="jump", dst=f"t{i}", port=22) for i in range(4)])
    o = run(ctx, lateral_outbound_dst=3)["B006"]
    assert o.severity is Severity.HIGH and "jump" in o.params["top_sources"]
    assert "B006" not in run(ctx, lateral_outbound_dst=4)


def test_b007_user_destinations(ctx):
    _write(ctx, [flow(dst=f"t{i}", port=443, user="CORP\\alice") for i in range(3)])
    assert run(ctx, user_destination=2)["B007"].severity is Severity.HIGH


def test_b008_byte_outliers_need_byte_data(ctx):
    _write(ctx, [flow(dst=f"t{i}", port=443, bytes_=1000) for i in range(20)] +
           [flow(dst="big", port=443, bytes_=50 * 1024 * 1024)])
    o = run(ctx)["B008"]
    assert o.severity is Severity.MEDIUM and o.params["n_outliers"] == 1 and "big" in o.params["top_pairs"]


def test_b009_cross_env_volume(ctx):
    _write(ctx, [flow(port=443, src_env="Dev", dst_env="Prod") for _ in range(3)])
    assert run(ctx, cross_env_connection=2)["B009"].severity is Severity.LOW


def test_l001_cleartext(ctx):
    _write(ctx, [flow(port=23, decision="blocked")])
    assert run(ctx)["L001"].severity is Severity.MEDIUM


def test_l003_db_from_many_apps(ctx):
    _write(ctx, [flow(dst="sql", port=1433, src_app=f"A{i}") for i in range(3)])
    assert run(ctx, db_unique_src_app=2)["L003"].severity is Severity.HIGH


def test_l004_db_across_env(ctx):
    _write(ctx, [flow(dst="sql", port=5432, src_env="Dev", dst_env="Prod")])
    assert run(ctx)["L004"].severity is Severity.HIGH


def test_l005_identity_from_many_apps(ctx):
    _write(ctx, [flow(dst="dc", port=389, src_app=f"A{i}", decision="potentially_blocked") for i in range(4)])
    assert run(ctx)["L005"].severity is Severity.MEDIUM


def test_l006_reads_exposure(ctx):
    _write(ctx, [flow(port=443)])
    with ctx.flows().connect() as conn:
        analysis.write_result(conn, "exposure", params={}, at=NOW, result={
            "hosts": [{"key": "/orgs/1/workloads/hub", "reach_now": 9}, {"key": "/orgs/1/workloads/x", "reach_now": 1}]})
        conn.commit()
    o = run(ctx)["L006"]
    assert o.severity is Severity.HIGH and o.params["n_hosts"] == 1


def test_l007_unmanaged_to_critical(ctx):
    _write(ctx, [flow(port=445, unmanaged_src=True) for _ in range(2)])
    assert run(ctx, unmanaged_critical=2)["L007"].severity is Severity.HIGH


def test_l008_pb_lateral(ctx):
    _write(ctx, [flow(port=22, decision="potentially_blocked") for _ in range(2)])
    assert run(ctx, pb_lateral=2)["L008"].severity is Severity.HIGH


def test_l009_exfil_bytes(ctx):
    _write(ctx, [flow(port=443, unmanaged_dst=True, bytes_=2 * 1024 * 1024)])
    assert run(ctx, exfil_mb=1)["L009"].severity is Severity.HIGH
    assert "L009" not in run(ctx, exfil_mb=3)


def test_l010_cross_env_management(ctx):
    _write(ctx, [flow(port=22, src_env="Dev", dst_env="Prod") for _ in range(2)])
    assert run(ctx, cross_env_lateral=2)["L010"].severity is Severity.CRITICAL


def test_nothing_fires_on_quiet_traffic(ctx):
    _write(ctx, [flow(port=443)])
    assert run(ctx) == {}


def test_rule_error_is_reported_not_fatal(ctx, monkeypatch):
    _write(ctx, [flow(port=5900)])

    def boom(*a, **k):
        raise RuntimeError("bad rule")
    monkeypatch.setitem(findings.RULE_FUNCTIONS, "B001", boom)
    got = run(ctx)
    assert got["B001"].error == "RuntimeError: bad rule" and got["B002"].severity is Severity.HIGH


def test_rules_share_one_period_read(ctx, monkeypatch):
    _write(ctx, [flow(port=445), flow(port=5900)])
    seen: list[str] = []
    real = findings.reads.reading

    class Spy:
        def __init__(self, ctx_):
            self.cm = real(ctx_)

        def __enter__(self):
            conn = self.cm.__enter__()
            conn.set_trace_callback(seen.append)
            return conn

        def __exit__(self, *exc):
            return self.cm.__exit__(*exc)
    monkeypatch.setattr(findings.reads, "reading", Spy)
    run(ctx)
    assert sum(" FROM flows " in s for s in seen) == 1


def test_thresholds_from_settings(ctx):
    ctx.settings.update(ctx.settings.current().revision,
                        lambda d: d["reports"]["rule_thresholds"].update(unmanaged_connection=1))
    _write(ctx, [flow(port=443, unmanaged_src=True) for _ in range(2)])
    got = {o.rule_id for o in findings.run_rules(ctx, SPEC, ctx.settings.current().reports.rule_thresholds,
                                                 Language.EN, now=NOW)}
    assert "B004" in got
