"""The security risk report (spec §6.5 報表, 5.x security_risk): how far segmentation has come and where the risk
is — the maturity score, policy coverage, traffic no rule covers (by app pair and by port) and what to do about it,
enforcement progress by app, potentially blocked traffic with the rule it needs, and every rule finding. Flow
numbers are the flow store's primary rows under the report's filter.
What other reports hold is named, not repeated (UI redesign spec §9.2): ransomware protection is one number whose
note names the ransomware report, lateral movement one sentence that names the lateral posture report, and users
and processes are a chapter of the traffic report (flowsections.users_section).
The maturity score and the enforced share of hosts are today's inventory; their previous-period values come from the
daily snapshots of the previous period's last day (the hosts' modes, the ransomware services), when that day can be
compared with (see build_security_risk)."""
from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from datetime import timedelta
from typing import Any

from illumio_ops.domain.findings_rules import (
    BY_ID,
    CATEGORY_KEYS,
    SEVERITY_RANK,
    RuleOutcome,
)
from illumio_ops.domain.maturity import WEIGHTS as MATURITY_WEIGHTS
from illumio_ops.domain.maturity import (
    Maturity,
    MaturityInputs,
    losing_most,
    maturity,
    score_with,
)
from illumio_ops.domain.ransomware import service_coverage
from illumio_ops.domain.report import (
    Column,
    Kpi,
    ReportDocument,
    Section,
    TableBlock,
    TextBlock,
)
from illumio_ops.domain.segment import GroupBy
from illumio_ops.domain.values import (
    PolicyDecision,
    PortClass,
    SegmentDimension,
    SegmentMetric,
    Severity,
)
from illumio_ops.services.analysis.context import load_lateral_context
from illumio_ops.services.flowsource import FlowTotals, flow_totals
from illumio_ops.services.reports import findings, flowsections, reads
from illumio_ops.services.reports.common import DECISION_KEYS, MODE_KEYS, tr
from illumio_ops.services.reports.generate import (
    caveats_in_order,
    coverage_text,
    previous_period,
    traffic_covered,
)
from illumio_ops.services.reports.hints import hint
from illumio_ops.services.reports.registry import BuildInput
from illumio_ops.store.flowdb import analysis, ransomware, workloads
from illumio_ops.store.flowdb.db import db_day

TOP = 20
APP = "app"  # the app label key
UNCOVERED = (PolicyDecision.POTENTIALLY_BLOCKED, PolicyDecision.BLOCKED)
PB_ONLY = (PolicyDecision.POTENTIALLY_BLOCKED,)
MODES = ("full", "selective", "visibility_only", "idle")
_CATEGORY_ORDER = {c: i for i, c in enumerate(CATEGORY_KEYS)}
_PART_KEYS = {"enforcement": "rpt_sec_part_enforcement", "policy": "rpt_sec_part_policy",
              "lateral": "rpt_sec_part_lateral", "managed": "rpt_sec_part_managed",
              "ransomware": "rpt_sec_part_ransomware"}
_PART_MEASURES = {"enforcement": "rpt_sec_measures_enforcement", "policy": "rpt_sec_measures_policy",
                  "lateral": "rpt_sec_measures_lateral", "managed": "rpt_sec_measures_managed",
                  "ransomware": "rpt_sec_measures_ransomware"}
_PART_FULL = {"enforcement": "rpt_sec_full_enforcement", "policy": "rpt_sec_full_policy",
              "lateral": "rpt_sec_full_lateral", "managed": "rpt_sec_full_managed",
              "ransomware": "rpt_sec_full_ransomware"}
# grade -> (score range, what it means for segmentation)
_GRADE_KEYS = {"A": ("rpt_rdy_range_a", "rpt_sec_means_a"), "B": ("rpt_rdy_range_b", "rpt_sec_means_b"),
               "C": ("rpt_rdy_range_c", "rpt_sec_means_c"), "D": ("rpt_rdy_range_d", "rpt_sec_means_d"),
               "F": ("rpt_rdy_range_f", "rpt_sec_means_f")}
