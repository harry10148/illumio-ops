"""The app summary report (P5b-1 Task 6): one application's inbound, outbound and intra-app traffic, its policy
impact and hosts, and the rule findings over its flows only. The app is the report filter's app label, matched
exactly (5.x readiness lowercased it, app_summary did not)."""
from datetime import UTC, datetime

import pytest

from illumio_ops.domain.filter import EndpointFilter, FlowCondition, LabelCond
from illumio_ops.domain.report import TableBlock, TextBlock
from illumio_ops.domain.values import Language, ReportType
from illumio_ops.services.reports import generate
from illumio_ops.services.reports.registry import BuildInput, ReportParams, specs
from illumio_ops.store.flowdb import labels, workloads
from tests.services.collect.conftest import configured_ctx
from tests.services.reports.test_findings import covered, flow
from tests.services.reports.test_traffic import _write

NOW = datetime(2026, 10, 27, 1, 0, tzinfo=UTC)
START, END = datetime(2026, 10, 20, tzinfo=UTC), datetime(2026, 10, 27, tzinfo=UTC)


def _app(app, env=None):
    conds = (LabelCond(key="app", values=(app,)),) + ((LabelCond(key="env", values=(env,)),) if env else ())
    return FlowCondition(dst=EndpointFilter(labels=conds))


def _build(ctx, cond, lang=Language.EN, report_type=ReportType.APP_SUMMARY):
    return specs()[report_type].build(BuildInput(
        ctx=ctx, params=ReportParams(report_type=report_type, filter=cond), start=START, end=END, lang=lang, tz=UTC,
        now=NOW, pce_label="pce"))


def _section(doc, sid):
    return next(s for s in doc.sections if s.id == sid)


def _table(doc, sid, i=0):
    return [b for b in _section(doc, sid).blocks if isinstance(b, TableBlock)][i]


@pytest.fixture
def ctx(tmp_path):
    return configured_ctx(tmp_path)


def test_app_required(ctx):
    spec = specs()[ReportType.APP_SUMMARY]
    assert spec.requires_app
    assert generate.refusal(ctx.settings.current(), ReportParams(report_type=ReportType.APP_SUMMARY)) == \
        "rpt_err_app_required"
    assert generate.refusal(ctx.settings.current(),
                            ReportParams(report_type=ReportType.APP_SUMMARY, filter=_app("Finance"))) is None


def test_inbound_outbound_split(ctx):
    _write(ctx, [flow(src_app="Web", dst_app="Finance", port=443, conns=4),
                 flow(src_app="Finance", dst_app="DB", port=5432, conns=2),
                 flow(src_app="Finance", dst_app="Finance", port=8080, conns=1)])
    doc = _build(ctx, _app("Finance"))
    assert _table(doc, "inbound").rows == (("Web", "443/TCP", 4),)
    assert _table(doc, "outbound").rows == (("DB", "5432/TCP", 2),)
    assert _table(doc, "intra").rows == (("8080/TCP", 1),)


def test_intra_app_counted_once(ctx):
    _write(ctx, [flow(src_app="Web", dst_app="Finance", port=443), flow(src_app="Finance", dst_app="Finance", port=8080),
                 flow(src_app="Finance", dst_app="DB", port=5432, decision="potentially_blocked")])
    doc = _build(ctx, _app("Finance"))
    rows = {r[0]: r[1] for r in _table(doc, "impact").rows}
    assert rows == {"Allowed (a rule allows it)": 2, "Potentially Blocked (blocked once enforcement starts)": 1,
                    "Blocked": 0}  # the three decisions, always (stage 3b)
    kpi = {k.key: k.value for k in doc.kpis}
    assert kpi["inbound_connections"] == 1 and kpi["outbound_connections"] == 1 and kpi["intra_connections"] == 1
    assert kpi["pb_flows"] == 1


def test_app_match_is_exact_everywhere(ctx):
    _write(ctx, [flow(src_app="Web", dst_app="Finance", port=443, conns=3),
                 flow(src_app="Web", dst_app="finance", port=443, conns=5)])
    assert _table(_build(ctx, _app("Finance")), "inbound").rows == (("Web", "443/TCP", 3),)
    inv = _build(ctx, None, report_type=ReportType.NETWORK_INVENTORY)
    assert {r[0] for r in _table(inv, "services").rows} == {"Finance", "finance"}


def test_env_narrows_the_app(ctx):
    _write(ctx, [flow(src_app="Web", dst_app="Finance", dst_env="Prod", port=443, conns=3),
                 flow(src_app="Web", dst_app="Finance", dst_env="Dev", port=443, conns=5)])
    doc = _build(ctx, _app("Finance", "Prod"))
    assert _table(doc, "inbound").rows == (("Web", "443/TCP", 3),) and "Finance" in doc.title and "Prod" in doc.title


