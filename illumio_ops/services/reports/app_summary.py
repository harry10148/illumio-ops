"""The app summary report (spec §6.5 報表, 5.x app_summary): one application, named by the report filter's app
label (and environment, when given), matched exactly. Its traffic is split once: inbound (into the app from
elsewhere), outbound (from the app to elsewhere) and intra-app — 5.x listed intra-app traffic on both sides. Then
its policy impact, its hosts, its uncovered traffic and the rule findings over its flows only."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from illumio_ops.domain.filter import (
    EndpointFilter,
    FilterSpec,
    FlowCondition,
)
from illumio_ops.domain.report import (
    Column,
    Kpi,
    ReportDocument,
    Section,
    TableBlock,
    TextBlock,
)
from illumio_ops.domain.segment import GroupBy
from illumio_ops.domain.values import PolicyDecision, SegmentDimension, SegmentMetric
from illumio_ops.services.analysis.context import load_lateral_context
from illumio_ops.services.flowsource import FlowTotals, flow_totals
from illumio_ops.services.reports import findings, flowsections
from illumio_ops.services.reports.common import tr
from illumio_ops.services.reports.flowsections import DECISION_KEYS
from illumio_ops.services.reports.generate import (
    coverage_note,
    previous_period,
    traffic_covered,
)
from illumio_ops.services.reports.registry import BuildInput

TOP = 30
UNCOVERED_TOP = 10
KEY_FINDINGS = 5
APP = "app"
UNCOVERED = (PolicyDecision.POTENTIALLY_BLOCKED, PolicyDecision.BLOCKED)


def app_endpoint(cond: FlowCondition | None) -> EndpointFilter:
    """The app's end as the filter names it: every label condition on the side that names an app (the app,
    and an environment, role or other label that narrows it). registry.app_filter_ok has refused the rest."""
    for side in (cond.dst, cond.src) if cond is not None else ():
        if side is not None and any(lc.key == APP for lc in side.labels):
            return EndpointFilter(labels=side.labels)
    return EndpointFilter()


def _sides(inp: BuildInput, ep: EndpointFilter, start: datetime | None = None,
           end: datetime | None = None) -> dict[str, FilterSpec]:
    base = (inp.params.filter or FlowCondition()).model_copy(
        update={"src": None, "dst": None, "src_exclude": None, "dst_exclude": None})
    first, last = start or inp.start, end or inp.end

    def spec(**sides: EndpointFilter) -> FilterSpec:
        fields: dict[str, Any] = {**dict(base), **sides}
        return FilterSpec(start=first, end=last, **fields)
    return {"inbound": spec(dst=ep, src_exclude=ep), "outbound": spec(src=ep, dst_exclude=ep),
            "intra": spec(src=ep, dst=ep), "touching_dst": spec(dst=ep), "touching_src": spec(src=ep)}


def _sum(parts: list[FlowTotals]) -> dict[str, tuple[int, int]]:
    """decision -> (flows, connections) over disjoint parts."""
    out: dict[str, tuple[int, int]] = {}
    for t in parts:
        for d in t.by_decision:
            f, c = out.get(d.decision, (0, 0))
            out[d.decision] = (f + d.flows, c + d.connections)
    return out


def build_app_summary(inp: BuildInput) -> ReportDocument:
    lang = inp.lang

    def t(msg: str, /, **params: object) -> str:
        return tr(lang, msg, **params)

    lc = load_lateral_context(inp.ctx, now=inp.now)
    env_key = lc.settings.environment_label_key
    ep = app_endpoint(inp.params.filter)
    conds = {c.key: " / ".join(c.values) for c in ep.labels}
    app_name = conds.get(APP, "")
    title = t("rpt_app_title_env", app=app_name, env=conds[env_key]) if env_key in conds else \
        t("rpt_app_title", app=app_name)
    sides = _sides(inp, ep)
    parts = {k: flow_totals(inp.ctx, sides[k]) for k in ("inbound", "outbound", "intra")}
    decisions = _sum(list(parts.values()))
    flows = sum(f for f, _ in decisions.values())
    connections = sum(c for _, c in decisions.values())
    no_flows = t("rpt_no_flows_filtered")

    prev_start, _ = previous_period(inp.start, inp.end, inp.tz)
    before: dict[str, float | int] | None = None
    if traffic_covered(inp.ctx, prev_start, inp.start, now=inp.now, flows=True):
        prev = _sides(inp, ep, prev_start, inp.start)
        prev_parts = {k: flow_totals(inp.ctx, prev[k]) for k in ("inbound", "outbound", "intra")}
        before = _kpi_values(prev_parts, _sum(list(prev_parts.values())))
    now_v = _kpi_values(parts, decisions)

    # ── hosts ───────────────────────────────────────────────────────────────
    hosts = sorted((h for h in lc.hosts.values() if h.managed and ep.labels
                    and all(h.labels.get(c.key) in c.values for c in ep.labels)),
                   key=lambda h: h.hostname or h.key)
    modes = Counter(h.enforcement_mode for h in hosts)
    host_table = TableBlock(
        title=t("rpt_app_tbl_hosts"),
        columns=(Column(key="host", label=t("rpt_col_host")), Column(key="env", label=env_key),
                 Column(key="mode", label=t("rpt_col_enforcement_mode"))),
        rows=tuple((h.hostname or h.key, h.labels.get(env_key) or t("rpt_no_label"), h.enforcement_mode or "—")
                   for h in hosts),
        total_rows=len(hosts), empty_text=t("rpt_app_no_hosts"))

    kpis = (
        *(Kpi(key=k, label=t(label), value=now_v[k] if flows else None,
              previous=before[k] if before is not None else None, note=None if flows else no_flows,
              unit="percent" if k == "allowed_pct" else "count",
              better="higher" if k == "allowed_pct" else "lower" if k == "pb_flows" else "neutral")
          for k, label in (("inbound_connections", "rpt_app_kpi_inbound"), ("outbound_connections", "rpt_app_kpi_outbound"),
                           ("intra_connections", "rpt_app_kpi_intra"), ("allowed_pct", "rpt_sec_kpi_allowed_pct"),
                           ("pb_flows", "rpt_sec_kpi_pb_flows"))),
        Kpi(key="hosts", label=t("rpt_app_kpi_hosts"), value=len(hosts), previous=None),
        Kpi(key="enforced_hosts_pct", label=t("rpt_sec_kpi_enforced_hosts"), unit="percent", better="higher",
            value=round(100 * (modes["full"] + modes["selective"]) / len(hosts), 1) if hosts else None, previous=None,
            note=None if hosts else t("rpt_app_no_hosts")),
    )

    def peer_ranking(title_key: str, side: str, dim: SegmentDimension, *, uncovered: bool = False,
                     limit: int = TOP) -> TableBlock:
        return flowsections.ranking(
            inp, title=t(title_key), spec=sides[side], decisions=UNCOVERED if uncovered else (),
            metric=SegmentMetric.CONNECTIONS, limit=limit,
            group_by=(GroupBy(dimension=dim, label_key=APP), GroupBy(dimension=SegmentDimension.SERVICE)),
            columns=(Column(key="peer", label=t("rpt_col_peer_app")), Column(key="service", label=t("rpt_col_service")),
                     Column(key="n", label=t("rpt_col_connections"), kind="number")))
    intra = flowsections.ranking(
        inp, title=t("rpt_app_tbl_intra"), spec=sides["intra"], metric=SegmentMetric.CONNECTIONS, limit=TOP,
        group_by=(GroupBy(dimension=SegmentDimension.SERVICE),),
        columns=(Column(key="service", label=t("rpt_col_service")),
                 Column(key="n", label=t("rpt_col_connections"), kind="number")))

    def pct(n: int, d: int) -> str:
        return f"{100 * n / d:.1f}%" if d else "—"
    order = sorted(decisions, key=lambda d: -decisions[d][0])
    impact = TableBlock(
        title=t("rpt_app_tbl_impact"),
        columns=(Column(key="decision", label=t("rpt_col_decision")),
                 Column(key="flows", label=t("rpt_col_flows"), kind="number"),
                 Column(key="connections", label=t("rpt_col_connections"), kind="number"),
                 Column(key="share", label=t("rpt_col_share_flows"))),
        rows=tuple((t(DECISION_KEYS.get(d, "decision_unknown")), decisions[d][0], decisions[d][1],
                    pct(decisions[d][0], flows)) for d in order),
        total_rows=len(order), empty_text=no_flows)
    impact_text = TextBlock(paragraphs=(t(
        "rpt_app_impact_text", allowed=pct(decisions.get("allowed", (0, 0))[1], connections),
        pb=f"{decisions.get('potentially_blocked', (0, 0))[0]:,}"),))

    outcomes = findings.run_rules(inp.ctx, [sides["touching_dst"], sides["touching_src"]],
                                  inp.ctx.settings.current().reports.rule_thresholds, lang,
                                  now=inp.now, scoped=True) if flows else []
    filter_line = flowsections.filter_text(inp.params.filter, lang)
    quality = (*coverage_note(inp.ctx, inp.start, inp.end, lang, now=inp.now, tz=inp.tz, flows=True),
               *((t("rpt_quality_filter", filter=filter_line),) if filter_line else ()),
               t("rpt_app_quality_split"), t("rpt_trf_quality_counts"))
    return ReportDocument(
        report_type=inp.params.report_type, lang=lang, title=title, period_start=inp.start, period_end=inp.end,
        generated_at=inp.now, pce_label=inp.pce_label, kpis=kpis,
        findings=findings.as_findings(outcomes, lang, limit=KEY_FINDINGS), data_quality=quality,
        sections=(
            Section(id="inbound", title=t("rpt_app_sec_inbound"), intro=t("rpt_app_inbound_intro"),
                    blocks=(peer_ranking("rpt_app_tbl_inbound", "inbound", SegmentDimension.SRC_LABEL),)),
            Section(id="outbound", title=t("rpt_app_sec_outbound"), intro=t("rpt_app_outbound_intro"),
                    blocks=(peer_ranking("rpt_app_tbl_outbound", "outbound", SegmentDimension.DST_LABEL),)),
            Section(id="intra", title=t("rpt_app_sec_intra"), blocks=(intra,)),
            Section(id="impact", title=t("rpt_app_sec_impact"), blocks=(impact, impact_text)),
            Section(id="hosts", title=t("rpt_app_sec_hosts"), intro=t("rpt_app_hosts_intro"), blocks=(host_table,)),
            Section(id="uncovered", title=t("rpt_sec_sec_uncovered"), blocks=(
                peer_ranking("rpt_app_tbl_uncovered_in", "inbound", SegmentDimension.SRC_LABEL, uncovered=True,
                             limit=UNCOVERED_TOP),
                peer_ranking("rpt_app_tbl_uncovered_out", "outbound", SegmentDimension.DST_LABEL, uncovered=True,
                             limit=UNCOVERED_TOP))),
            Section(id="findings", title=t("rpt_trf_sec_findings"), intro=t("rpt_app_findings_intro"),
                    blocks=(findings.outcomes_table(outcomes, lang, title=t("rpt_trf_tbl_findings"),
                                                    evaluated=bool(flows)),))))


def _kpi_values(parts: dict[str, FlowTotals], decisions: dict[str, tuple[int, int]]) -> dict[str, float | int]:
    connections = sum(c for _, c in decisions.values())
    return {"inbound_connections": parts["inbound"].connections, "outbound_connections": parts["outbound"].connections,
            "intra_connections": parts["intra"].connections,
            "allowed_pct": round(100 * decisions.get("allowed", (0, 0))[1] / connections, 1) if connections else 0.0,
            "pb_flows": decisions.get("potentially_blocked", (0, 0))[0]}
