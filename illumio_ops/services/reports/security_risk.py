"""The security risk report (spec §6.5 報表, 5.x security_risk): how far segmentation has come and where the risk
is — the maturity score, policy coverage, traffic no rule covers and what to do about it, enforcement progress by
app, potentially blocked traffic with the rule it needs, ransomware and lateral-movement summaries, users and
processes, and every rule finding. Flow numbers are the flow store's primary rows under the report's filter."""
from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from typing import Any

from illumio_ops.domain.findings_rules import (
    BY_ID,
    CATEGORY_KEYS,
    SEVERITY_RANK,
    RuleOutcome,
)
from illumio_ops.domain.maturity import WEIGHTS as MATURITY_WEIGHTS
from illumio_ops.domain.maturity import (
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
from illumio_ops.services.flowsource import FlowTotals, field_coverage, flow_totals
from illumio_ops.services.reports import findings, flowsections, reads
from illumio_ops.services.reports.common import host_name, port_text, severity_name, tr
from illumio_ops.services.reports.flowsections import DECISION_KEYS
from illumio_ops.services.reports.generate import (
    coverage_note,
    previous_period,
    traffic_covered,
)
from illumio_ops.services.reports.registry import BuildInput
from illumio_ops.store.flowdb import analysis

TOP = 20
RANSOMWARE_TOP = 10
KEY_FINDINGS = 5
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
    "ransomware_protected_pct": "rpt_sec_kpi_ransomware_protected", "lateral_detections": "rpt_sec_kpi_detections",
}
_FLOW_KPIS = ("allowed_pct", "pb_flows", "blocked_flows", "unmanaged_connections", "admin_open_connections")