def test_hosts_of_the_app(ctx):
    with ctx.flows().connect() as conn:
        workloads.replace_inventory(conn, [workloads.WorkloadRow(
            href=f"/orgs/1/workloads/{n}", hostname=n, name=None, managed=1, enforcement_mode=mode,
            visibility_level=None, os_id=None, ven_version=None, ven_href=None,
            label_set=labels.label_set_id(conn, (("app", app), ("env", "Prod"))), online=1, risk_exposure=None,
            risk_percent=None, risk_updated_at=None, fetched_at="x")
            for n, app, mode in (("f1", "Finance", "full"), ("f2", "finance", "idle"), ("w1", "Web", "full"))])
        conn.commit()
    _write(ctx, [flow(src_app="Web", dst_app="Finance", port=443)])
    doc = _build(ctx, _app("Finance"))
    hosts = _table(doc, "hosts")
    assert hosts.rows == (("f1", "Prod", "Blocking everything (Full)"),)  # the mode in plain words, the PCE's beside
    assert hosts.host_keys == {"host": ("/orgs/1/workloads/f1",)} and hosts.columns[0].kind == "host"
    assert {k.key: k.value for k in doc.kpis}["enforced_hosts_pct"] == 100.0


def test_findings_only_this_app(ctx):
    _write(ctx, [flow(src_app="Web", dst_app="Other", port=5900), flow(src_app="Web", dst_app="Finance", port=443)])
    doc = _build(ctx, _app("Finance"))
    assert not any("Ransomware Risk Port" in f.title for f in doc.findings)
    _write(ctx, [flow(src_app="Finance", dst_app="Other", port=5900)])
    doc = _build(ctx, _app("Finance"))
    assert any("Ransomware Risk Port" in f.title for f in doc.findings)
    assert all(f.what and f.why and f.action_code and f.action_short for f in doc.findings)
    # a rule that fired is a finding, never a row of the closing section
    assert not any(r[0] == "B002" for s in doc.sections if s.id == "findings" for r in s.blocks[0].rows)


def test_as_many_findings_as_rules_that_fired(ctx, monkeypatch):
    """Stage 3a: none held back (the summary showed the first five)."""
    from illumio_ops.services.reports import findings
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["reports"]["rule_thresholds"].update(
        unmanaged_connection=1, lateral_outbound_dst=1, cross_env_connection=1, discovery_protocol=1, pb_lateral=1))
    _write(ctx, [flow(src_app="Finance", dst_app="X", port=p, **kw) for p, kw in (
        (5900, {}), (445, {"src_env": "Dev", "dst_env": "Prod"}), (22, {"decision": "potentially_blocked"}),
        (23, {"decision": "blocked"}), (137, {"proto": 17}), (1433, {"src_env": "Dev", "dst_env": "Prod"}))])
    seen = []
    real = findings.run_rules

    def spy(*a, **k):
        seen.append(real(*a, **k))
        return seen[-1]
    monkeypatch.setattr(findings, "run_rules", spy)
    doc = _build(ctx, _app("Finance"))
    fired = [o for o in seen[0] if o.severity is not None]
    assert len(seen) == 1 and len(fired) > 5 and len(doc.findings) == len(fired)


def test_zh_tw_builds(ctx):
    _write(ctx, [flow(src_app="Web", dst_app="Finance", port=443)])
    assert "Finance" in _build(ctx, _app("Finance"), Language.ZH_TW).title


def test_exposure_finding_limited_to_the_app(ctx):
    from illumio_ops.store.flowdb import analysis
    _write(ctx, [flow(src_app="Web", dst_app="Finance", port=443)])
    with ctx.flows().connect() as conn:
        analysis.write_result(conn, "exposure", params={}, at=NOW, result={
            "hosts": [{"key": "/orgs/1/workloads/elsewhere", "reach_now": 50}]})
        conn.commit()
    doc = _build(ctx, _app("Finance"))
    # L006 was evaluated on the app's own hosts and did not fire: no finding, and no closing section to list it in
    assert doc.findings == () and "findings" not in {s.id for s in doc.sections}


# ── stage 3b: a share counts only the flows the PCE gave a decision for ──────────────────────────────────────

NO_DECIDED = "No flow in this period carries a decision, so no share can be worked out."


def _words(doc, sid):
    return " ".join(p for b in _section(doc, sid).blocks if isinstance(b, TextBlock) for p in b.paragraphs)


