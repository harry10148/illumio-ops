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
from tests.services.collect.conftest import configured_ctx
from tests.services.reports.test_findings import (
    UNDECIDED_EN,
    UNDECIDED_ZH,
    covered,
    decided_and_not,
    flow,
    undecided_sample,
)
from tests.services.reports.test_traffic import _write

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
    table = _tables(_build(ctx), "enforcement")[0]
    assert [c.label for c in table.columns[2:6]] == ["Blocking everything (Full)", "Blocking some (Selective)",
                                                     "Recording only (Visibility Only)", "Not blocking yet (Idle)"]
    rows = {r[0]: r for r in table.rows}
    assert rows["Web (Prod)"][1:6] == (3, 1, 1, 1, 0) and rows["DB (Prod)"][1:6] == (1, 0, 0, 0, 1)


def test_maturity_from_inventory_and_connections(ctx):
    _inventory(ctx, [("a1", "full", "Web", "Prod"), ("a2", "selective", "Web", "Prod")])
    _write(ctx, [flow(port=443, conns=3), flow(port=8080, decision="potentially_blocked", conns=1)])
    doc = _build(ctx)
    kpi = {k.key: k for k in doc.kpis}
    # enforcement 0.75 x40, policy 0.75 x25, lateral 1 x15, managed 1 x10; no ransomware data: out of 90
    assert kpi["maturity"].value == round(100 * (30 + 18.75 + 15 + 10) / 90)  # whole points
    assert "B" in kpi["maturity"].note


def test_zero_user_coverage_says_so(ctx):
    _write(ctx, [flow(port=443)])
    doc = _build(ctx)
    # 6.6.0: no flow names a user or a process — the section is left out and one data note says so
    assert "users" not in {s.id for s in doc.sections}
    assert sum("names the initiating user or process" in q for q in doc.data_quality) == 1


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


def test_every_fired_rule_is_a_finding_and_the_number_still_counts_critical_and_high(ctx):
    """Stage 3a: the findings are every rule that fired (they were the critical and high ones only); the key number
    "critical / high findings" is computed as before."""
    from illumio_ops.services.reports import findings, flowsections
    _write(ctx, [flow(port=22, decision="potentially_blocked"), flow(port=5900)])
    doc = _build(ctx)
    outcomes = findings.run_rules(ctx, flowsections.window(_inp(ctx)), ctx.settings.current().reports.rule_thresholds,
                                  Language.EN, now=NOW)
    fired = [o for o in outcomes if o.severity is not None]
    assert len(doc.findings) == len(fired)
    severities = {f.severity for f in doc.findings}
    assert Severity.MEDIUM in severities and Severity.HIGH in severities  # B003 (medium) is a finding now
    high = sum(1 for f in doc.findings if f.severity in (Severity.CRITICAL, Severity.HIGH))
    assert 0 < high < len(doc.findings)
    assert {k.key: k.value for k in doc.kpis}["critical_high_findings"] == high
    # the closing section holds only what could not be evaluated (no exposure graph here: L006)
    assert [r[0] for r in _tables(doc, "findings")[0].rows] == ["L006"]


def test_ransomware_summary(tmp_path):
    a = configured_ctx(tmp_path / "a")
    _write(a, [flow(port=443)])
    doc = _build(a)  # 6.6.0: not computed yet — no section, no number, one data note
    assert "ransomware" not in {s.id for s in doc.sections}
    assert "ransomware_protected_pct" not in {k.key for k in doc.kpis}
    assert sum("ransomware analysis has not been computed" in q for q in doc.data_quality) == 1
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
    assert doc.title and doc.findings[0].title == "勒索軟體高風險遠端存取 port"


# ── readable (2026-10-29: customers could not read the scores; keep them, explain them) ──────────────────────

def test_how_maturity_is_scored_with_this_periods_points(ctx):
    _inventory(ctx, [("a1", "full", "Web", "Dev"), ("a2", "visibility_only", "Web", "Dev")])
    _write(ctx, [flow(port=443, conns=3), flow(port=443, decision="potentially_blocked", conns=7)])
    doc = _build(ctx)
    assert doc.sections[0].id == "how"
    parts, grades = _tables(doc, "how")
    assert len(parts.rows) == 5 and {r[3] for r in parts.rows} == {"40", "25", "15", "10"}
    enforced = next(r for r in parts.rows if r[0] == "Hosts enforced")
    assert enforced[4].startswith("20 of 40")  # half the hosts enforced: 20 of its 40 points
    assert [r[0] for r in grades.rows] == ["A", "B", "C", "D", "F"]


def test_maturity_note_names_the_part_losing_most_and_the_score_without_it(ctx):
    _inventory(ctx, [("a1", "full", "Web", "Dev")])
    _write(ctx, [flow(port=443, decision="potentially_blocked", conns=10)])
    k = {x.key: x for x in _build(ctx).kpis}["maturity"]
    assert k.unit == "count" and isinstance(k.value, int)
    assert "Allowed by a rule" in k.note and "about" in k.note


# ── stage 3b: a share counts only the flows the PCE gave a decision for ──────────────────────────────────────

NO_DECIDED = "No flow in this period carries a decision, so no share can be worked out."
DECISIONS = ["Allowed (a rule allows it)", "Potentially Blocked (blocked once enforcement starts)", "Blocked"]


