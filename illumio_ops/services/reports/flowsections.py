"""The pieces every flow report is built from (spec §6.3 point 4): a ranking is an analysis segment computed by
run_segment — the same number the workbench shows — turned into a report table; plus the report's filter in
words and the optional fields' coverage."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from illumio_ops.domain.filter import (
    EndpointFilter,
    FilterSpec,
    FlowCondition,
    endpoint_matches,
)
from illumio_ops.domain.lateral import HostInfo
from illumio_ops.domain.report import Cell, Column, TableBlock
from illumio_ops.domain.segment import FlowSegment, GroupBy
from illumio_ops.domain.values import (
    Language,
    PolicyDecision,
    SegmentDimension,
    SegmentMetric,
    SegmentView,
)
from illumio_ops.services.analysis.segments import run_segment
from illumio_ops.services.flowsource import AggRow, FieldCoverage
from illumio_ops.services.hosts import display_names
from illumio_ops.services.reports.common import host_name, port_text, tr
from illumio_ops.services.reports.registry import BuildInput

DECISION_KEYS = {"allowed": "decision_allowed", "potentially_blocked": "decision_potentially_blocked",
                 "blocked": "decision_blocked", "unknown": "decision_unknown"}
DIRECTION_KEYS = {"inbound": "rpt_direction_inbound", "outbound": "rpt_direction_outbound"}
_HOSTS = (SegmentDimension.SRC_HOST, SegmentDimension.DST_HOST)
_LABELS = (SegmentDimension.SRC_LABEL, SegmentDimension.DST_LABEL)


def window(inp: BuildInput) -> FilterSpec:
    """The report's period and filter."""
    base = dict(inp.params.filter) if inp.params.filter is not None else {}
    return FilterSpec(start=inp.start, end=inp.end, **base)


def narrowed(spec: FilterSpec, decisions: Sequence[PolicyDecision]) -> FilterSpec | None:
    """`spec` limited to `decisions` as well: a section's own decisions narrow the report's filter, never
    replace it. None when the two share no decision (the section has nothing to show)."""
    if not spec.decisions:
        return spec.model_copy(update={"decisions": tuple(decisions)})
    both = tuple(d for d in spec.decisions if d in decisions)
    return spec.model_copy(update={"decisions": both}) if both else None


def _key_text(inp: BuildInput, g: GroupBy, key: Any, display: str | None, names: dict[str, str]) -> str:
    if g.dimension in _HOSTS:
        return display or names.get(str(key)) or host_name({}, str(key), inp.lang)
    if g.dimension in _LABELS:
        return str(key) if key not in (None, "") else tr(inp.lang, "rpt_no_label")
    if g.dimension is SegmentDimension.SERVICE:
        port, _, proto = str(key).partition("/")
        return port_text(int(port), int(proto)) if port.lstrip("-").isdigit() and proto.isdigit() else str(key)
    if g.dimension is SegmentDimension.DECISION:
        return tr(inp.lang, DECISION_KEYS.get(str(key), "decision_unknown"))
    if g.dimension is SegmentDimension.DIRECTION:
        return tr(inp.lang, DIRECTION_KEYS.get(str(key), str(key)))
    return str(key) if key not in (None, "") else tr(inp.lang, "rpt_none_value")


def _names(inp: BuildInput, rows: Sequence[AggRow], group_by: Sequence[GroupBy]) -> dict[str, str]:
    """Host keys the flows did not name, as every page shows them (hosts.display_names): never an href."""
    keys = {str(r.keys[i]) for r in rows for i, g in enumerate(group_by) if g.dimension in _HOSTS and not r.display[i]}
    if not keys:
        return {}
    return display_names(inp.ctx, keys, lang=inp.lang)


