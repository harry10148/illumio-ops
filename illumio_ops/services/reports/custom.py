"""A custom report (spec §6.5.5, P6e): its sections, each an analysis segment saved from the workbench, run on the
report's period through run_segment — the same number the workbench shows — as a table, with a link to open the
section in the workbench when the GUI's external address is set and the period is one the workbench takes."""
from __future__ import annotations

import dataclasses
from urllib.parse import urlencode

from illumio_ops.domain.filter import FlowCondition
from illumio_ops.domain.report import (
    Cell,
    Column,
    ReportDocument,
    Section,
    TableBlock,
    TextBlock,
)
from illumio_ops.domain.segment import EventSegment, FlowSegment
from illumio_ops.domain.values import (
    ReportType,
    SegmentDimension,
    SegmentMetric,
    SegmentView,
)
from illumio_ops.services import custom_reports
from illumio_ops.services.analysis.segments import run_segment
from illumio_ops.services.coverage import Coverage
from illumio_ops.services.custom_reports import CustomSection
from illumio_ops.services.eventsource import EventRow
from illumio_ops.services.flowsource import FlowRow, field_coverage
from illumio_ops.services.reports import flowsections
from illumio_ops.services.reports.common import port_text, tr
from illumio_ops.services.reports.flowsections import DECISION_KEYS
from illumio_ops.services.reports.generate import coverage_note
from illumio_ops.services.reports.registry import BuildInput, ReportFailed
from illumio_ops.services.reports.render_html import fmt_time

DIM_KEYS = {d: f"wb_dim_{d.value}" for d in SegmentDimension}
METRIC_KEYS = {"flows": "wb_metric_flows", "connections": "wb_metric_connections", "distinct_dst": "wb_metric_distinct_dst",
               "distinct_src": "wb_metric_distinct_src", "distinct_ports": "wb_metric_distinct_ports",
               "bytes": "wb_metric_bytes", "events": "wb_metric_events"}


def _link(inp: BuildInput, sec: CustomSection) -> str | None:
    base = inp.ctx.settings.current().reports.gui_external_url
    req = sec.segment.request(inp.start, inp.end)
    if not base or req is None:
        return None
    return f"{base.rstrip('/')}/investigate?{urlencode({'q': req.model_dump_json(exclude_none=True)})}"


def _gaps(inp: BuildInput, cov: Coverage | None) -> tuple[TextBlock, ...]:
    """Where this section's data has holes (not collected, failed, cut): said beside the table, never an empty
    table that reads as "nothing happened"."""
    if cov is None or not (cov.gaps or cov.truncated):
        return ()
    lines = [tr(inp.lang, "rpt_cust_gaps", n=len(cov.gaps), start=fmt_time(cov.gaps[0][0].isoformat(), inp.tz),
                end=fmt_time(cov.gaps[0][1].isoformat(), inp.tz))] if cov.gaps else []
    if cov.truncated:
        lines.append(tr(inp.lang, "rpt_cust_truncated"))
    return (TextBlock(paragraphs=tuple(lines)),)


def _flow_detail(inp: BuildInput, seg: FlowSegment, title: str) -> tuple[TableBlock, Coverage]:
    def t(k: str) -> str:
        return tr(inp.lang, k)
    result = run_segment(inp.ctx, seg, now=inp.now)
    rows: tuple[tuple[Cell, ...], ...] = tuple(
        (r.last_detected.isoformat(), r.src_hostname or r.src_ip, r.dst_hostname or r.dst_ip, port_text(r.port, r.proto),
         t(DECISION_KEYS.get(r.policy_decision, "decision_unknown")), r.num_connections)
        for r in result.detail or [] if isinstance(r, FlowRow))
    return TableBlock(
        title=title, columns=(Column(key="last", label=t("evidence_col_last"), kind="time"),
                              Column(key="src", label=t("evidence_col_src")), Column(key="dst", label=t("evidence_col_dst")),
                              Column(key="port", label=t("evidence_col_port")),
                              Column(key="decision", label=t("evidence_col_decision")),
                              Column(key="connections", label=t("evidence_col_connections"), kind="number")),
        rows=rows, total_rows=len(rows), empty_text=t("rpt_no_flows_filtered"),
        limit_note=tr(inp.lang, "rpt_limit_top_n", n=seg.limit) if result.limit_hit else None), result.coverage