def test_shares_and_counts_rest_on_the_decided_flows(ctx):
    _write(ctx, decided_and_not())
    doc = _build(ctx)
    kpi = {k.key: k for k in doc.kpis}
    assert kpi["allowed_pct"].value == 25.0  # 10 of the 40 connections with a decision, not 10 of 100
    assert kpi["unmanaged_connections"].value == 4 and kpi["admin_open_connections"].value == 2
    assert kpi["unmanaged_connections"].label == "Connections with a decision from unmanaged sources"
    assert kpi["unmanaged_connections"].note == kpi["admin_open_connections"].note == (
        "Counts only connections with a decision; the ones without are in “Traffic that can only be watched”.")
    assert (kpi["pb_flows"].value, kpi["blocked_flows"].value) == (1, 0)


def test_coverage_table_is_the_three_decisions_and_says_how_many_flows_have_none(ctx):
    _write(ctx, decided_and_not())
    doc = _build(ctx)
    table = _tables(doc, "coverage")[0]
    assert [r[0] for r in table.rows] == DECISIONS
    assert [r[1] for r in table.rows] == [3, 1, 0] and [r[2] for r in table.rows] == ["75.0%", "25.0%", "0.0%"]
    assert sum(float(r[2].rstrip("%")) for r in table.rows) == 100.0
    words = _texts(doc, "coverage")
    assert ("Shares count only the flows with a decision. Flows without one: 2 (connections: 60); see “Traffic that "
            "can only be watched”.") in words
    # both directions over decided flows: 3 of 4 into managed hosts, 2 of 3 out of them (with the undecided: 60%, 50%)
    assert "Of flows with a decision into managed hosts, 75.0% are allowed by a rule" in words and "66.7%" in words


def test_no_note_about_undecided_flows_when_there_are_none(ctx):
    _write(ctx, [flow(port=443, unmanaged_src=True), flow(port=8080, decision="potentially_blocked")])
    doc = _build(ctx)
    assert "can only be watched" not in _texts(doc, "coverage")
    assert {k.key: k for k in doc.kpis}["unmanaged_connections"].note is None


def test_no_decided_flow_is_no_share_and_never_zero_percent(ctx):
    _inventory(ctx, [("a1", "full", "Web", "Prod")])
    _write(ctx, [flow(port=443, decision="unknown", conns=5), flow(port=22, decision="unknown", conns=5)])
    doc = _build(ctx)
    kpi = {k.key: k for k in doc.kpis}
    assert kpi["allowed_pct"].value is None and kpi["allowed_pct"].note == NO_DECIDED
    # counts of decided flows are counts: there are none
    assert (kpi["pb_flows"].value, kpi["unmanaged_connections"].value, kpi["admin_open_connections"].value) == (0, 0, 0)
    table = _tables(doc, "coverage")[0]
    assert table.rows == () and table.empty_text == NO_DECIDED
    assert "into managed hosts" not in _texts(doc, "coverage")  # no share of nothing in a sentence either
    # the three connection parts have no data; the score rests on the hosts (one, in full enforcement)
    parts = _tables(doc, "how")[0]
    assert [r[4] for r in parts.rows][1:4] == ["No data: not counted"] * 3 and kpi["maturity"].value == 100


def test_how_the_score_is_worked_out_says_which_connections_it_counts(ctx):
    _write(ctx, decided_and_not())
    doc = _build(ctx)
    parts = _tables(doc, "how")[0]
    measures = {r[0]: r[1] for r in parts.rows}
    assert "against all connections" not in " ".join(measures.values())
    for part in ("Management ports closed", "From managed sources", "Allowed by a rule"):
        assert "with a decision" in measures[part], part
    said = _texts(doc, "how")
    assert "count only the connections with a decision" in said and "6.10.0" in said
    # this period's points follow the decided denominator: 4 of 40 from unmanaged sources is 0.8 of the part's 10
    assert next(r for r in parts.rows if r[0] == "From managed sources")[4].startswith("8 of 10")
    zh = _build(ctx, lang=Language.ZH_TW)
    assert "只算有判定的連線" in _texts(zh, "how") and "6.10.0" in _texts(zh, "how")


# ── stage 3b: the flows without a decision have their chapter, and the first page says how many there are ────

def test_undecided_flows_have_their_chapter_before_the_rules_and_a_sentence_on_the_first_page(ctx):
    undecided_sample(ctx)
    covered(ctx)
    doc = _build(ctx)
    ids = [s.id for s in doc.sections]
    assert ids[ids.index("monitor_only") - 1] == "lateral" and ids[ids.index("monitor_only") + 1] == "findings"
    assert doc.caveats == (UNDECIDED_EN,)
    kinds = _tables(doc, "monitor_only")[0]
    assert [(r[2], r[3]) for r in kinds.rows] == [(1, 50), (4, 19)]
    assert _build(ctx, lang=Language.ZH_TW).caveats == (UNDECIDED_ZH,)


def test_no_undecided_flow_no_chapter_and_no_sentence(ctx):
    _write(ctx, [flow(port=443), flow(port=8080, decision="potentially_blocked")])
    covered(ctx)
    doc = _build(ctx)
    assert "monitor_only" not in [s.id for s in doc.sections] and doc.caveats == ()


def test_a_collection_gap_comes_before_the_undecided_sentence(ctx, monkeypatch):
    from illumio_ops.services.reports import security_risk
    from illumio_ops.services.reports.generate import CoverageText
    undecided_sample(ctx)
    monkeypatch.setattr(security_risk, "coverage_text",
                        lambda *a, **k: CoverageText(lines=("the gap, line by line",), caveats=("the gap sentence",)))
    doc = _build(ctx)
    assert len(doc.caveats) == 2 and doc.caveats[0] == "the gap sentence"
    assert doc.caveats[1].startswith("Flows without a decision: 55.6%")
