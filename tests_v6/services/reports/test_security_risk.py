"""The security risk report (P5b-1 Task 4): maturity from the inventory and the period's connections, the
uncovered traffic with what to do about it, enforcement progress by app, user and process coverage stated, the
ransomware and lateral summaries, and the rule engine's critical/high findings — every KPI shown (5.x showed 8)."""
from datetime import UTC, datetime

import pytest

from illumio_ops.domain.filter import EndpointFilter, FlowCondition, LabelCond
from illumio_ops.domain.report import TableBlock, TextBlock
from illumio_ops.domain.values import Language, ReportType, Severity
from illumio_ops.services.reports.registry import BuildInput, ReportParams, specs
from illumio_ops.services.reports.render_html import render_html
from illumio_ops.store.flowdb import analysis, labels, workloads
from tests_v6.services.collect.conftest import configured_ctx
from tests_v6.services.reports.test_findings import flow
from tests_v6.services.reports.test_traffic import _write

NOW = datetime(2026, 10, 27, 1, 0, tzinfo=UTC)
START, END = datetime(2026, 10, 20, tzinfo=UTC), datetime(2026, 10, 27, tzinfo=UTC)


def _inp(ctx, *, cond=None, lang=Language.EN):
    return BuildInput(ctx=ctx, params=ReportParams(report_type=ReportType.SECURITY_RISK, filter=cond), start=START,
                      end=END, lang=lang, tz=UTC, now=NOW, pce_label="pce")


def _build(ctx, **kw):
    return specs()[ReportType.SECURITY_RISK].build(_inp(ctx, **kw))


def _section(doc, sid):
    return next(s for s in doc.sections if s.id == sid)


def _tables(doc, sid):
    return [b for b in _section(doc, sid).blocks if isinstance(b, TableBlock)]


def _texts(doc, sid):
    return " ".join(p for b in _section(doc, sid).blocks if isinstance(b, TextBlock) for p in b.paragraphs)


def _inventory(ctx, hosts):
    """hosts: (name, enforcement_mode, app, env)."""
    with ctx.flows().connect() as conn:
        rows = []
        for name, mode, app, env in hosts:
            ls = labels.label_set_id(conn, (("app", app), ("env", env)))
            rows.append(workloads.WorkloadRow(
                href=f"/orgs/1/workloads/{name}", hostname=name, name=None, managed=1, enforcement_mode=mode,
                visibility_level=None, os_id=None, ven_version=None, ven_href=None, label_set=ls, online=1,
                risk_exposure=None, risk_percent=None, risk_updated_at=None, fetched_at="x"))
        workloads.replace_inventory(conn, rows)
        conn.commit()


@pytest.fixture
def ctx(tmp_path):
    return configured_ctx(tmp_path)


def test_uncovered_recommendation_kinds(ctx):
    _write(ctx, [flow(port=8080, decision="potentially_blocked", src_app="Web", dst_app="Web"),
                 flow(port=8080, decision="potentially_blocked", src_app="Web", dst_app="DB"),
                 flow(port=8080, decision="potentially_blocked", unmanaged_src=True, dst_app="DB")])
    rows = {(r[0], r[1]): r[-1] for r in _tables(_build(ctx), "uncovered")[0].rows}
    assert "same app" in rows[("Web", "Web")].lower()
    assert "between" in rows[("Web", "DB")].lower()
    assert "label" in rows[("(no label)", "DB")].lower()


def test_enforcement_progress_by_app(ctx):
    _inventory(ctx, [("a1", "full", "Web", "Prod"), ("a2", "selective", "Web", "Prod"),
                     ("a3", "visibility_only", "Web", "Prod"), ("b1", "idle", "DB", "Prod")])
    _write(ctx, [flow(port=443)])
    rows = {r[0]: r for r in _tables(_build(ctx), "enforcement")[0].rows}
    assert rows["Web (Prod)"][1:6] == (3, 1, 1, 1, 0) and rows["DB (Prod)"][1:6] == (1, 0, 0, 0, 1)