def test_allowed_share_is_of_the_apps_decided_connections(ctx):
    _write(ctx, [flow(src_app="Web", dst_app="Finance", port=443, conns=10),
                 flow(src_app="Finance", dst_app="DB", port=5432, decision="potentially_blocked", conns=30),
                 flow(src_app="Finance", dst_app="Finance", port=8080, decision="unknown", conns=60)])
    doc = _build(ctx, _app("Finance"))
    kpi = {k.key: k for k in doc.kpis}
    assert kpi["allowed_pct"].value == 25.0  # 10 of the 40 connections with a decision, not 10 of 100
    assert kpi["intra_connections"].value == 60  # what was seen keeps the connections without a decision
    assert _table(doc, "impact").rows == (
        ("Allowed (a rule allows it)", 1, 10, "50.0%"),
        ("Potentially Blocked (blocked once enforcement starts)", 1, 30, "50.0%"), ("Blocked", 0, 0, "0.0%"))
    words = _words(doc, "impact")
    assert "25.0% of the app's connections with a decision are allowed by a rule" in words
    assert "Flows without one: 1 (connections: 60); see “Traffic that can only be watched”." in words


def test_an_app_with_no_decided_flow_has_no_share_and_still_an_opening_sentence(ctx):
    from illumio_ops.domain.conclusion import conclusion, incomplete
    from illumio_ops.i18n import translate
    from illumio_ops.services.reports.finish import finish
    _write(ctx, [flow(src_app="Web", dst_app="Finance", port=443, decision="unknown", conns=7)])
    doc = finish(_build(ctx, _app("Finance")))
    kpi = {k.key: k for k in doc.kpis}
    assert kpi["allowed_pct"].value is None and kpi["allowed_pct"].note == NO_DECIDED
    assert kpi["inbound_connections"].value == 7 and kpi["pb_flows"].value == 0
    assert not incomplete(doc)
    assert conclusion(doc, lambda key, p: translate(doc.lang, key, p), tz=UTC) == (
        "Connections inbound: 7, outbound: 0, within the app: 0.")
    zh = finish(_build(ctx, _app("Finance"), Language.ZH_TW))
    assert conclusion(zh, lambda key, p: translate(zh.lang, key, p), tz=UTC) == "連線次數：連入 7、連出 0、App 內 0。"
    table = _table(doc, "impact")
    assert table.rows == () and table.empty_text == NO_DECIDED
    assert "are allowed by a rule" not in _words(doc, "impact")  # no share of nothing in a sentence either


# ── stage 3b: the app's flows without a decision have their chapter ──────────────────────────────────────────

def test_the_apps_undecided_flows_have_their_chapter_and_a_sentence_on_the_first_page(ctx):
    _write(ctx, [flow(src_app="Web", dst_app="Finance", port=443, conns=10),
                 flow(src_app="Web", dst_app="Finance", port=8443, decision="unknown", conns=5),       # inbound
                 flow(src_app="Finance", dst_app="DB", port=5432, decision="unknown", conns=3),        # outbound
                 flow(src_app="Finance", dst_app="Finance", port=8080, decision="unknown", conns=2),   # within the app
                 flow(dst_app="Finance", port=9, decision="unknown", unmanaged_src=True, conns=7),     # inbound
                 flow(src_app="Web", dst_app="Other", port=443, decision="unknown", conns=100)])       # not the app's
    covered(ctx)
    doc = _build(ctx, _app("Finance"))
    ids = [s.id for s in doc.sections]
    assert ids[ids.index("monitor_only") - 1] == "uncovered"
    kinds = _table(doc, "monitor_only")
    # the app's 5 flows and 27 connections: 4 flows (17 connections) carry no decision, every one with a VEN on an end
    assert [(r[0], *r[2:]) for r in kinds.rows] == [("Neither end has a VEN", 0, 0, "0.0%", "0.0%"),
                                                    ("At least one end has a VEN", 4, 17, "80.0%", "63.0%")]
    tables = {b.title: b for b in _section(doc, "monitor_only").blocks if isinstance(b, TableBlock)}
    # the rankings read the app's flows in either direction, once each: they add up to what the three parts counted
    src = tables["Top sources, at least one end has a VEN"]
    assert (sum(r[1] for r in src.rows), sum(r[2] for r in src.rows)) == (4, 17)
    assert "Top sources, neither end has a VEN" not in tables
    (said,) = doc.caveats
    assert said == ("Flows without a decision: 80.0% of the period's flows (63.0% by connections). The report's shares "
                    "count only the flows with a decision; the rest are in “Traffic that can only be watched”.")


def test_an_app_whose_flows_all_carry_a_decision_has_no_chapter_and_no_sentence(ctx):
    _write(ctx, [flow(src_app="Web", dst_app="Finance", port=443),
                 flow(src_app="Web", dst_app="Other", port=443, decision="unknown")])  # not the app's
    covered(ctx)
    doc = _build(ctx, _app("Finance"))
    assert "monitor_only" not in [s.id for s in doc.sections] and doc.caveats == ()