def _flow_kpis(t: FlowTotals) -> dict[str, float | int]:
    by = {d.decision: d for d in t.by_decision}
    allowed = by["allowed"].connections if "allowed" in by else 0
    return {"allowed_pct": round(100 * allowed / t.connections, 1) if t.connections else 0.0,
            "pb_flows": by["potentially_blocked"].flows if "potentially_blocked" in by else 0,
            "blocked_flows": by["blocked"].flows if "blocked" in by else 0,
            "unmanaged_connections": t.from_unmanaged_connections, "admin_open_connections": t.admin_open_connections}


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
    prev_start, _ = previous_period(inp.start, inp.end, inp.tz)
    before = (_flow_kpis(flow_totals(inp.ctx, spec.model_copy(update={"start": prev_start, "end": inp.start}),
                                     admin_ports=admin))
              if traffic_covered(inp.ctx, prev_start, inp.start, now=inp.now, flows=True) else None)
    no_flows = t("rpt_no_flows_filtered" if cond is not None else "rpt_no_flows")
    hosts = [h for h in lc.hosts.values() if flowsections.host_in_scope(h, cond)]
    modes = Counter(h.enforcement_mode for h in hosts)
    with reads.reading(inp.ctx) as conn:
        rw_row = analysis.read_result(conn, "ransomware")
        exposure_row = analysis.read_result(conn, "exposure")
        detections = analysis.detection_counts(conn, inp.start, inp.end)
    rw = json.loads(rw_row["result_json"]) if rw_row is not None else None
    rw_counts = _ransomware_counts(rw, {h.href for h in hosts if h.href} if cond is not None else None)
    by = {d.decision: d for d in totals.by_decision}
    allowed_connections = by["allowed"].connections if "allowed" in by else 0
    score = maturity(MaturityInputs(
        hosts_managed=len(hosts), hosts_full=modes["full"], hosts_selective=modes["selective"],
        connections=totals.connections, allowed_connections=allowed_connections,
        undecided_connections=by["unknown"].connections if "unknown" in by else 0,
        admin_open_connections=totals.admin_open_connections,
        unmanaged_source_connections=totals.from_unmanaged_connections,
        ransomware_services=rw_counts[0] if rw_counts else None,
        ransomware_protected=rw_counts[1] if rw_counts else None))
    outcomes = findings.run_rules(inp.ctx, spec, inp.ctx.settings.current().reports.rule_thresholds, lang,
                                  now=inp.now, scoped=cond is not None) if totals.flows else []
    fired = [o for o in outcomes if o.severity in (Severity.CRITICAL, Severity.HIGH)]

    # ── key metrics ─────────────────────────────────────────────────────────
    now_flow = _flow_kpis(totals)
    values: dict[str, float | int | None] = {
        # Without matching traffic the score would rest on the inventory alone: not shown (Review Focus 1).
        # whole points, as the explanation says them
        "maturity": round(score.score) if score.score is not None and totals.flows else None,
        "enforced_hosts_pct": round(100 * (modes["full"] + modes["selective"]) / len(hosts), 1) if hosts else None,
        **{k: (now_flow[k] if totals.flows else None) for k in _FLOW_KPIS},
        "critical_high_findings": len(fired) if totals.flows else None,
        "ransomware_protected_pct": round(100 * rw_counts[1] / rw_counts[0], 1) if rw_counts else None,
        "lateral_detections": sum(n for n, _ in detections.values()),
    }
    def maturity_note() -> str:
        worst = losing_most(score.parts)
        if worst is None:
            return t("rpt_sec_maturity_full", grade=score.grade)
        fixed = score_with(score.parts, worst)
        return t("rpt_sec_maturity_note", grade=score.grade, part=t(_PART_KEYS[worst]),
                 got=f"{MATURITY_WEIGHTS[worst] * (score.parts[worst] or 0):.0f}", weight=MATURITY_WEIGHTS[worst],
                 fixed=f"{fixed:.0f}" if fixed is not None else "—")
    notes: dict[str, str | None] = {k: (no_flows if values[k] is None else None) for k in _FLOW_KPIS}
    notes.update(
        maturity=(no_flows if not totals.flows else maturity_note() if score.grade else t("rpt_sec_maturity_none")),
        enforced_hosts_pct=None if hosts else t("rpt_sec_no_hosts"),
        critical_high_findings=None if totals.flows else no_flows,
        ransomware_protected_pct=None if rw_counts else t("rpt_sec_rw_no_data"),
        lateral_detections=t("rpt_sec_detections_all_hosts"))
    percent = {"enforced_hosts_pct", "allowed_pct", "ransomware_protected_pct"}
    higher = {"maturity", "enforced_hosts_pct", "allowed_pct", "ransomware_protected_pct"}
    kpis = tuple(Kpi(key=k, label=t(label), value=values[k],
                     previous=before[k] if before is not None and k in before else None,
                     unit="percent" if k in percent else "count", better="higher" if k in higher else "lower",
                     note=notes.get(k)) for k, label in _KPI_KEYS.items())

    # ── how the maturity score is worked out ────────────────────────────────
    def got(part: str) -> str:
        v = score.parts.get(part)
        if v is None or not totals.flows:
            return t("rpt_sec_part_no_data")
        return t("rpt_sec_part_got", got=f"{MATURITY_WEIGHTS[part] * v:.0f}", weight=MATURITY_WEIGHTS[part])
    parts_table = TableBlock(
        title=t("rpt_sec_tbl_parts"),
        columns=(Column(key="part", label=t("rpt_sec_col_part")), Column(key="measures", label=t("rpt_rdy_col_measures")),
                 Column(key="full", label=t("rpt_rdy_col_full_marks")), Column(key="points", label=t("rpt_rdy_col_points")),
                 Column(key="now", label=t("rpt_sec_col_this_period"))),
        rows=tuple((t(_PART_KEYS[k]), t(_PART_MEASURES[k]), t(_PART_FULL[k]), str(w), got(k))
                   for k, w in MATURITY_WEIGHTS.items()),
        total_rows=len(MATURITY_WEIGHTS), empty_text="")
    grades_table = TableBlock(
        title=t("rpt_rdy_tbl_grades"),
        columns=(Column(key="grade", label=t("rpt_rdy_col_grade")), Column(key="range", label=t("rpt_rdy_col_range")),
                 Column(key="means", label=t("rpt_rdy_col_means"))),
        rows=tuple((g, t(rng), t(means)) for g, (rng, means) in _GRADE_KEYS.items()),
        total_rows=len(_GRADE_KEYS), empty_text="")

    # ── coverage ────────────────────────────────────────────────────────────
    def pct(n: int, d: int) -> str:
        return f"{100 * n / d:.1f}%" if d else "—"
    coverage = TableBlock(
        title=t("rpt_sec_tbl_coverage"),
        columns=(Column(key="decision", label=t("rpt_col_decision")),
                 Column(key="flows", label=t("rpt_col_flows"), kind="number"),
                 Column(key="share", label=t("rpt_col_share_flows")),
                 Column(key="connections", label=t("rpt_col_connections"), kind="number")),
        rows=tuple((t(DECISION_KEYS.get(d.decision, "decision_unknown")), d.flows, pct(d.flows, totals.flows),
                    d.connections) for d in totals.by_decision),
        total_rows=len(totals.by_decision), empty_text=no_flows)
    into = sum(d.into_managed for d in totals.by_decision)
    out = sum(d.from_managed for d in totals.by_decision)
    direction = TextBlock(paragraphs=(t("rpt_sec_direction_coverage",
                                        inbound=pct(by["allowed"].into_managed if "allowed" in by else 0, into),
                                        outbound=pct(by["allowed"].from_managed if "allowed" in by else 0, out)),))

    # ── traffic no rule covers ──────────────────────────────────────────────
    def two_labels(title: str, decisions: tuple[PolicyDecision, ...], second: GroupBy,
                   second_label: str) -> TableBlock:
        return flowsections.ranking(
            inp, title=title, decisions=decisions, metric=SegmentMetric.CONNECTIONS, limit=TOP,
            group_by=(GroupBy(dimension=SegmentDimension.SRC_LABEL, label_key=APP), second),
            columns=(Column(key="src", label=t("rpt_col_src_label", key="app")),
                     Column(key="second", label=second_label),
                     Column(key="n", label=t("rpt_col_connections"), kind="number")))
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
                 *(Column(key=m, label=t(label), kind="number") for m, label in (
                     ("full", "rpt_col_mode_full"), ("selective", "rpt_col_mode_selective"),
                     ("visibility_only", "rpt_col_mode_visibility"), ("idle", "rpt_col_mode_idle"))),
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

    # ── ransomware ──────────────────────────────────────────────────────────
    rw_blocks: tuple[TableBlock | TextBlock, ...]
    if rw is None:
        rw_blocks = (TextBlock(paragraphs=(t("rpt_sec_rw_not_computed"),)),)
    elif rw.get("unsupported"):
        rw_blocks = (TextBlock(paragraphs=(t("rpt_sec_rw_unsupported"),)),)
    else:
        scope = {h.href for h in hosts if h.href} if cond is not None else None
        priority = [r for r in rw.get("priority") or () if scope is None or r.get("host") in scope]
        rw_blocks = (TableBlock(
            title=t("rpt_sec_tbl_ransomware"),
            columns=(Column(key="host", label=t("rpt_col_host")), Column(key="service", label=t("rpt_col_name")),
                     Column(key="port", label=t("rpt_col_service")),
                     Column(key="severity", label=t("rpt_col_severity")),
                     Column(key="sources", label=t("rpt_col_recent_sources"), kind="number")),
            rows=tuple((r.get("hostname") or host_name(lc.hosts, str(r.get("host")), lang), r.get("name"),
                        port_text(r.get("port"), int(r.get("proto") or 0)),
                        severity_name(lang, str(r.get("severity") or "").lower()), r.get("recent_sources"))
                       for r in priority[:RANSOMWARE_TOP]),
            total_rows=len(priority), empty_text=t("rpt_sec_rw_none"),
            limit_note=t("rpt_limit_top_n", n=RANSOMWARE_TOP) if len(priority) > RANSOMWARE_TOP else None),)
    rw_blocks = (*rw_blocks, TextBlock(paragraphs=(t("rpt_sec_rw_see"),)))

    # ── users and processes ─────────────────────────────────────────────────
    fc = field_coverage(inp.ctx, spec)

    def share(n: int) -> str:
        return f"{100 * n / fc.total:.1f}" if fc.total else "0.0"
    user_blocks: list[TableBlock | TextBlock] = [TextBlock(paragraphs=(t(
        "rpt_sec_users_intro", user=share(fc.initiator_user), process=share(fc.initiator_process)),))]
    if fc.initiator_user:
        user_blocks.append(flowsections.ranking(
            inp, title=t("rpt_sec_tbl_users"), metric=SegmentMetric.DISTINCT_DST, limit=TOP,
            group_by=(GroupBy(dimension=SegmentDimension.INITIATOR_USER),), skip_empty=True,
            columns=(Column(key="user", label=t("rpt_col_user")),
                     Column(key="n", label=t("rpt_col_distinct_destinations"), kind="number"))))
    else:
        user_blocks.append(TextBlock(paragraphs=(t("rpt_sec_no_users"),)))
    if fc.initiator_process:
        user_blocks.append(flowsections.ranking(
            inp, title=t("rpt_sec_tbl_processes"), metric=SegmentMetric.CONNECTIONS, limit=TOP,
            group_by=(GroupBy(dimension=SegmentDimension.INITIATOR_PROCESS),), skip_empty=True,
            columns=(Column(key="process", label=t("rpt_col_process")),
                     Column(key="n", label=t("rpt_col_connections"), kind="number"))))
    else:
        user_blocks.append(TextBlock(paragraphs=(t("rpt_sec_no_processes"),)))

    # ── lateral movement ────────────────────────────────────────────────────
    exposure = json.loads(exposure_row["result_json"]) if exposure_row is not None else None
    lateral_lines = [t("rpt_sec_lateral_detections", n=values["lateral_detections"],
                       high=sum(h for _, h in detections.values()))]
    if exposure is None:
        lateral_lines.append(t("rpt_lat_not_computed"))
    else:
        lateral_lines.append(t(
            "rpt_sec_lateral_exposure",
            assets=sum(1 for a in exposure.get("assets") or () if a.get("sources_now")),
            pivots=sum(1 for h in exposure.get("hosts") or () if h.get("pivot_now")),
            cross_env=exposure.get("cross_env_total") or 0))
    lateral_lines.append(t("rpt_sec_lateral_see", report=t("rpt_title_lateral_posture")))

    filter_line = flowsections.filter_text(cond, lang)
    quality = (*coverage_note(inp.ctx, inp.start, inp.end, lang, now=inp.now, tz=inp.tz, flows=True),
               *((t("rpt_quality_filter", filter=filter_line),) if filter_line else ()),
               t("rpt_trf_quality_counts"), *flowsections.coverage_lines(inp, fc))
    return ReportDocument(
        report_type=inp.params.report_type, lang=lang, title=t("rpt_title_security_risk"), period_start=inp.start,
        period_end=inp.end, generated_at=inp.now, pce_label=inp.pce_label, kpis=kpis,
        findings=findings.as_findings(fired, lang, limit=KEY_FINDINGS), data_quality=quality,
        sections=(
            Section(id="how", title=t("rpt_sec_sec_how"), intro=t("rpt_sec_how_intro"),
                    blocks=(parts_table, grades_table)),
            Section(id="coverage", title=t("rpt_sec_sec_coverage"), intro=t("rpt_sec_coverage_intro"),
                    blocks=(coverage, direction)),
            Section(id="uncovered", title=t("rpt_sec_sec_uncovered"), intro=t("rpt_sec_uncovered_intro"),
                    blocks=(uncovered,)),
            Section(id="ports", title=t("rpt_sec_sec_ports"), blocks=(port_gaps,)),
            Section(id="enforcement", title=t("rpt_sec_sec_enforcement"), intro=t("rpt_sec_enforcement_intro"),
                    blocks=(enforcement,)),
            Section(id="pb", title=t("rpt_sec_sec_pb"), intro=t("rpt_sec_pb_intro"), blocks=(pb,)),
            Section(id="ransomware", title=t("rpt_sec_sec_ransomware"), blocks=rw_blocks),
            Section(id="users", title=t("rpt_sec_sec_users"), blocks=tuple(user_blocks)),
            Section(id="lateral", title=t("rpt_sec_sec_lateral"), blocks=(TextBlock(paragraphs=tuple(lateral_lines)),)),
            Section(id="findings", title=t("rpt_trf_sec_findings"), intro=t("rpt_trf_findings_intro"),
                    blocks=(findings.outcomes_table(_by_category(outcomes), lang, title=t("rpt_sec_tbl_findings"),
                                                    evaluated=bool(totals.flows)),))))