def test_maturity_from_inventory_and_connections(ctx):
    _inventory(ctx, [("a1", "full", "Web", "Prod"), ("a2", "selective", "Web", "Prod")])
    _write(ctx, [flow(port=443, conns=3), flow(port=8080, decision="potentially_blocked", conns=1)])
    doc = _build(ctx)
    kpi = {k.key: k for k in doc.kpis}
    # enforcement 0.75 x40, policy 0.75 x25, lateral 1 x15, managed 1 x10; no ransomware data: out of 90
    assert kpi["maturity"].value == pytest.approx(round(100 * (30 + 18.75 + 15 + 10) / 90, 1))
    assert "B" in kpi["maturity"].note


def test_zero_user_coverage_says_so(ctx):
    _write(ctx, [flow(port=443)])
    doc = _build(ctx)
    assert not any("user" in t.title.lower() for t in _tables(doc, "users"))
    assert "0.0%" in _texts(doc, "users")


def test_users_ranked_when_present(ctx):
    _write(ctx, [flow(dst=f"t{i}", port=443, user="CORP\\alice") for i in range(3)] +
           [flow(dst=f"n{i}", port=443) for i in range(5)])  # flows without a user are not a "(none)" user
    users = next(t for t in _tables(_build(ctx), "users") if "user" in t.title.lower())
    assert users.rows == (("corp\\alice", 3),)


def test_filter_with_no_flows_says_so(ctx):
    _write(ctx, [flow(port=443)])
    cond = FlowCondition(dst=EndpointFilter(labels=(LabelCond(key="app", values=("Nope",)),)))
    doc = _build(ctx, cond=cond)
    flow_kpis = [k for k in doc.kpis if k.key in ("allowed_pct", "pb_flows", "blocked_flows", "unmanaged_connections",
                                                  "admin_open_connections")]
    assert flow_kpis and all(k.value is None and k.note for k in flow_kpis)
    assert any("Destination app = Nope" in q for q in doc.data_quality)
    assert "filter" in _tables(doc, "uncovered")[0].empty_text.lower()


def test_all_kpis_rendered(ctx):
    _write(ctx, [flow(port=5900)])
    doc = _build(ctx)
    html = render_html(doc, tz=UTC)
    assert len(doc.kpis) >= 9 and all(k.label in html for k in doc.kpis)


def test_key_findings_critical_high_only(ctx):
    _write(ctx, [flow(port=22, decision="potentially_blocked"), flow(port=5900)])
    doc = _build(ctx)
    assert doc.findings and all(f.severity in (Severity.CRITICAL, Severity.HIGH) for f in doc.findings)
    assert any(r[0] == "B003" for r in _tables(doc, "findings")[0].rows)  # the full list keeps the medium one


def test_ransomware_summary(tmp_path):
    a = configured_ctx(tmp_path / "a")
    _write(a, [flow(port=443)])
    assert "not been computed" in _texts(_build(a), "ransomware")
    b = configured_ctx(tmp_path / "b")
    _write(b, [flow(port=443)])
    with b.flows().connect() as conn:
        analysis.write_result(conn, "ransomware", params={}, at=NOW, result={
            "unsupported": False, "contradictions": 0, "safe_to_block": [], "suspicious": [],
            "priority": [{"host": "/orgs/1/workloads/db", "hostname": "db", "name": "SMB", "port": 445, "proto": 6,
                          "severity": "critical", "weight": 40, "recent_sources": 3}],
            "hosts": [{"href": "/orgs/1/workloads/db", "services": [
                {"severity": "critical", "protection_state": "unprotected"},
                {"severity": "high", "protection_state": "protected_open"},
                {"severity": "low", "protection_state": "unprotected"}]}]})
        conn.commit()
    doc = _build(b)
    assert _tables(doc, "ransomware")[0].rows[0][:2] == ("db", "SMB")
    assert {k.key: k.value for k in doc.kpis}["ransomware_protected_pct"] == 50.0


def test_lateral_summary_points_to_report(ctx):
    _write(ctx, [flow(port=443)])
    assert "Lateral movement posture" in _texts(_build(ctx), "lateral")


def test_zh_tw_builds(ctx):
    _write(ctx, [flow(port=5900)])
    doc = _build(ctx, lang=Language.ZH_TW)
    assert doc.title and doc.findings[0].title == "勒索軟體高風險遠端存取 Port"
