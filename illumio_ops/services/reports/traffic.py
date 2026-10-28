"""The traffic report (spec §6.5 報表, 5.x traffic): what moved in the period — flows and connections by decision,
the busiest apps, environments, services and host pairs, traffic touching unmanaged addresses, and the findings
of the rule engine. Every number is the flow store's primary rows under the report's filter; rankings are
analysis segments (the workbench's numbers)."""
from __future__ import annotations

from illumio_ops.domain.report import (
    Column,
    Kpi,
    ReportDocument,
    Section,
    TableBlock,
    TextBlock,
)
from illumio_ops.domain.segment import GroupBy
from illumio_ops.domain.values import SegmentDimension, SegmentMetric
from illumio_ops.services.analysis.context import load_lateral_context
from illumio_ops.services.flowsource import FlowTotals, field_coverage, flow_totals
from illumio_ops.services.reports import findings, flowsections
from illumio_ops.services.reports.common import tr
from illumio_ops.services.reports.flowsections import DECISION_KEYS
from illumio_ops.services.reports.generate import (
    coverage_note,
    previous_period,
    traffic_covered,
)
from illumio_ops.services.reports.registry import BuildInput

TOP = 20
KEY_FINDINGS = 5
_KPI_KEYS = {"flows": "rpt_trf_kpi_flows", "connections": "rpt_trf_kpi_connections",
             "sources": "rpt_trf_kpi_sources", "destinations": "rpt_trf_kpi_destinations"}


def _kpi_values(t: FlowTotals) -> dict[str, int]:
    return {"flows": t.flows, "connections": t.connections, "sources": t.sources, "destinations": t.destinations}