_KPI_KEYS = {
    "maturity": "rpt_sec_kpi_maturity", "enforced_hosts_pct": "rpt_sec_kpi_enforced_hosts",
    "allowed_pct": "rpt_sec_kpi_allowed_pct", "pb_flows": "rpt_sec_kpi_pb_flows",
    "blocked_flows": "rpt_sec_kpi_blocked_flows", "unmanaged_connections": "rpt_sec_kpi_unmanaged_connections",
    "admin_open_connections": "rpt_sec_kpi_admin_open", "critical_high_findings": "rpt_sec_kpi_critical_high",
    "ransomware_protected_pct": "rpt_sec_kpi_ransomware_protected",
}
_FLOW_KPIS = ("allowed_pct", "pb_flows", "blocked_flows", "unmanaged_connections", "admin_open_connections")


def _flow_kpis(t: FlowTotals) -> dict[str, float | int | None]:
    """The numbers read from the period's flows. Every one counts the flows the PCE gave a decision for; the share
    is None when there is none (a share of nothing is not 0%)."""
    by = {d.decision: d for d in t.by_decision}
    allowed = by["allowed"].connections if "allowed" in by else 0
    return {"allowed_pct": round(100 * allowed / t.decided_connections, 1) if t.decided_connections else None,
            "pb_flows": by["potentially_blocked"].flows if "potentially_blocked" in by else 0,
            "blocked_flows": by["blocked"].flows if "blocked" in by else 0,
            "unmanaged_connections": t.from_unmanaged_connections, "admin_open_connections": t.admin_open_connections}


def _score(*, hosts: int, full: int, selective: int, flows: FlowTotals, rw: tuple[int, int] | None) -> Maturity:
    """The maturity score of a set of managed hosts (how many, and of them in Full and in Selective), a period's
    connections and the ransomware services counted (_ransomware_counts)."""
    by = {d.decision: d for d in flows.by_decision}
    return maturity(MaturityInputs(
        hosts_managed=hosts, hosts_full=full, hosts_selective=selective, connections=flows.connections,
        allowed_connections=by["allowed"].connections if "allowed" in by else 0,
        undecided_connections=flows.connections - flows.decided_connections,
        admin_open_connections=flows.admin_open_connections,
        unmanaged_source_connections=flows.from_unmanaged_connections,
        ransomware_services=rw[0] if rw else None, ransomware_protected=rw[1] if rw else None))


def _scored(score: Maturity) -> frozenset[str]:
    """The parts a score rests on: the ones that have data."""
    return frozenset(part for part, value in score.parts.items() if value is not None)


def _enforced_pct(full: int, selective: int, hosts: int) -> float | None:
    """Of the managed hosts, the share in Full or Selective; None without a host."""
    return round(100 * (full + selective) / hosts, 1) if hosts else None


def _ransomware_counts(result: Mapping[str, Any] | None, hrefs: set[str] | None) -> tuple[int, int] | None:
    """(critical/high services the PCE rated, of them protected); None without ransomware data."""
    if not result or result.get("unsupported"):
        return None
    known = [service_coverage(s.get("protection_state")) for h in result.get("hosts") or ()
             if hrefs is None or h.get("href") in hrefs for s in h.get("services") or ()
             if str(s.get("severity") or "").lower() in ("critical", "high")]
    rated = [c for c in known if c is not None]  # an unknown protection state is neither protected nor not
    if not rated:
        return None
    return len(rated), sum(1 for c in rated if c == 1.0)


def _by_category(outcomes: list[RuleOutcome]) -> list[RuleOutcome]:
    return sorted(outcomes, key=lambda o: (_CATEGORY_ORDER[BY_ID[o.rule_id].category],
                                           SEVERITY_RANK[o.severity] if o.severity else 9, o.rule_id))