def _event_table(inp: BuildInput, seg: EventSegment, title: str) -> tuple[TableBlock, Coverage]:
    def t(k: str) -> str:
        return tr(inp.lang, k)
    result = run_segment(inp.ctx, seg, now=inp.now)
    if seg.view is SegmentView.RANKING:
        columns = (*(Column(key=f"k{i}", label=t(DIM_KEYS[g.dimension])) for i, g in enumerate(seg.group_by)),
                   Column(key="n", label=t(METRIC_KEYS["events"]), kind="number"))
        rows: tuple[tuple[Cell, ...], ...] = tuple(
            (*((r.display[i] or str(k) if k not in (None, "") else t("rpt_none_value")) for i, k in enumerate(r.keys)),
             r.value) for r in result.ranking or [])
    else:
        columns = (Column(key="time", label=t("evidence_col_time"), kind="time"),
                   Column(key="type", label=t("evidence_col_event_type")),
                   Column(key="severity", label=t("evidence_col_severity")),
                   Column(key="actor", label=t("evidence_col_actor")))
        rows = tuple((r.timestamp.isoformat(), r.event_type, r.severity or "", r.created_by_name or "")
                     for r in result.detail or [] if isinstance(r, EventRow))
    return TableBlock(title=title, columns=columns, rows=rows, total_rows=len(rows), empty_text=t("rpt_cust_no_events"),
                      limit_note=tr(inp.lang, "rpt_limit_top_n", n=seg.limit) if result.limit_hit else None), \
        result.coverage


def flows_coverage(inp: BuildInput) -> Coverage:
    """The traffic store's coverage of the report's period (what a flow ranking read)."""
    seg = FlowSegment(filter=FlowCondition().within(inp.start, inp.end), view=SegmentView.DETAIL, limit=1)
    return run_segment(inp.ctx, seg, now=inp.now).coverage


def _section(inp: BuildInput, i: int, sec: CustomSection) -> Section:
    seg = sec.segment.materialize(inp.start, inp.end)
    cov: Coverage | None = None
    notes: tuple[TextBlock, ...] = ()
    if isinstance(seg, EventSegment):
        # events are the install's: a store pulled for the traffic holds none
        block, cov = _event_table(dataclasses.replace(inp, ctx=inp.install or inp.ctx), seg, sec.title)
    elif seg.view is SegmentView.RANKING:
        columns = (*(Column(key=f"k{j}", label=tr(inp.lang, DIM_KEYS[g.dimension])) for j, g in enumerate(seg.group_by)),
                   Column(key="v", label=tr(inp.lang, METRIC_KEYS.get(seg.metric.value, "rpt_col_metric")),
                          kind="number"))
        block = flowsections.ranking(inp, title=sec.title, group_by=seg.group_by, metric=seg.metric, columns=columns,
                                     limit=seg.limit, spec=seg.filter)
        if seg.metric is SegmentMetric.BYTES:  # bytes ride on few flows (spec §6.5.7): say how many
            fc = field_coverage(inp.ctx, seg.filter)
            lines = flowsections.coverage_lines(inp, fc)
            if fc is not None and fc.total and not fc.bytes:
                lines = (*lines, tr(inp.lang, "rpt_cust_bytes_unknown"))
            notes = (TextBlock(paragraphs=lines),) if lines else ()
    else:
        block, cov = _flow_detail(inp, seg, sec.title)
    words = flowsections.filter_text(sec.segment.condition, inp.lang) if sec.segment.mode == "flows" else None
    intro = tr(inp.lang, "rpt_cust_conditions", conditions=words) if words else ""
    if cov is None:  # a flow ranking: the store's coverage of the section's own period
        cov = flows_coverage(inp)
    return Section(id=f"s{i + 1}", title=sec.title, intro=intro, blocks=(*_gaps(inp, cov), *notes, block),
                   workbench_link=_link(inp, sec))


def build_custom(inp: BuildInput) -> ReportDocument:
    rep = custom_reports.get(inp.ctx, inp.params.custom_id) if inp.params.custom_id is not None else None
    if rep is None:
        raise ReportFailed("rpt_err_custom_missing")  # deleted after it was queued or scheduled
    sections = tuple(_section(inp, i, s) for i, s in enumerate(rep.sections))
    quality: tuple[str, ...] = ()
    if any(sec.segment.mode == "flows" for sec in rep.sections):
        quality += coverage_note(inp.ctx, inp.start, inp.end, inp.lang, now=inp.now, tz=inp.tz, flows=True)
    if not inp.ctx.settings.current().reports.gui_external_url:
        quality += (tr(inp.lang, "rpt_cust_no_links"),)
    return ReportDocument(
        report_type=ReportType.CUSTOM, lang=inp.lang, title=rep.name, period_start=inp.start, period_end=inp.end,
        generated_at=inp.now, pce_label=inp.pce_label, kpis=(), findings=(), data_quality=quality,
        sections=sections or (Section(id="empty", title=rep.name, blocks=(TextBlock(paragraphs=(
            tr(inp.lang, "rpt_cust_empty"),)),)),))