def build_traffic(inp: BuildInput) -> ReportDocument:
    lang = inp.lang

    def t(msg: str, /, **params: object) -> str:
        return tr(lang, msg, **params)

    lc = load_lateral_context(inp.ctx, now=inp.now)
    env_key = lc.settings.environment_label_key
    spec = flowsections.window(inp)
    totals = flow_totals(inp.ctx, spec)
    prev_start, _ = previous_period(inp.start, inp.end, inp.tz)
    prev_known = traffic_covered(inp.ctx, prev_start, inp.start, now=inp.now, flows=True)
    before = (_kpi_values(flow_totals(inp.ctx, flowsections.window(inp).model_copy(
        update={"start": prev_start, "end": inp.start}))) if prev_known else None)
    no_flows = t("rpt_no_flows_filtered" if inp.params.filter is not None else "rpt_no_flows")
    now_v = _kpi_values(totals)
    kpis = tuple(Kpi(key=k, label=t(label), value=now_v[k] if totals.flows else None,
                     previous=before[k] if before is not None else None,
                     note=None if totals.flows else no_flows) for k, label in _KPI_KEYS.items())

    def pct(n: int, d: int) -> str:
        return f"{100 * n / d:.1f}%" if d else "—"
    decisions = TableBlock(
        title=t("rpt_trf_tbl_decisions"),
        columns=(Column(key="decision", label=t("rpt_col_decision")),
                 Column(key="flows", label=t("rpt_col_flows"), kind="number"),
                 Column(key="connections", label=t("rpt_col_connections"), kind="number"),
                 Column(key="into_managed", label=t("rpt_col_into_managed"), kind="number"),
                 Column(key="into_managed_pct", label=t("rpt_col_into_managed_pct"))),
        rows=tuple((t(DECISION_KEYS.get(d.decision, "decision_unknown")), d.flows, d.connections, d.into_managed,
                    pct(d.into_managed, d.flows)) for d in totals.by_decision),
        total_rows=len(totals.by_decision), empty_text=no_flows)

    def ranking(title: str, dim: SegmentDimension, label: str, *, label_key: str | None = None) -> TableBlock:
        return flowsections.ranking(
            inp, title=title, group_by=(GroupBy(dimension=dim, label_key=label_key),),
            metric=SegmentMetric.CONNECTIONS, limit=TOP,
            columns=(Column(key="key", label=label), Column(key="n", label=t("rpt_col_connections"), kind="number")))
    labels = tuple(ranking(t(title, key=k), dim, t(col, key=k), label_key=k) for title, col, dim, k in (
        ("rpt_trf_tbl_src_label", "rpt_col_src_label", SegmentDimension.SRC_LABEL, "app"),
        ("rpt_trf_tbl_dst_label", "rpt_col_dst_label", SegmentDimension.DST_LABEL, "app"),
        ("rpt_trf_tbl_src_label", "rpt_col_src_label", SegmentDimension.SRC_LABEL, env_key),
        ("rpt_trf_tbl_dst_label", "rpt_col_dst_label", SegmentDimension.DST_LABEL, env_key)))
    services = ranking(t("rpt_trf_tbl_services"), SegmentDimension.SERVICE, t("rpt_col_service"))

    fc = field_coverage(inp.ctx, spec)
    bytes_intro = t("rpt_trf_bytes_intro", pct=f"{100 * fc.bytes / fc.total:.1f}" if fc.total else "0.0")
    bytes_blocks: tuple[TableBlock | TextBlock, ...]
    if fc.bytes:
        bytes_blocks = (flowsections.ranking(
            inp, title=t("rpt_trf_tbl_bytes"), metric=SegmentMetric.BYTES, limit=TOP,
            group_by=(GroupBy(dimension=SegmentDimension.SRC_HOST), GroupBy(dimension=SegmentDimension.DST_HOST)),
            columns=(Column(key="src", label=t("rpt_col_source")), Column(key="dst", label=t("rpt_col_destination")),
                     Column(key="bytes", label=t("rpt_col_bytes"), kind="number"))),)
    else:
        bytes_blocks = (TextBlock(paragraphs=(t("rpt_trf_no_bytes") if totals.flows else no_flows,)),)

    unmanaged = TextBlock(paragraphs=(t("rpt_trf_unmanaged", from_n=f"{totals.from_unmanaged:,}",
                                        to_n=f"{totals.to_unmanaged:,}", total=f"{totals.flows:,}"),
                                      t("rpt_trf_unmanaged_see")))

    outcomes = findings.run_rules(inp.ctx, spec, inp.ctx.settings.current().reports.rule_thresholds, lang,
                                  now=inp.now, scoped=inp.params.filter is not None) if totals.flows else []
    filter_line = flowsections.filter_text(inp.params.filter, lang)
    quality = (*coverage_note(inp.ctx, inp.start, inp.end, lang, now=inp.now, tz=inp.tz, flows=True),
               *((t("rpt_quality_filter", filter=filter_line),) if filter_line else ()),
               t("rpt_trf_quality_counts"), *flowsections.coverage_lines(inp, fc))
    return ReportDocument(
        report_type=inp.params.report_type, lang=lang, title=t("rpt_title_traffic"), period_start=inp.start,
        period_end=inp.end, generated_at=inp.now, pce_label=inp.pce_label, kpis=kpis,
        findings=findings.as_findings(outcomes, lang, limit=KEY_FINDINGS), data_quality=quality,
        sections=(Section(id="decisions", title=t("rpt_trf_sec_decisions"), intro=t("rpt_trf_decisions_intro"),
                          blocks=(decisions,)),
                  Section(id="labels", title=t("rpt_trf_sec_labels"), blocks=labels),
                  Section(id="services", title=t("rpt_trf_sec_services"), blocks=(services,)),
                  Section(id="bytes", title=t("rpt_trf_sec_bytes"), intro=bytes_intro, blocks=bytes_blocks),
                  Section(id="unmanaged", title=t("rpt_trf_sec_unmanaged"), blocks=(unmanaged,)),
                  Section(id="findings", title=t("rpt_trf_sec_findings"), intro=t("rpt_trf_findings_intro"),
                          blocks=(findings.outcomes_table(outcomes, lang, title=t("rpt_trf_tbl_findings"),
                                                    evaluated=bool(totals.flows)),))))