def ranking(inp: BuildInput, *, title: str, group_by: Sequence[GroupBy], metric: SegmentMetric,
            columns: Sequence[Column], decisions: Sequence[PolicyDecision] = (), limit: int = 20,
            spec: FilterSpec | None = None, skip_empty: bool = False) -> TableBlock:
    """A top-`limit` ranking as a table: one column per grouping level, then the metric. `spec` replaces the
    report's window and filter (a report that builds its own sides, such as one app's inbound traffic);
    `decisions` narrows it (see narrowed). skip_empty: flows without the grouped field (no user, no
    process) are not ranked as a "(none)" row."""
    empty = tr(inp.lang, "rpt_no_flows_filtered" if inp.params.filter is not None else "rpt_no_flows")
    base: FilterSpec | None = spec or window(inp)
    if decisions and base is not None:
        base = narrowed(base, decisions)
    if base is None:
        return TableBlock(title=title, columns=tuple(columns), rows=(), total_rows=0, empty_text=empty)
    seg = FlowSegment(filter=base, group_by=tuple(group_by), metric=metric,
                      view=SegmentView.RANKING, limit=limit + 1 if skip_empty else limit)
    result = run_segment(inp.ctx, seg, now=inp.now)
    rows_in = result.ranking or []
    limit_hit = result.limit_hit
    if skip_empty:
        rows_in = [r for r in rows_in if any(k not in (None, "") for k in r.keys)]
        limit_hit = limit_hit or len(rows_in) > limit
        rows_in = rows_in[:limit]
    names = _names(inp, rows_in, group_by)
    rows: tuple[tuple[Cell, ...], ...] = tuple(
        (*(_key_text(inp, g, r.keys[i], r.display[i], names) for i, g in enumerate(group_by)), r.value)
        for r in rows_in)
    return TableBlock(title=title, columns=tuple(columns), rows=rows, total_rows=len(rows), empty_text=empty,
                      limit_note=tr(inp.lang, "rpt_limit_top_n", n=limit) if limit_hit else None)


def _side_text(side: EndpointFilter, lang: Language, prefix_key: str) -> list[str]:
    out = []
    for lc in side.labels:
        out.append(tr(lang, "rpt_filter_label", side=tr(lang, prefix_key), key=lc.key,
                      values=tr(lang, "rpt_filter_or").join(lc.values)))
    if side.hrefs or side.ips:
        out.append(tr(lang, "rpt_filter_hosts", side=tr(lang, prefix_key), n=len(side.hrefs) + len(side.ips)))
    return out


def filter_text(cond: FlowCondition | None, lang: Language) -> str | None:
    """The report's filter in words for the cover and the data-quality line; None without a filter."""
    if cond is None:
        return None
    parts: list[str] = []
    if cond.src is not None:
        parts += _side_text(cond.src, lang, "rpt_filter_source")
    if cond.dst is not None:
        parts += _side_text(cond.dst, lang, "rpt_filter_destination")
    if cond.ports:
        parts.append(tr(lang, "rpt_filter_ports", ports=", ".join(port_text(p.port, p.proto or 6) for p in cond.ports)))
    if cond.decisions:
        parts.append(tr(lang, "rpt_filter_decisions",
                        decisions=", ".join(tr(lang, DECISION_KEYS[d.value]) for d in cond.decisions)))
    return "; ".join(parts) or None


def coverage_lines(inp: BuildInput, fc: FieldCoverage | None) -> tuple[str, ...]:
    """How much of the period's traffic carries a process, a user and byte counts (spec §6.5.7)."""
    if fc is None or not fc.total:
        return ()

    def pct(n: int) -> str:
        return f"{100 * n / fc.total:.1f}"
    return (tr(inp.lang, "rpt_field_coverage", process=pct(fc.initiator_process), user=pct(fc.initiator_user),
               bytes=pct(fc.bytes)),)


def host_in_scope(host: HostInfo, cond: FlowCondition | None) -> bool:
    """A managed host a filtered report is about: one an include side of the filter matches (labels, href or
    address, as the flows are matched) and that side's exclusion does not; every host without include
    conditions, minus the excluded ones. Inventory hosts carry no address here, so an address-only side
    matches none of them."""
    if not host.managed:
        return False
    if cond is None:
        return True

    def hits(ep: EndpointFilter | None) -> bool:
        return ep is not None and not ep.is_empty() and endpoint_matches(ep, href=host.href, ip="", labels=host.labels)
    sides = [(cond.src, cond.src_exclude), (cond.dst, cond.dst_exclude)]
    includes = [(inc, exc) for inc, exc in sides if inc is not None and not inc.is_empty()]
    if not includes:
        return not any(hits(exc) for _, exc in sides)
    return any(hits(inc) and not hits(exc) for inc, exc in includes)