def build_security_risk(inp: BuildInput) -> ReportDocument:
    lang = inp.lang

    def t(msg: str, /, **params: object) -> str:
        return tr(lang, msg, **params)

    lc = load_lateral_context(inp.ctx, now=inp.now)
    # Remote-execution ports, any protocol where configured so (the rule engine's management ports)
    admin = {(e.port, e.proto) for e in lc.admin_ports.entries if e.category is PortClass.REMOTE}
    cond = inp.params.filter
    spec = flowsections.window(inp)
    totals = flow_totals(inp.ctx, spec, admin_ports=admin)
    saw = flowsections.seen(totals)
    prev_start, _ = previous_period(inp.start, inp.end, inp.tz)
    prev_totals = (flow_totals(inp.ctx, spec.model_copy(update={"start": prev_start, "end": inp.start}),
                               admin_ports=admin)
                   if traffic_covered(inp.ctx, prev_start, inp.start, now=inp.now, flows=True) else None)
    before = _flow_kpis(prev_totals) if prev_totals is not None else None
    no_flows = t("rpt_no_flows_filtered" if cond is not None else "rpt_no_flows")
    scope_groups = flowsections.label_groups_of(inp.ctx, cond)
    hosts = [h for h in lc.hosts.values() if flowsections.host_in_scope(h, cond, label_groups=scope_groups)]
    modes = Counter(h.enforcement_mode for h in hosts)
    # The hosts' numbers (the enforced share, and through it the score) are read from the inventory as it is now.
    # What they were is the daily snapshot of the previous period's last day, and it is read only when it speaks of
    # the same thing: the period ends now — its end, a midnight of the display zone, is today's or yesterday's (the
    # hosts of a period that ended earlier are not today's inventory) — and the report has no filter (a snapshot
    # holds no labels to tell a filtered report's hosts by).
    ends_now = (inp.now.astimezone(inp.tz).date() - inp.end.astimezone(inp.tz).date()).days <= 1
    # a snapshot's day is the collector's, a UTC day: the one that holds the previous period's last instant
    day_before = db_day(inp.start - timedelta(microseconds=1))
    hosts_before: workloads.ModeCounts | None = None
    rw_before: tuple[int, int] | None = None
    rw_snapshot_before = False
    with reads.reading(inp.ctx) as conn:
        rw_row = analysis.read_result(conn, "ransomware")
        if cond is None and ends_now:
            hosts_before = workloads.mode_counts_on(conn, day_before)
            # That day's ransomware services, counted as _ransomware_counts counts this period's (one definition:
            # ransomware.protected_by_day). Nothing when the day has no ransomware snapshot, and also when its
            # snapshot holds no critical or high service with a known state: snapshot_taken tells which.
            rw_before = ransomware.protected_by_day(conn, day_before, day_before).get(day_before)
            rw_snapshot_before = ransomware.snapshot_taken(conn, day_before)
    rw = json.loads(rw_row["result_json"]) if rw_row is not None else None
    rw_counts = _ransomware_counts(rw, {h.href for h in hosts if h.href} if cond is not None else None)
    by = {d.decision: d for d in totals.by_decision}
    score = _score(hosts=len(hosts), full=modes["full"], selective=modes["selective"], flows=totals, rw=rw_counts)
    # The previous period's score, worked out the same way from that day's hosts, that period's connections (all of
    # them collected, and at least one flow: a score on the inventory alone is not shown for this period either)
    # and that day's ransomware services. This period's ransomware part is the hourly analysis' stored result, of
    # which only the latest is kept; the previous one is the daily snapshot of the same services
    # (ransomware_snapshot_daily), counted by the same definition. A part without data is left out and the others
    # scaled up: two scores are compared only when they rest on the same parts, never across two scales.
    score_before = (_score(hosts=hosts_before.hosts, full=hosts_before.modes.get("full", 0),
                           selective=hosts_before.modes.get("selective", 0), flows=prev_totals, rw=rw_before)
                    if hosts_before is not None and prev_totals is not None and prev_totals.flows else None)
    parts, parts_before = _scored(score), _scored(score_before) if score_before is not None else None
    same_parts = parts_before == parts
    # This period's score has the ransomware part, the previous one lacks it because that day has no ransomware
    # snapshot, and nothing else sets the two apart: the number's note says why there is no change to read. (A day
    # whose snapshot holds nothing to rate leaves the previous score without the part too, and the two are not
    # compared either — but a snapshot is not what is missing there, and the note does not say it is.)
    no_ransomware_snapshot = (parts_before is not None and not rw_snapshot_before
                              and parts == parts_before | {"ransomware"})
    outcomes = findings.run_rules(inp.ctx, spec, inp.ctx.settings.current().reports.rule_thresholds, lang,
                                  now=inp.now, scoped=cond is not None) if totals.flows else []
    fired = [o for o in outcomes if o.severity in (Severity.CRITICAL, Severity.HIGH)]

    # ── key metrics ─────────────────────────────────────────────────────────
    now_flow = _flow_kpis(totals)
    values: dict[str, float | int | None] = {
        # Without matching traffic the score would rest on the inventory alone: not shown (Review Focus 1).
        # whole points, as the explanation says them
        "maturity": round(score.score) if score.score is not None and totals.flows else None,
        "enforced_hosts_pct": _enforced_pct(modes["full"], modes["selective"], len(hosts)),
        **{k: (now_flow[k] if totals.flows else None) for k in _FLOW_KPIS},
        "critical_high_findings": len(fired) if totals.flows else None,
        "ransomware_protected_pct": round(100 * rw_counts[1] / rw_counts[0], 1) if rw_counts else None,
    }
    def maturity_note() -> str:
        worst = losing_most(score.parts)
        if worst is None:
            return t("rpt_sec_maturity_full", grade=score.grade)
        fixed = score_with(score.parts, worst)
        return t("rpt_sec_maturity_note", grade=score.grade, part=t(_PART_KEYS[worst]),
                 got=f"{MATURITY_WEIGHTS[worst] * (score.parts[worst] or 0):.0f}", weight=MATURITY_WEIGHTS[worst],
                 fixed=f"{fixed:.0f}" if fixed is not None else "—")
    # Why a number is not there: no traffic at all, or traffic of which none carries a decision.
    no_decided = t("rpt_no_decided_flows")
    notes: dict[str, str | None] = {k: (None if values[k] is not None else no_decided if totals.flows else no_flows)
                                    for k in _FLOW_KPIS}
    if totals.undecided.flows:  # these two count decided connections: say where the others are
        notes.update(dict.fromkeys(("unmanaged_connections", "admin_open_connections"), t("rpt_kpi_decided_only")))
    maturity_said = no_flows if not totals.flows else maturity_note() if score.grade else t("rpt_sec_maturity_none")
    if no_ransomware_snapshot and totals.flows:
        maturity_said = " ".join((maturity_said, t("rpt_sec_no_previous_parts")))
    notes.update(
        maturity=maturity_said,
        enforced_hosts_pct=None if hosts else t("rpt_sec_no_hosts"),
        critical_high_findings=None if totals.flows else no_flows,
        # the one number this report keeps of ransomware protection: where each host and service is listed
        ransomware_protected_pct=t("rpt_sec_see_ransomware", report=t("rpt_title_ransomware")))
    percent = {"enforced_hosts_pct", "allowed_pct", "ransomware_protected_pct"}
    higher = {"maturity", "enforced_hosts_pct", "allowed_pct", "ransomware_protected_pct"}
    previous: dict[str, float | int | None] = dict(before or {})
    if hosts_before is not None:
        previous["enforced_hosts_pct"] = _enforced_pct(hosts_before.modes.get("full", 0),
                                                       hosts_before.modes.get("selective", 0), hosts_before.hosts)
    if same_parts and score_before is not None and score_before.score is not None and values["maturity"] is not None:
        previous["maturity"] = round(score_before.score)
    kpis = tuple(Kpi(key=k, label=t(label), value=values[k], previous=previous.get(k),
                     unit="percent" if k in percent else "count", better="higher" if k in higher else "lower",
                     note=notes.get(k)) for k, label in _KPI_KEYS.items()
                 # a number another analysis has not produced is left out; the data notes say why (6.6.0)
                 if not (k == "ransomware_protected_pct" and values[k] is None))

    # ── how the maturity score is worked out ────────────────────────────────
    def got(part: str) -> str:
        v = score.parts.get(part)
        if v is None or not totals.flows:
            return t("rpt_sec_part_no_data")
        return t("rpt_sec_part_got", got=f"{MATURITY_WEIGHTS[part] * v:.0f}", weight=MATURITY_WEIGHTS[part])
    def reached(part: str) -> str:
        """The part's share of its full marks (drawn as a bar); a dash without data."""
        v = score.parts.get(part)
        return "—" if v is None or not totals.flows else f"{100 * v:.1f}%"
    parts_table = TableBlock(
        title=t("rpt_sec_tbl_parts"),
        columns=(Column(key="part", label=t("rpt_sec_col_part")), Column(key="measures", label=t("rpt_rdy_col_measures")),
                 Column(key="full", label=t("rpt_rdy_col_full_marks")), Column(key="points", label=t("rpt_rdy_col_points")),
                 Column(key="now", label=t("rpt_sec_col_this_period")),
                 Column(key="share", label=t("rpt_sec_col_part_share"))),
        rows=tuple((t(_PART_KEYS[k]), t(_PART_MEASURES[k]), t(_PART_FULL[k]), str(w), got(k), reached(k))
                   for k, w in MATURITY_WEIGHTS.items()),
        total_rows=len(MATURITY_WEIGHTS), empty_text="")
    parts_rule = TextBlock(paragraphs=(t("rpt_sec_how_decided"),))
    grades_table = TableBlock(
        title=t("rpt_rdy_tbl_grades"),
        columns=(Column(key="grade", label=t("rpt_rdy_col_grade")), Column(key="range", label=t("rpt_rdy_col_range")),
                 Column(key="means", label=t("rpt_rdy_col_means"))),
        rows=tuple((g, t(rng), t(means)) for g, (rng, means) in _GRADE_KEYS.items()),
        total_rows=len(_GRADE_KEYS), empty_text="")

    # ── coverage ────────────────────────────────────────────────────────────
    def pct(n: int, d: int) -> str:
        return f"{100 * n / d:.1f}%" if d else "—"
    # The three decisions and their shares of the decided flows; the flows without a decision are no row here: a
    # sentence under the table says how many there are and which chapter lists them.
    decided = totals.decided() if totals.decided_flows else []
    coverage = TableBlock(
        title=t("rpt_sec_tbl_coverage"),
        columns=(Column(key="decision", label=t("rpt_col_decision")),
                 Column(key="flows", label=t("rpt_col_flows"), kind="number"),
                 Column(key="share", label=t("rpt_col_share_flows")),
                 Column(key="connections", label=t("rpt_col_connections"), kind="number")),
        rows=tuple((t(DECISION_KEYS[d.decision]), d.flows, pct(d.flows, totals.decided_flows), d.connections)
                   for d in decided),
        total_rows=len(decided), empty_text=no_decided if totals.flows else no_flows)
    # Lateral movement has its own report: one sentence here names it. It stands with a chapter that has something
    # to show; in a period without traffic the chapter stays what it was, a table with no rows (finish folds it).
    see_lateral = TextBlock(paragraphs=(t("rpt_sec_see_lateral", report=t("rpt_title_lateral_posture")),))
    coverage_blocks: tuple[TableBlock | TextBlock, ...] = (*((see_lateral,) if totals.flows else ()), coverage)
    if decided:  # both shares are of decided flows; without one there is no share to say
        into = sum(d.into_managed for d in decided)
        out = sum(d.from_managed for d in decided)
        coverage_blocks += (TextBlock(paragraphs=(t(
            "rpt_sec_direction_coverage", inbound=pct(by["allowed"].into_managed if "allowed" in by else 0, into),
            outbound=pct(by["allowed"].from_managed if "allowed" in by else 0, out)),)),)
    coverage_blocks += flowsections.decided_note(lang, totals.undecided)

    # ── traffic no rule covers ──────────────────────────────────────────────
    def two_labels(title: str, decisions: tuple[PolicyDecision, ...], second: GroupBy,
                   second_label: str) -> TableBlock:
        return flowsections.ranking(
            inp, title=title, decisions=decisions, metric=SegmentMetric.CONNECTIONS, limit=TOP,
            group_by=(GroupBy(dimension=SegmentDimension.SRC_LABEL, label_key=APP), second),
            columns=(Column(key="src", label=t("rpt_col_src_label", key="app")),
                     Column(key="second", label=second_label),
                     Column(key="n", label=t("rpt_col_connections"), kind="number")))

    def link(decisions: tuple[PolicyDecision, ...], *group_by: GroupBy,
             metric: SegmentMetric = SegmentMetric.CONNECTIONS) -> str | None:
        """A section's ranking opened in the workbench: the segment flowsections.ranking runs for it."""
        return flowsections.link(inp, decisions=decisions, metric=metric, limit=TOP, group_by=group_by)
    by_app_src = GroupBy(dimension=SegmentDimension.SRC_LABEL, label_key=APP)
    by_app_dst = GroupBy(dimension=SegmentDimension.DST_LABEL, label_key=APP)
    by_service = GroupBy(dimension=SegmentDimension.SERVICE)
    no_label = t("rpt_no_label")
    uncovered_base = two_labels(t("rpt_sec_tbl_uncovered"), UNCOVERED,
                                GroupBy(dimension=SegmentDimension.DST_LABEL, label_key=APP),
                                t("rpt_col_dst_label", key="app"))

    def advice(src: Any, dst: Any) -> str:
        if src == no_label:
            return t("rpt_sec_advice_unlabeled")
        return t("rpt_sec_advice_same_app") if src == dst else t("rpt_sec_advice_cross_app")
    uncovered = uncovered_base.model_copy(update={
        "columns": (*uncovered_base.columns, Column(key="advice", label=t("rpt_col_action"))),
        "rows": tuple((*r, advice(r[0], r[1])) for r in uncovered_base.rows)})
    port_gaps = flowsections.ranking(
        inp, title=t("rpt_sec_tbl_port_gaps"), decisions=UNCOVERED, metric=SegmentMetric.CONNECTIONS, limit=TOP,
        group_by=(GroupBy(dimension=SegmentDimension.SERVICE),),
        columns=(Column(key="service", label=t("rpt_col_service")),
                 Column(key="n", label=t("rpt_col_connections"), kind="number")))

    # ── enforcement progress ────────────────────────────────────────────────
    env_key = lc.settings.environment_label_key
    groups: dict[str, Counter[str | None]] = {}
    for h in hosts:
        name = f"{h.labels.get('app') or no_label} ({h.labels.get(env_key) or no_label})"
        groups.setdefault(name, Counter())[h.enforcement_mode] += 1
    ordered = sorted(groups.items(), key=lambda kv: (-sum(kv[1].values()), kv[0]))
    enforcement = TableBlock(
        title=t("rpt_sec_tbl_enforcement"),
        columns=(Column(key="app", label=t("rpt_col_app_env")),
                 Column(key="hosts", label=t("rpt_col_managed_hosts"), kind="number"),
                 *(Column(key=m, label=t(MODE_KEYS[m]), kind="number") for m in MODES),
                 Column(key="enforced", label=t("rpt_col_enforced_pct"))),
        rows=tuple((name, sum(c.values()), *(c[m] for m in MODES), pct(c["full"] + c["selective"], sum(c.values())))
                   for name, c in ordered),
        total_rows=len(ordered), empty_text=t("rpt_sec_no_hosts"))

    # ── potentially blocked ─────────────────────────────────────────────────
    pb_base = flowsections.ranking(
        inp, title=t("rpt_sec_tbl_pb"), decisions=PB_ONLY, metric=SegmentMetric.CONNECTIONS, limit=TOP,
        group_by=(GroupBy(dimension=SegmentDimension.DST_LABEL, label_key=APP),
                  GroupBy(dimension=SegmentDimension.SERVICE)),
        columns=(Column(key="dst", label=t("rpt_col_dst_label", key="app")),
                 Column(key="service", label=t("rpt_col_service")),
                 Column(key="n", label=t("rpt_col_connections"), kind="number")))
    pb = pb_base.model_copy(update={
        "columns": (*pb_base.columns, Column(key="rule", label=t("rpt_col_suggested_rule"))),
        "rows": tuple((*r, t("rpt_sec_pb_rule", app=r[0], service=r[1]) if r[0] != no_label
                       else t("rpt_sec_pb_rule_unlabeled", service=r[1])) for r in pb_base.rows)})

    # ── what is not there ───────────────────────────────────────────────────
    # The ransomware number rests on another analysis: it is left out until that analysis has a result, and one
    # data note says why (hints.py). The ransomware report holds the hosts and services.
    missing: tuple[str, ...] = ()
    if rw is None:
        missing = (hint(lang, "rpt_hint_pending_sec_rw"),)
    elif rw.get("unsupported"):
        missing = (hint(lang, "rpt_hint_unsupported_sec_rw"),)

    filter_line = flowsections.filter_text(cond, lang)
    cov = coverage_text(inp.ctx, inp.start, inp.end, lang, now=inp.now, tz=inp.tz, flows=True)
    # No note on how much of the traffic carries a process, a user or byte counts (flowsections.coverage_lines): it
    # is about rankings by those fields, and the ones this report had are the traffic report's now.
    quality = (*cov.lines,
               *((t("rpt_quality_filter", filter=filter_line),) if filter_line else ()),
               t("rpt_trf_quality_counts"))
    return ReportDocument(
        report_type=inp.params.report_type, lang=lang, title=t("rpt_title_security_risk"), period_start=inp.start,
        period_end=inp.end, generated_at=inp.now, pce_label=inp.pce_label, kpis=kpis,
        findings=findings.as_findings(outcomes, lang),
        caveats=caveats_in_order(gaps=cov.caveats, undecided=flowsections.undecided_caveat(lang, saw)),
        data_quality=(*quality, *missing, *flowsections.no_links_note(inp)),
        sections=(
            Section(id="how", title=t("rpt_sec_sec_how"), intro=t("rpt_sec_how_intro"),
                    blocks=(parts_table, parts_rule, grades_table)),
            Section(id="coverage", title=t("rpt_sec_sec_coverage"), intro=t("rpt_sec_coverage_intro"),
                    blocks=coverage_blocks),
            # by app pair, then the same connections by port (its own chapter, "Ports with gaps", until 6.10.0);
            # the chapter opens its first ranking in the workbench
            Section(id="uncovered", title=t("rpt_sec_sec_uncovered"), intro=t("rpt_sec_uncovered_intro"),
                    blocks=(uncovered, port_gaps), workbench_link=link(UNCOVERED, by_app_src, by_app_dst)),
            Section(id="enforcement", title=t("rpt_sec_sec_enforcement"), intro=t("rpt_sec_enforcement_intro"),
                    blocks=(enforcement,)),
            Section(id="pb", title=t("rpt_sec_sec_pb"), intro=t("rpt_sec_pb_intro"), blocks=(pb,),
                    workbench_link=link(PB_ONLY, by_app_dst, by_service)),
            *flowsections.monitor_only_section(inp, spec, saw, hosts=lc.hosts),
            *findings.unevaluated_section(_by_category(outcomes), lang,
                                          title=t("rpt_rules_sec_unevaluated"), intro=t("rpt_trf_findings_intro"),
                                          table_title=t("rpt_rules_tbl_unevaluated"), evaluated=bool(totals.flows))))
