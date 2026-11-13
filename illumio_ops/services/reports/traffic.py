"""The traffic report (spec §6.5 報表, 5.x traffic): what moved in the period — flows and connections by decision,
the busiest apps, environments, services and host pairs, traffic touching unmanaged addresses, and the findings
of the rule engine. Every number is the flow store's primary rows under the report's filter; rankings are
analysis segments (the workbench's numbers)."""
from __future__ import annotations

from collections.abc import Callable

from illumio_ops.domain.report import (
    BarBlock,
    Cell,
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
from illumio_ops.services.flowsource import (
    FlowTotals,
    VolumeRow,
    connections_by_day,
    field_coverage,
    flow_totals,
    traffic_volume,
)
from illumio_ops.services.reports import findings, flowsections
from illumio_ops.services.reports.common import DECISION_KEYS, PROTOCOLS, port_text, tr
from illumio_ops.services.reports.generate import (
    coverage_text,
    previous_period,
    traffic_covered,
)
from illumio_ops.services.reports.registry import BuildInput

TOP = 20
APP = "app"
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
    # The three decisions and their shares of the decided flows. The flows the PCE gave no decision for are no row:
    # the sentence under the table says how many there are and which chapter lists them. (The numbers above the
    # table, and the day chart, are what was seen: every flow.)
    decided = totals.decided() if totals.decided_flows else []
    decisions = TableBlock(
        title=t("rpt_trf_tbl_decisions"),
        columns=(Column(key="decision", label=t("rpt_col_decision")),
                 Column(key="flows", label=t("rpt_col_flows"), kind="number"),
                 Column(key="share", label=t("rpt_col_share_flows")),
                 Column(key="connections", label=t("rpt_col_connections"), kind="number"),
                 Column(key="into_managed", label=t("rpt_col_into_managed"), kind="number"),
                 Column(key="into_managed_pct", label=t("rpt_col_into_managed_pct"))),
        rows=tuple((t(DECISION_KEYS[d.decision]), d.flows, pct(d.flows, totals.decided_flows), d.connections,
                    d.into_managed, pct(d.into_managed, d.flows)) for d in decided),
        total_rows=len(decided), empty_text=t("rpt_no_decided_flows") if totals.flows else no_flows)
    decision_blocks: tuple[TableBlock | TextBlock | BarBlock, ...] = (
        decisions, *flowsections.decided_note(lang, totals.undecided))
    by_day = connections_by_day(inp.ctx, spec) if totals.flows else {}
    if len(by_day) > 1:  # a period seen on one day only has no trend to draw
        decision_blocks += (BarBlock(title=t("rpt_trf_bar_daily"), points=tuple((d[5:], n) for d, n in by_day.items()),
                                     empty_text=no_flows),)

    def ranking(title: str, dim: SegmentDimension, label: str, *, label_key: str | None = None) -> TableBlock:
        return flowsections.ranking(
            inp, title=title, group_by=(GroupBy(dimension=dim, label_key=label_key),),
            metric=SegmentMetric.CONNECTIONS, limit=TOP,
            columns=(Column(key="key", label=label), Column(key="n", label=t("rpt_col_connections"), kind="number")))

    def link(*dims: SegmentDimension, metric: SegmentMetric = SegmentMetric.CONNECTIONS,
             label_key: str | None = None) -> str | None:
        """The section's first ranking, opened in the workbench (the segment ranking() runs)."""
        return flowsections.link(inp, metric=metric, limit=TOP, group_by=tuple(
            GroupBy(dimension=d, label_key=label_key if d in (SegmentDimension.SRC_LABEL, SegmentDimension.DST_LABEL)
                    else None) for d in dims))
    labels = tuple(ranking(t(title, key=k), dim, t(col, key=k), label_key=k) for title, col, dim, k in (
        ("rpt_trf_tbl_src_label", "rpt_col_src_label", SegmentDimension.SRC_LABEL, "app"),
        ("rpt_trf_tbl_dst_label", "rpt_col_dst_label", SegmentDimension.DST_LABEL, "app"),
        ("rpt_trf_tbl_src_label", "rpt_col_src_label", SegmentDimension.SRC_LABEL, env_key),
        ("rpt_trf_tbl_dst_label", "rpt_col_dst_label", SegmentDimension.DST_LABEL, env_key)))
    services = ranking(t("rpt_trf_tbl_services"), SegmentDimension.SERVICE, t("rpt_col_service"))
    vol = traffic_volume(inp.ctx, spec, top=TOP, app_key=APP)
    protocols = TableBlock(
        title=t("rpt_trf_tbl_protocols"),
        columns=(Column(key="proto", label=t("rpt_col_protocol")), Column(key="flows", label=t("rpt_col_flows"), kind="number"),
                 Column(key="connections", label=t("rpt_col_connections"), kind="number"),
                 Column(key="share", label=t("rpt_col_share_connections"))),
        rows=tuple((PROTOCOLS.get(p.proto) or t("rpt_trf_proto_n", n=p.proto), p.flows, p.connections,
                    pct(p.connections, totals.connections)) for p in vol.by_proto),
        total_rows=len(vol.by_proto), empty_text=no_flows)

    def volume_table(title: str, rows: list[VolumeRow], total: int, last: Column, value: Callable[[VolumeRow], Cell],
                     empty: str) -> TableBlock:
        return TableBlock(
            title=title,
            columns=(Column(key="src", label=t("rpt_col_source")), Column(key="dst", label=t("rpt_col_destination")),
                     Column(key="service", label=t("rpt_col_service")),
                     Column(key="bytes", label=t("rpt_col_bytes"), kind="number"),
                     Column(key="connections", label=t("rpt_col_connections"), kind="number"), last),
            rows=tuple((r.src, r.dst, port_text(r.port, r.proto), r.bytes, r.connections, value(r)) for r in rows),
            total_rows=total, empty_text=empty,
            limit_note=t("rpt_limit_top_n", n=TOP) if total > len(rows) else None)

    fc = field_coverage(inp.ctx, spec)
    bytes_intro = t("rpt_trf_bytes_intro", pct=f"{100 * fc.bytes / fc.total:.1f}" if fc.total else "0.0")
    bytes_blocks: tuple[TableBlock | TextBlock, ...]
    if fc.bytes:
        bytes_blocks = (flowsections.ranking(
            inp, title=t("rpt_trf_tbl_bytes"), metric=SegmentMetric.BYTES, limit=TOP,
            group_by=(GroupBy(dimension=SegmentDimension.SRC_HOST), GroupBy(dimension=SegmentDimension.DST_HOST)),
            columns=(Column(key="src", label=t("rpt_col_source")), Column(key="dst", label=t("rpt_col_destination")),
                     Column(key="bytes", label=t("rpt_col_bytes"), kind="number"))),
            TableBlock(
                title=t("rpt_trf_tbl_app_bytes"),
                columns=(Column(key="src_app", label=t("rpt_col_src_label", key=APP)),
                         Column(key="dst_app", label=t("rpt_col_dst_label", key=APP)),
                         Column(key="bytes", label=t("rpt_col_bytes"), kind="number")),
                rows=tuple((a or t("rpt_no_label"), d or t("rpt_no_label"), n) for a, d, n in vol.by_app),
                total_rows=vol.app_pairs, empty_text=t("rpt_trf_no_bytes"),
                limit_note=t("rpt_limit_top_n", n=TOP) if vol.app_pairs > TOP else None),
            TextBlock(paragraphs=(t("rpt_trf_rate_note", rated=f"{vol.with_rate:,}", total=f"{vol.with_bytes:,}",
                                    max=f"{vol.max_mbps:.3f}") if vol.max_mbps is not None
                                  else t("rpt_trf_rate_none", total=f"{vol.with_bytes:,}"),)),
            volume_table(t("rpt_trf_tbl_rate"), vol.by_rate, vol.with_rate,
                         Column(key="mbps", label=t("rpt_col_mbps")), lambda r: f"{r.mbps or 0:.3f}",
                         t("rpt_trf_no_rate")),
            volume_table(t("rpt_trf_tbl_per_conn"), vol.by_per_conn, vol.multi_conn,
                         Column(key="per_conn", label=t("rpt_col_bytes_per_conn"), kind="number"),
                         lambda r: r.bytes // max(r.connections, 1), t("rpt_trf_no_multi_conn")))
    else:
        bytes_blocks = (TextBlock(paragraphs=(t("rpt_trf_no_bytes") if totals.flows else no_flows,)),)

    unmanaged = TextBlock(paragraphs=(t("rpt_trf_unmanaged", from_n=f"{totals.from_unmanaged:,}",
                                        to_n=f"{totals.to_unmanaged:,}", total=f"{totals.flows:,}"),
                                      t("rpt_trf_unmanaged_see")))

    outcomes = findings.run_rules(inp.ctx, spec, inp.ctx.settings.current().reports.rule_thresholds, lang,
                                  now=inp.now, scoped=inp.params.filter is not None) if totals.flows else []
    filter_line = flowsections.filter_text(inp.params.filter, lang)
    cov = coverage_text(inp.ctx, inp.start, inp.end, lang, now=inp.now, tz=inp.tz, flows=True)
    quality = (*cov.lines,
               *((t("rpt_quality_filter", filter=filter_line),) if filter_line else ()),
               t("rpt_trf_quality_counts"), *flowsections.coverage_lines(inp, fc))
    return ReportDocument(
        report_type=inp.params.report_type, lang=lang, title=t("rpt_title_traffic"), period_start=inp.start,
        period_end=inp.end, generated_at=inp.now, pce_label=inp.pce_label, kpis=kpis,
        findings=findings.as_findings(outcomes, lang), caveats=cov.caveats,
        data_quality=(*quality, *flowsections.no_links_note(inp)),
        sections=(Section(id="decisions", title=t("rpt_trf_sec_decisions"), intro=t("rpt_trf_decisions_intro"),
                          blocks=decision_blocks),
                  Section(id="labels", title=t("rpt_trf_sec_labels"), blocks=labels,
                          workbench_link=link(SegmentDimension.SRC_LABEL, label_key=APP)),
                  Section(id="services", title=t("rpt_trf_sec_services"), blocks=(services, protocols),
                          workbench_link=link(SegmentDimension.SERVICE)),
                  Section(id="bytes", title=t("rpt_trf_sec_bytes"), intro=bytes_intro, blocks=bytes_blocks,
                          workbench_link=link(SegmentDimension.SRC_HOST, SegmentDimension.DST_HOST,
                                              metric=SegmentMetric.BYTES) if fc.bytes else None),
                  Section(id="unmanaged", title=t("rpt_trf_sec_unmanaged"), blocks=(unmanaged,)),
                  *findings.unevaluated_section(outcomes, lang,
                                                title=t("rpt_rules_sec_unevaluated"), intro=t("rpt_trf_findings_intro"),
                                                table_title=t("rpt_rules_tbl_unevaluated"), evaluated=bool(totals.flows))))
