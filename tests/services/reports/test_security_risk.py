"""The security risk report (P5b-1 Task 4): maturity from the inventory and the period's connections, the
uncovered traffic by app pair and by port with what to do about it, enforcement progress by app, and the rule
engine's findings. Stage 3b: ransomware and lateral movement are a number and a sentence that name their own
reports; users and processes are a chapter of the traffic report (test_traffic)."""
from datetime import UTC, datetime

import pytest

from illumio_ops.domain.filter import EndpointFilter, FlowCondition, LabelCond
from illumio_ops.domain.report import TableBlock, TextBlock
from illumio_ops.domain.values import Language, ReportType, Severity
from illumio_ops.services.reports.registry import BuildInput, ReportParams, specs
from illumio_ops.services.reports.render_html import render_html
from illumio_ops.store.flowdb import analysis, labels, ransomware, workloads
from tests.services.collect.conftest import configured_ctx
from tests.services.reports.test_findings import (
    MOVED_PORT_GAPS,
    UNDECIDED_EN,
    UNDECIDED_ZH,
    as_moved,
    covered,
    decided_and_not,
    flow,
    moved_sample,
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
    # the eight this install has: no ransomware analysis, so no "ransomware services protected"
    assert len(doc.kpis) == 8 and all(k.label in html for k in doc.kpis)


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


def _ransomware_result(c):
    with c.flows().connect() as conn:
        analysis.write_result(conn, "ransomware", params={}, at=NOW, result={
            "unsupported": False, "contradictions": 0, "safe_to_block": [], "suspicious": [],
            "priority": [{"host": "/orgs/1/workloads/db", "hostname": "db", "name": "SMB", "port": 445, "proto": 6,
                          "severity": "critical", "weight": 40, "recent_sources": 3}],
            "hosts": [{"href": "/orgs/1/workloads/db", "services": [
                {"severity": "critical", "protection_state": "unprotected"},
                {"severity": "high", "protection_state": "protected_open"},
                {"severity": "low", "protection_state": "unprotected"}]}]})
        conn.commit()


def test_ransomware_is_one_number_that_names_its_report(tmp_path):
    """Stage 3b: the chapter is gone. What stays is the number (and the maturity score's part), with one fixed
    sentence that says where each host and service is listed."""
    a = configured_ctx(tmp_path / "a")
    _write(a, [flow(port=443)])
    doc = _build(a)  # 6.6.0: not computed yet — no number, one data note; the note names no chapter
    assert "ransomware" not in {s.id for s in doc.sections}
    assert "ransomware_protected_pct" not in {k.key for k in doc.kpis}
    (note,) = [q for q in doc.data_quality if "ransomware analysis has not been computed" in q]
    assert "section" not in note and "ransomware services protected" in note
    b = configured_ctx(tmp_path / "b")
    _write(b, [flow(port=443)])
    _ransomware_result(b)
    doc = _build(b)
    assert "ransomware" not in {s.id for s in doc.sections}
    kpi = {k.key: k for k in doc.kpis}["ransomware_protected_pct"]
    assert kpi.value == 50.0 and kpi.note == "Every host and service is in the “Ransomware protection” report."
    # the score still counts the part: 1 of the 2 critical and high services is protected, 5 of its 10 points
    part = next(r for r in _tables(doc, "how")[0].rows if r[0] == "Ransomware services protected")
    assert part[4].startswith("5 of 10")
    zh = {k.key: k for k in _build(b, lang=Language.ZH_TW).kpis}["ransomware_protected_pct"]
    assert zh.note == "各主機與服務的明細見〈勒索防護〉報表。"


def test_lateral_movement_is_one_sentence_that_names_its_report(ctx):
    """Stage 3b: no chapter and no "lateral detections" number; the policy coverage chapter says where they are."""
    _write(ctx, [flow(port=443)])
    doc = _build(ctx)
    assert "lateral" not in {s.id for s in doc.sections}
    assert "lateral_detections" not in {k.key for k in doc.kpis}
    assert ("Lateral-movement detections and what can be reached are in the “Lateral movement posture” report."
            in _texts(doc, "coverage"))
    assert "橫向移動的偵測與可觸及範圍見〈橫向移動態勢〉報表。" in _texts(_build(ctx, lang=Language.ZH_TW), "coverage")
    # the exposure analysis is not this report's to wait for any more: no data note about it
    assert not [q for q in doc.data_quality if "exposure" in q.lower()]


def test_a_period_without_traffic_still_folds_the_coverage_chapter(ctx):
    """The sentence about lateral movement is part of a chapter that has something to show; a period with no flow
    keeps the chapter one line under "Nothing to show this period", as before."""
    from illumio_ops.services.reports.finish import finish
    doc = finish(_build(ctx))
    assert "coverage" not in {s.id for s in doc.sections}
    assert any(p.startswith("Policy coverage: ") for b in _section(doc, "nothing").blocks for p in b.paragraphs)


# ── stage 3b: the report keeps what is its own ───────────────────────────────────────────────────────────────

def _everything(c):
    """An install where every chapter the report ever had would have content: hosts, uncovered traffic, flows
    without a decision, flows that name users and processes, a ransomware result."""
    undecided_sample(c)
    _write(c, moved_sample())
    _ransomware_result(c)


def test_the_chapters_in_reading_order(ctx):
    from illumio_ops.services.reports.finish import finish
    from tests.services.reports.dom import dom
    _everything(ctx)
    doc = finish(_build(ctx))
    # the builder puts "how" first; the page moves it to the closing part, before the data notes
    assert [s.id for s in doc.sections] == ["how", "coverage", "uncovered", "enforcement", "pb", "monitor_only",
                                            "findings"]
    page = dom(render_html(doc, tz=UTC))
    assert [n.attrs["id"] for n in page.find_attr("class", "chapter")] == [
        "coverage", "uncovered", "enforcement", "pb", "monitor_only", "findings", "how", "notes"]
    assert not {"ransomware", "lateral", "users", "ports"} & {s.id for s in doc.sections}


def test_ports_with_gaps_is_the_second_table_of_the_uncovered_chapter(ctx):
    """The table left its own chapter for this one with its title, columns and rows as they were."""
    _write(ctx, moved_sample())
    doc = _build(ctx)
    tables = _tables(doc, "uncovered")
    assert len(tables) == 2
    by_pair, by_port = tables
    assert by_pair.title == "Uncovered connections by app pair" and by_pair.rows[0][:3] == ("Web", "DB", 15)
    assert as_moved(by_port) == MOVED_PORT_GAPS
    assert "second table" in _section(doc, "uncovered").intro
    zh = _build(ctx, lang=Language.ZH_TW)
    assert _tables(zh, "uncovered")[1].title == "依 port／協定的未涵蓋連線" and "第二張表" in _section(zh, "uncovered").intro


def test_users_and_processes_are_not_this_reports_any_more(tmp_path):
    """Flows that name users and processes: no chapter here and no data note about them — the traffic report has
    both. The note on how much of the traffic carries a process, a user and byte counts went with them: it speaks
    of "rankings by these", and this report has none left."""
    named = configured_ctx(tmp_path / "named")
    _write(named, moved_sample())
    doc = _build(named)
    assert "users" not in {s.id for s in doc.sections}
    assert not [t for _, t in doc.tables() if t.title in ("Users by distinct destinations", "Processes by connections")]
    assert not [q for q in doc.data_quality if "carry a process" in q or "rankings by these" in q]
    none = configured_ctx(tmp_path / "none")  # no flow names either: the traffic report says so, this one does not
    _write(none, [flow(port=443)])
    assert not [q for q in _build(none).data_quality if "initiating user" in q or "initiating process" in q]


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
    enforced = next(r for r in parts.rows if r[0] == "Hosts in Full")
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
DECISIONS = ["Allowed (a rule allows it)", "Potentially Blocked", "Blocked"]


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
    assert ids[ids.index("monitor_only") - 1] == "pb" and ids[ids.index("monitor_only") + 1] == "findings"
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


# ── stage 3b: the maturity score and the enforced share are compared with the previous period ────────────────
# The inventory is today's. What it was on the previous period's last day is the daily snapshot of that day, which
# knows since migration 0018 which hosts were managed. The sample: on 2026-10-19, the last day before the period,
# three managed hosts (one Full) and an address without a VEN; today the second host is in Selective. Both periods
# hold 3 allowed and 1 potentially blocked connections.

PREVIOUS_DAY = "2026-10-19"
WEEK = END - START
# enforcement 1 of 3 hosts in Full, policy 3 of 4 connections, nothing on management ports or from unmanaged
# sources, no ransomware data: of the 90 points that have data
MATURITY_BEFORE = round(100 * (40 * (1 / 3) + 25 * 0.75 + 15 + 10) / 90)   # 63
MATURITY_NOW = round(100 * (40 * (1.5 / 3) + 25 * 0.75 + 15 + 10) / 90)    # 71: the second host counts half
NO_PREVIOUS_PARTS = ("The last day of the previous period has no snapshot of ransomware protection, so the two "
                     "scores rest on different parts and are not compared.")
# (severity, protection state) of the ransomware services in that day's snapshot: 1 of the 4 critical and high ones
# protected, where this period's analysis (_ransomware_result) has 1 of 2
RANSOMWARE_BEFORE = [("critical", "unprotected"), ("high", "unprotected"), ("high", "unprotected"),
                     ("critical", "protected_open"), ("low", "unprotected")]


def _hosts(ctx, hosts, *, snapshot=None):
    """hosts: (name, mode, managed). snapshot: the day this inventory is also the snapshot of."""
    with ctx.flows().connect() as conn:
        ls = labels.label_set_id(conn, (("app", "Web"), ("env", "Prod")))
        workloads.replace_inventory(conn, [workloads.WorkloadRow(
            href=f"/orgs/1/workloads/{name}", hostname=name, name=None, managed=managed, enforcement_mode=mode,
            visibility_level=None, os_id=None, ven_version=None, ven_href=None, label_set=ls, online=1,
            risk_exposure=None, risk_percent=None, risk_updated_at=None, fetched_at="x")
            for name, mode, managed in hosts])
        if snapshot:
            workloads.snapshot_day(conn, snapshot)
        conn.commit()


def _ransomware_snapshot(ctx, day, services, *, host="a1"):
    """services: (severity, protection state) of the host's ransomware services, as the PCE listed them; the store's
    ransomware services are then snapshotted as `day`'s (what the inventory run does once a day)."""
    with ctx.flows().connect() as conn:
        ransomware.upsert_services(conn, f"/orgs/1/workloads/{host}", [
            {"name": f"svc{i}", "port": 1000 + i, "proto": 6, "severity": severity, "protection_state": state,
             "port_status": "listening"} for i, (severity, state) in enumerate(services)],
            source_updated_at=None, at=NOW)
        ransomware.snapshot_day(conn, day)
        conn.commit()


def _earlier(f, by=WEEK):
    """The flow, seen `by` earlier: in the period before."""
    for name in ("first_detected", "last_detected"):
        object.__setattr__(f, name, getattr(f, name) - by)
    return f


def _two_periods(ctx, *, snapshot=PREVIOUS_DAY, previous_covered=True, previous=None, current=None):
    """The sample above. snapshot: the day the earlier inventory is the snapshot of (None: no snapshot);
    previous, current: the two periods' flows, when not the sample's."""
    from illumio_ops.domain.values import IngestSource
    from illumio_ops.store.flowdb import ingest_state
    _hosts(ctx, [("a1", "full", 1), ("a2", "visibility_only", 1), ("a3", "idle", 1), ("u1", "full", 0)],
           snapshot=snapshot)
    _hosts(ctx, [("a1", "full", 1), ("a2", "selective", 1), ("a3", "idle", 1), ("u1", "full", 0)])
    if previous is None:
        previous = [flow(port=443, conns=3), flow(port=8080, decision="potentially_blocked", conns=1)]
    if current is None:
        current = [flow(port=443, conns=3), flow(port=8080, decision="potentially_blocked", conns=1)]
    _write(ctx, [*current, *(_earlier(f) for f in previous)])
    with ctx.flows().connect() as conn:
        ingest_state.add_coverage(conn, IngestSource.TRAFFIC, START - WEEK if previous_covered else START, END)
        conn.commit()


def _compared(doc):
    kpi = {k.key: k for k in doc.kpis}
    return kpi["maturity"], kpi["enforced_hosts_pct"]


def test_both_numbers_are_compared_once_a_snapshot_knows_the_managed_hosts(ctx):
    _two_periods(ctx)
    maturity, enforced = _compared(_build(ctx))
    assert (maturity.value, maturity.previous) == (MATURITY_NOW, MATURITY_BEFORE) == (71, 63)
    # 1 of the 3 managed hosts in Full now (the one moved to Selective is not counted), 1 of 3 on the previous
    # period's last day; the address without a VEN is in neither
    assert (enforced.value, enforced.previous) == (33.3, 33.3)
    assert NO_PREVIOUS_PARTS not in maturity.note


def test_no_snapshot_on_the_previous_periods_last_day_is_no_comparison(ctx):
    _two_periods(ctx, snapshot="2026-10-18")  # the day before the one the report reads
    maturity, enforced = _compared(_build(ctx))
    assert (maturity.value, maturity.previous) == (MATURITY_NOW, None)
    assert (enforced.value, enforced.previous) == (33.3, None)
    assert NO_PREVIOUS_PARTS not in maturity.note  # the snapshot is what is missing: no word of ransomware


def test_a_snapshot_from_before_the_upgrade_is_no_comparison(ctx):
    """The first report after the upgrade: the snapshot of that day does not say which hosts were managed. One
    such row is enough — the hosts that do say would be another set than the day's (here 1 of 2 in Full: 50%)."""
    _two_periods(ctx)
    with ctx.flows().connect() as conn:
        conn.execute("UPDATE workload_snapshot_daily SET managed = NULL WHERE day = ? AND href LIKE '%/a3'",
                     (PREVIOUS_DAY,))
        assert conn.execute("SELECT COUNT(*), COUNT(managed) FROM workload_snapshot_daily").fetchone()[:] == (4, 3)
        conn.commit()
    maturity, enforced = _compared(_build(ctx))
    assert (maturity.previous, enforced.previous) == (None, None)


def test_a_filtered_report_does_not_compare_the_two(ctx):
    """A snapshot holds no labels: the hosts of a filtered report on that day cannot be told."""
    _two_periods(ctx)
    doc = _build(ctx, cond=FlowCondition(dst=EndpointFilter(labels=(LabelCond(key="app", values=("DB",)),))))
    maturity, enforced = _compared(doc)
    assert (maturity.previous, enforced.previous) == (None, None)
    # the numbers read from the flows are compared as before: both periods are filtered alike
    assert {k.key: k.previous for k in doc.kpis}["pb_flows"] == 1
    # ...and a ransomware snapshot of that day changes nothing: it holds no labels either
    _ransomware_snapshot(ctx, PREVIOUS_DAY, RANSOMWARE_BEFORE)
    _ransomware_result(ctx)
    maturity, enforced = _compared(_build(ctx, cond=FlowCondition(dst=EndpointFilter(labels=(LabelCond(
        key="app", values=("DB",)),)))))
    assert (maturity.previous, enforced.previous) == (None, None) and NO_PREVIOUS_PARTS not in maturity.note


def test_a_previous_period_not_wholly_collected_is_no_maturity_to_compare(ctx):
    """The score rests on the period's connections: without all of the previous period's there is none. The
    enforced share rests on the snapshot alone and is compared."""
    _two_periods(ctx, previous_covered=False)
    maturity, enforced = _compared(_build(ctx))
    assert (maturity.value, maturity.previous) == (MATURITY_NOW, None)
    assert (enforced.value, enforced.previous) == (33.3, 33.3)


def test_the_previous_score_has_its_ransomware_part_where_that_day_has_a_snapshot(ctx):
    """The store keeps a daily snapshot of the PCE's ransomware services. Where the previous period's last day has
    one, the previous score counts it as this period's score counts the analysis' result: both rest on all five
    parts and are compared. That day 1 of 4 critical and high services was protected (2.5 of the part's 10
    points), now 1 of 2 (5 of 10)."""
    _two_periods(ctx)
    _ransomware_snapshot(ctx, PREVIOUS_DAY, RANSOMWARE_BEFORE)
    _ransomware_result(ctx)
    maturity, enforced = _compared(_build(ctx))
    before = round(40 * (1 / 3) + 25 * 0.75 + 15 + 10 + 10 * 0.25)   # of the whole 100 points
    now = round(40 * (1.5 / 3) + 25 * 0.75 + 15 + 10 + 10 * 0.5)
    assert (maturity.value, maturity.previous) == (now, before) == (69, 60)
    assert NO_PREVIOUS_PARTS not in maturity.note
    assert (enforced.value, enforced.previous) == (33.3, 33.3)


def test_no_ransomware_snapshot_that_day_is_no_comparison_and_says_why(ctx):
    """This period's score has the ransomware part and the previous period's last day has no ransomware snapshot
    (the one of the day before is not that day's): the previous score would rest on four parts, this period's on
    five. Two scores on different parts are not subtracted, and the note says what is missing."""
    _two_periods(ctx)
    _ransomware_snapshot(ctx, "2026-10-18", RANSOMWARE_BEFORE)
    _ransomware_result(ctx)
    doc = _build(ctx)
    maturity, enforced = _compared(doc)
    assert (maturity.value, maturity.previous) == (69, None)
    assert maturity.note.endswith(NO_PREVIOUS_PARTS) and maturity.note.startswith("Grade ")
    assert (enforced.value, enforced.previous) == (33.3, 33.3)  # the share of hosts has both its values
    zh, _ = _compared(_build(ctx, lang=Language.ZH_TW))
    assert zh.note.endswith("上期那一天沒有勒索防護的快照，計分的部分不同，所以不比較。")


def test_a_ransomware_snapshot_with_nothing_rated_is_no_comparison_and_not_that_sentence(ctx):
    """That day has a ransomware snapshot, and none of its services is a critical or high one with a known state:
    the previous score has no ransomware part, so the two are not compared — but a snapshot is not what is
    missing, and the sentence that says so is not said."""
    _two_periods(ctx)
    _ransomware_snapshot(ctx, PREVIOUS_DAY, [("low", "unprotected"), ("critical", None)])
    _ransomware_result(ctx)
    maturity, enforced = _compared(_build(ctx))
    assert (maturity.value, maturity.previous) == (69, None) and NO_PREVIOUS_PARTS not in maturity.note
    assert enforced.previous == 33.3


def test_a_previous_ransomware_part_this_period_lacks_is_no_comparison(ctx):
    """The other way round: that day's snapshot gives the previous score a ransomware part, and this period has
    none (the analysis has no result yet). Different parts again: not compared, and no sentence about a snapshot."""
    _two_periods(ctx)
    _ransomware_snapshot(ctx, PREVIOUS_DAY, RANSOMWARE_BEFORE)
    maturity, _ = _compared(_build(ctx))
    assert (maturity.value, maturity.previous) == (MATURITY_NOW, None) and NO_PREVIOUS_PARTS not in maturity.note


def test_a_days_ransomware_snapshot_counts_the_services_the_analysis_counts(ctx):
    """One set of ransomware services, read both ways at one moment: the day's snapshot (what the previous score's
    ransomware part is worked out from) and the hourly analysis' result (this period's). Both count the critical
    and high services with a known state and, of them, the protected ones — also for spellings the PCE does not
    use, so the two readings cannot drift apart on a letter's case."""
    import json

    from illumio_ops.services.analysis.ransomware import ransomware_overlay
    from illumio_ops.services.reports.security_risk import _ransomware_counts
    day = "2026-10-27"
    _ransomware_snapshot(ctx, day, [("critical", "unprotected"), ("high", "Unprotected"), ("HIGH", "UNPROTECTED"),
                                    ("critical", "protected_open"), ("low", "unprotected"), ("critical", None)])
    _ransomware_snapshot(ctx, day, [("Critical", "Protected_Closed"), ("high", "pending"),
                                    ("medium", "protected_open")], host="a2")
    ransomware_overlay(ctx, NOW)
    with ctx.flows().connect() as conn:
        snapshot = ransomware.protected_by_day(conn, day, day).get(day)
        result = json.loads(analysis.read_result(conn, "ransomware")["result_json"])
    assert snapshot == _ransomware_counts(result, None) == (5, 2)


def test_the_ransomware_sentence_is_said_only_when_ransomware_is_what_sets_the_scores_apart(ctx):
    """With no snapshot of the hosts to compare with, a missing ransomware snapshot is not why: the sentence is not
    said (the first report after the upgrade must not blame ransomware for what the hosts' snapshot lacks)."""
    _two_periods(ctx, snapshot="2026-10-18")
    _ransomware_result(ctx)
    maturity, enforced = _compared(_build(ctx))
    assert (maturity.previous, enforced.previous) == (None, None) and maturity.value is not None
    assert NO_PREVIOUS_PARTS not in maturity.note


def test_a_previous_period_without_traffic_has_no_score_even_on_the_same_parts(tmp_path):
    """This period: flows, none with a decision — the score rests on the hosts alone. A previous period with no
    flow would rest on that same one part; but a period without traffic has no score (the rule this period's own
    number follows), so there is none to compare with. One with flows, none decided, has: 1 of 3 hosts in Full."""
    quiet = configured_ctx(tmp_path / "quiet")
    _two_periods(quiet, previous=[], current=[flow(port=443, decision="unknown", conns=5)])
    maturity, _ = _compared(_build(quiet))
    assert (maturity.value, maturity.previous) == (50, None)  # 1.5 of 3 hosts, the only part with data
    both = configured_ctx(tmp_path / "both")
    _two_periods(both, previous=[flow(port=22, decision="unknown", conns=2)],
                 current=[flow(port=443, decision="unknown", conns=5)])
    maturity, _ = _compared(_build(both))
    assert (maturity.value, maturity.previous) == (50, 33)


@pytest.mark.parametrize("previous", [
    [],                                                       # no traffic at all: no score to speak of
    [flow(port=443, decision="unknown", conns=5)],            # traffic, none with a decision: three parts fewer
], ids=["no_traffic", "no_decided_traffic"])
def test_a_previous_score_on_other_parts_is_not_compared(ctx, previous):
    _two_periods(ctx, previous=previous)
    maturity, enforced = _compared(_build(ctx))
    assert (maturity.value, maturity.previous) == (MATURITY_NOW, None)
    assert NO_PREVIOUS_PARTS not in maturity.note and enforced.previous == 33.3


@pytest.mark.parametrize(("days_after", "compared"), [(0, True), (1, True), (2, False), (3, False)])
def test_only_a_period_that_ends_today_or_yesterday_is_compared(ctx, days_after, compared):
    """This period's two numbers are read from the inventory as it is now: for a period that ended days ago they
    are not that period's. The period's end (exclusive, a midnight of the display zone) is today's date when the
    report covers up to yesterday — the scheduled case — and yesterday's when it covers up to the day before."""
    from datetime import timedelta
    _two_periods(ctx)
    doc = specs()[ReportType.SECURITY_RISK].build(BuildInput(
        ctx=ctx, params=ReportParams(report_type=ReportType.SECURITY_RISK), start=START, end=END, lang=Language.EN,
        tz=UTC, now=NOW + timedelta(days=days_after), pce_label="pce"))
    maturity, enforced = _compared(doc)
    assert (maturity.previous, enforced.previous) == ((MATURITY_BEFORE, 33.3) if compared else (None, None))


@pytest.mark.parametrize(("zone", "day"), [("Asia/Taipei", "2026-10-19"), ("America/New_York", "2026-10-20")])
def test_the_snapshot_read_is_the_utc_day_the_previous_period_ends_in(tmp_path, zone, day):
    """The daily snapshot's day is a UTC day (the collector's db_day), the report's period a span of the display
    zone's days: the snapshot read is the one of the UTC day that holds the previous period's last instant. East of
    UTC that is the day before the period's first; west of it, the period's first day itself."""
    from datetime import timedelta
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(zone)
    start, end = datetime(2026, 10, 20, tzinfo=tz), datetime(2026, 10, 27, tzinfo=tz)

    def build(c):
        return specs()[ReportType.SECURITY_RISK].build(BuildInput(
            ctx=c, params=ReportParams(report_type=ReportType.SECURITY_RISK), start=start, end=end, lang=Language.EN,
            tz=tz, now=end + timedelta(hours=1), pce_label="pce"))
    on_the_day = configured_ctx(tmp_path / "on")
    _two_periods(on_the_day, snapshot=day)
    assert _compared(build(on_the_day))[1].previous == 33.3
    beside = configured_ctx(tmp_path / "beside")
    _two_periods(beside, snapshot="2026-10-20" if day == "2026-10-19" else "2026-10-19")
    assert _compared(build(beside))[1].previous is None


def test_managed_means_the_same_in_the_snapshot_and_in_the_report(ctx):
    """One inventory, read both ways: the share in Full the report prints for this period equals the share a
    snapshot of the same inventory gives — the hosts counted are the same ones (a host with a VEN and no mode is
    one of them, an address without a VEN is not)."""
    hosts = [("a1", "full", 1), ("a2", "selective", 1), ("a3", "visibility_only", 1), ("a4", "idle", 1),
             ("a5", None, 1), ("u1", "full", 0), ("u2", "selective", 0)]
    _hosts(ctx, hosts, snapshot="2026-10-26")
    _write(ctx, [flow(port=443)])
    with ctx.flows().connect() as conn:
        counts = workloads.mode_counts_on(conn, "2026-10-26")
    _, enforced = _compared(_build(ctx))
    assert counts.hosts == 5
    assert enforced.value == round(100 * counts.modes["full"] / counts.hosts, 1) == 20.0  # in Full: 1 of the 5


# ── Selective is not Full (user 2026-11-14): the share is of hosts in Full; Selective is said beside it ──────

def test_the_share_of_hosts_is_of_those_in_full_and_selective_is_said_beside_it(ctx):
    """a1 Full, a2 Selective, a3 Idle: 1 of 3 in Full, and one more in Selective, which blocks only what a Deny Rule
    names. On the previous period's last day a2 was in Visibility Only: 1 of 3 in Full then too."""
    _two_periods(ctx)
    doc = _build(ctx)
    _, share = _compared(doc)
    assert (share.label, share.value, share.previous) == ("Managed hosts in Full enforcement", 33.3, 33.3)
    assert share.note == "1 more in Selective: it blocks only the connections a Deny Rule names."
    zh = {k.key: k for k in _build(ctx, lang=Language.ZH_TW).kpis}["enforced_hosts_pct"]
    assert (zh.label, zh.note) == ("Full 模式的受管主機", "另有 1 台是 Selective：只擋 Deny Rule 指定的連線。")
    from illumio_ops.i18n import translate
    assert "managed hosts in Full enforcement: {enforced_hosts_pct}" in translate(Language.EN, "rpt_conclusion_security_risk")
    assert "Full 模式的受管主機 {enforced_hosts_pct}" in translate(Language.ZH_TW, "rpt_conclusion_security_risk")
    # the table of modes by app: its last column is the share in Full, beside the count of each mode
    table = next(b for s in doc.sections if s.id == "enforcement" for b in s.blocks if hasattr(b, "columns"))
    assert [c.label for c in table.columns][-1] == "In Full" and table.rows[0][-1] == "33.3%"


def test_no_host_in_selective_says_nothing_beside_the_share(ctx):
    _hosts(ctx, [("a1", "full", 1), ("a2", "visibility_only", 1)])
    _write(ctx, [flow(port=443, conns=3)])
    _, share = _compared(_build(ctx))
    assert (share.value, share.note) == (50.0, None)


def test_every_host_in_selective_is_no_host_in_full(ctx):
    _hosts(ctx, [("a1", "selective", 1), ("a2", "selective", 1)])
    _write(ctx, [flow(port=443, conns=3)])
    _, share = _compared(_build(ctx))
    assert share.value == 0.0 and share.note.startswith("2 more in Selective")
