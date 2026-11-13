"""The pieces every flow report is built from (spec §6.3 point 4): a ranking is an analysis segment computed by
run_segment — the same number the workbench shows — turned into a report table; plus the report's filter in
words, the optional fields' coverage, and the chapters more than one report may carry (the flows without a
decision, users and processes)."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from pydantic import ValidationError

from illumio_ops.domain.filter import (
    EndpointFilter,
    FilterSpec,
    FlowCondition,
    LabelGroups,
    endpoint_matches,
    label_group_hrefs,
)
from illumio_ops.domain.lateral import HostInfo
from illumio_ops.domain.report import (
    HTML_ROW_CAP,
    Cell,
    Column,
    Section,
    TableBlock,
    TextBlock,
)
from illumio_ops.domain.segment import FlowSegment, GroupBy
from illumio_ops.domain.values import (
    Language,
    PolicyDecision,
    SegmentDimension,
    SegmentMetric,
    SegmentView,
)
from illumio_ops.services.analysis.segments import run_segment
from illumio_ops.services.context import AppContext
from illumio_ops.services.flowsource import (
    AggRow,
    FieldCoverage,
    FlowTotals,
    Undecided,
    UndecidedEnd,
    UndecidedHost,
    undecided_breakdown,
)
from illumio_ops.services.hosts import display_names
from illumio_ops.services.reports.common import (
    DECISION_IN_SENTENCE_KEYS,
    DECISION_KEYS,
    host_key,
    host_keys,
    host_name,
    mode_word,
    port_text,
    tr,
)
from illumio_ops.services.reports.hints import hint
from illumio_ops.services.reports.registry import BuildInput
from illumio_ops.services.workbench import FlowRequest
from illumio_ops.store.flowdb import policy_objects

DIRECTION_KEYS = {"inbound": "rpt_direction_inbound", "outbound": "rpt_direction_outbound"}
_HOSTS = (SegmentDimension.SRC_HOST, SegmentDimension.DST_HOST)
_LABELS = (SegmentDimension.SRC_LABEL, SegmentDimension.DST_LABEL)


def window(inp: BuildInput) -> FilterSpec:
    """The report's period and filter."""
    base = dict(inp.params.filter) if inp.params.filter is not None else {}
    return FilterSpec(start=inp.start, end=inp.end, **base)


def decided_note(lang: Language, undecided: Undecided) -> tuple[TextBlock, ...]:
    """Under a table of the three decisions: the shares count the decided flows, and how many flows have no
    decision and where they are listed. Nothing when every flow has a decision."""
    if not undecided.flows:
        return ()
    return (TextBlock(paragraphs=(tr(lang, "rpt_decided_note", flows=f"{undecided.flows:,}",
                                     connections=f"{undecided.connections:,}"),)),)


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


def segment(inp: BuildInput, *, group_by: Sequence[GroupBy], metric: SegmentMetric,
            decisions: Sequence[PolicyDecision] = (), limit: int = 20,
            spec: FilterSpec | None = None) -> FlowSegment | None:
    """The analysis segment a ranking runs: the report's window and filter (or `spec`), narrowed to `decisions`.
    None when the two share no decision."""
    base: FilterSpec | None = spec or window(inp)
    if decisions and base is not None:
        base = narrowed(base, decisions)
    if base is None:
        return None
    return FlowSegment(filter=base, group_by=tuple(group_by), metric=metric, view=SegmentView.RANKING, limit=limit)


def workbench_link(inp: BuildInput, seg: FlowSegment | None) -> str | None:
    """A section's segment opened in the workbench (spec §6.5.5: every section computed from traffic links to
    it): the same filter, grouping and metric, nothing composed apart. None without a GUI address, without a
    segment, or when the workbench cannot take the period (longer than its 30 days)."""
    base = inp.ctx.settings.current().reports.gui_external_url
    if not base or seg is None:
        return None
    condition = FlowCondition(**{name: getattr(seg.filter, name) for name in FlowCondition.model_fields})
    try:
        req = FlowRequest(mode="flows", start=seg.filter.start, end=seg.filter.end, view=seg.view,
                          group_by=seg.group_by, metric=seg.metric, limit=seg.limit, condition=condition)
    except (ValidationError, ValueError):
        return None
    return f"{base.rstrip('/')}/investigate?{urlencode({'q': req.model_dump_json(exclude_none=True)})}"


def no_links_note(inp: BuildInput) -> tuple[str, ...]:
    """Why the sections carry no workbench link: the GUI's external address is not set (spec §6.5.5)."""
    return () if inp.ctx.settings.current().reports.gui_external_url else (tr(inp.lang, "rpt_cust_no_links"),)


def link(inp: BuildInput, *, group_by: Sequence[GroupBy], metric: SegmentMetric,
         decisions: Sequence[PolicyDecision] = (), limit: int = 20, spec: FilterSpec | None = None) -> str | None:
    """workbench_link of the segment ranking() runs for the same arguments."""
    return workbench_link(inp, segment(inp, group_by=group_by, metric=metric, decisions=decisions, limit=limit,
                                       spec=spec))


def ranking(inp: BuildInput, *, title: str, group_by: Sequence[GroupBy], metric: SegmentMetric,
            columns: Sequence[Column], decisions: Sequence[PolicyDecision] = (), limit: int = 20,
            spec: FilterSpec | None = None, skip_empty: bool = False) -> TableBlock:
    """A top-`limit` ranking as a table: one column per grouping level, then the metric. `spec` replaces the
    report's window and filter (a report that builds its own sides, such as one app's inbound traffic);
    `decisions` narrows it (see narrowed). skip_empty: flows without the grouped field (no user, no
    process) are not ranked as a "(none)" row. A level grouped by host is a host column: it carries each row's host
    key (host_keys), under the key of the column the caller gave for that level."""
    empty = tr(inp.lang, "rpt_no_flows_filtered" if inp.params.filter is not None else "rpt_no_flows")
    seg = segment(inp, group_by=group_by, metric=metric, decisions=decisions, spec=spec,
                  limit=limit + 1 if skip_empty else limit)
    if seg is None:
        return TableBlock(title=title, columns=tuple(columns), rows=(), total_rows=0, empty_text=empty)  # no rows: no keys
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
    by_host = [i for i, g in enumerate(group_by) if g.dimension in _HOSTS]
    shown = tuple(c.model_copy(update={"kind": "host"}) if i in by_host else c for i, c in enumerate(columns))
    return TableBlock(title=title, columns=shown, rows=rows, total_rows=len(rows), empty_text=empty,
                      limit_note=tr(inp.lang, "rpt_limit_top_n", n=limit) if limit_hit else None,
                      host_keys=host_keys(**{shown[i].key: [host_key({}, r.keys[i]) for r in rows_in]
                                             for i in by_host}))


def _side_text(side: EndpointFilter, lang: Language, prefix_key: str) -> list[str]:
    out = []
    name = tr(lang, prefix_key)
    for lc in side.labels:
        out.append(tr(lang, "rpt_filter_label", side=name, key=lc.key,
                      values=tr(lang, "rpt_filter_or").join(lc.values)))
    if side.label_groups:
        out.append(tr(lang, "rpt_filter_label_groups", side=name, n=len(side.label_groups)))
    if side.hrefs or side.ips:
        out.append(tr(lang, "rpt_filter_hosts", side=name, n=len(side.hrefs) + len(side.ips)))
    if side.ip_lists:
        out.append(tr(lang, "rpt_filter_ip_lists", side=name, n=len(side.ip_lists)))
    if side.public:
        out.append(tr(lang, "rpt_filter_field", name=name, value=tr(lang, "cond_public")))
    return out


_SIDE_TEXT_KEYS = {"src": "rpt_filter_source", "dst": "rpt_filter_destination", "either": "wb_cond_either",
                   "src_exclude": "wb_cond_src_not", "dst_exclude": "wb_cond_dst_not",
                   "either_exclude": "wb_cond_either_not"}
_VALUE_TEXT_KEYS = {"initiator_process": "wb_cond_initiator_process", "initiator_user": "wb_cond_initiator_user",
                    "service_process": "wb_cond_service_process", "service_user": "wb_cond_service_user",
                    "initiator_processes": "wb_cond_initiator_process", "initiator_users": "wb_cond_initiator_user",
                    "service_processes": "wb_cond_service_process", "service_users": "wb_cond_service_user",
                    "windows_services": "wb_cond_windows_service",
                    "exclude_windows_services": "wb_cond_windows_service_not",
                    "exclude_processes": "wb_cond_process_not", "text": "wb_cond_text"}
_TX_TEXT_KEYS = {"unicast": "cond_tx_unicast", "broadcast": "cond_tx_broadcast", "multicast": "cond_tx_multicast"}


def filter_text(cond: FlowCondition | None, lang: Language) -> str | None:
    """The report's filter in words for the cover and the data-quality line; None without a filter. Every condition
    the filter holds is named (PCE objects by count: the cover has no PCE to name them from)."""
    if cond is None:
        return None
    parts: list[str] = []
    for field, key in _SIDE_TEXT_KEYS.items():
        side = getattr(cond, field)
        if side is not None:
            parts += _side_text(side, lang, key)
    if cond.ports:
        parts.append(tr(lang, "rpt_filter_ports", ports=", ".join(port_text(p.port, p.proto or 6) for p in cond.ports)))
    for services, key in ((cond.services, "wb_cond_service"), (cond.exclude_services, "wb_cond_service_not")):
        if services:
            parts.append(tr(lang, "rpt_filter_services", name=tr(lang, key), n=len(services)))
    if cond.exclude_ports:
        parts.append(tr(lang, "rpt_filter_field", name=tr(lang, "wb_cond_port_not"),
                        value=", ".join(port_text(p.port, p.proto or 6) for p in cond.exclude_ports)))
    if cond.decisions:
        parts.append(tr(lang, "rpt_filter_decisions",
                        decisions=", ".join(tr(lang, DECISION_IN_SENTENCE_KEYS[d.value]) for d in cond.decisions)))
    for field, key in _VALUE_TEXT_KEYS.items():
        value = getattr(cond, field)
        if value:
            parts.append(tr(lang, "rpt_filter_field", name=tr(lang, key),
                            value=value if isinstance(value, str) else ", ".join(value)))
    for txs, key in ((cond.transmissions, "wb_cond_transmission"), (cond.exclude_transmissions,
                                                                      "wb_cond_transmission_not")):
        if txs:
            parts.append(tr(lang, "rpt_filter_field", name=tr(lang, key),
                            value=", ".join(tr(lang, _TX_TEXT_KEYS[x]) for x in txs)))
    if cond.exclude_system_accounts:
        parts.append(tr(lang, "wb_cond_no_system"))
    return "; ".join(parts) or None


def label_groups_of(ctx: AppContext, cond: FlowCondition | None) -> LabelGroups:
    """The members of the label groups a filter names (host_in_scope reads them)."""
    if cond is None or not label_group_hrefs(cond):
        return {}
    with ctx.flows().connect() as conn:
        return policy_objects.label_groups(conn, label_group_hrefs(cond))


def coverage_lines(inp: BuildInput, fc: FieldCoverage | None) -> tuple[str, ...]:
    """How much of the period's traffic carries a process, a user and byte counts (spec §6.5.7)."""
    if fc is None or not fc.total:
        return ()

    def pct(n: int) -> str:
        return f"{100 * n / fc.total:.1f}"
    return (tr(inp.lang, "rpt_field_coverage", process=pct(fc.initiator_process), user=pct(fc.initiator_user),
               bytes=pct(fc.bytes)),)


def host_in_scope(host: HostInfo, cond: FlowCondition | None, *, label_groups: LabelGroups) -> bool:
    """A managed host a filtered report is about: one an include side of the filter matches (labels, label groups,
    href or address, as the flows are matched) and that side's exclusion does not; every host without include
    conditions, minus the excluded ones. Either end counts as a side of its own. Inventory hosts carry no address
    here, so an address-only side matches none of them. label_groups: label_groups_of(the filter)."""
    if not host.managed:
        return False
    if cond is None:
        return True

    def hits(ep: EndpointFilter | None) -> bool:
        return ep is not None and not ep.is_empty() and endpoint_matches(ep, href=host.href, ip="", labels=host.labels,
                                                                          label_groups=label_groups)
    if hits(cond.either_exclude):
        return False
    sides = [(cond.src, cond.src_exclude), (cond.dst, cond.dst_exclude), (cond.either, None)]
    includes = [(inc, exc) for inc, exc in sides if inc is not None and not inc.is_empty()]
    if not includes:
        return not any(hits(exc) for _, exc in sides)
    return any(hits(inc) and not hits(exc) for inc, exc in includes)


# ── users and processes (UI redesign spec §9.2: moved from the security risk report to the traffic report) ────

USERS = "users"  # the chapter's id
USERS_TOP = 20  # each ranking's rows


def users_section(inp: BuildInput, spec: FilterSpec, fc: FieldCoverage) -> tuple[Section, ...]:
    """The chapter "Users and processes": the users who started connections, ranked by how many destinations each
    reached, and the processes, ranked by connections. `spec`: the report's flows; `fc`: how many of them name a
    user and a process (field_coverage of `spec`, which the builder has read). A ranking is there only when a flow
    names its field, and the chapter only when one of the two is: users_notes gives the data note for what is left
    out. The chapter opens its first ranking in the workbench."""
    if not (fc.initiator_user or fc.initiator_process):
        return ()
    lang = inp.lang

    def t(msg: str, /, **params: object) -> str:
        return tr(lang, msg, **params)

    def share(n: int) -> str:
        return f"{100 * n / fc.total:.1f}" if fc.total else "0.0"
    by_user = (GroupBy(dimension=SegmentDimension.INITIATOR_USER),)
    by_process = (GroupBy(dimension=SegmentDimension.INITIATOR_PROCESS),)
    blocks: list[TableBlock | TextBlock] = [TextBlock(paragraphs=(t(
        "rpt_users_intro", user=share(fc.initiator_user), process=share(fc.initiator_process)),))]
    if fc.initiator_user:
        blocks.append(ranking(
            inp, title=t("rpt_users_tbl_users"), spec=spec, metric=SegmentMetric.DISTINCT_DST, limit=USERS_TOP,
            group_by=by_user, skip_empty=True,
            columns=(Column(key="user", label=t("rpt_col_user")),
                     Column(key="n", label=t("rpt_col_distinct_destinations"), kind="number"))))
    if fc.initiator_process:
        blocks.append(ranking(
            inp, title=t("rpt_users_tbl_processes"), spec=spec, metric=SegmentMetric.CONNECTIONS, limit=USERS_TOP,
            group_by=by_process, skip_empty=True,
            columns=(Column(key="process", label=t("rpt_col_process")),
                     Column(key="n", label=t("rpt_col_connections"), kind="number"))))
    first = (link(inp, spec=spec, group_by=by_user, metric=SegmentMetric.DISTINCT_DST, limit=USERS_TOP)
             if fc.initiator_user else
             link(inp, spec=spec, group_by=by_process, metric=SegmentMetric.CONNECTIONS, limit=USERS_TOP))
    return (Section(id=USERS, title=t("rpt_users_sec"), blocks=tuple(blocks), workbench_link=first),)


def users_notes(lang: Language, fc: FieldCoverage) -> tuple[str, ...]:
    """The data note for what users_section leaves out (a part that is not there says why, hints.py): no flow of
    the period names a user, a process, or either — the last is why the report has no such chapter."""
    if not fc.initiator_user:
        return (hint(lang, "rpt_hint_pending_no_users" if fc.initiator_process
                     else "rpt_hint_pending_no_users_processes"),)
    if not fc.initiator_process:
        return (hint(lang, "rpt_hint_pending_no_processes"),)
    return ()


# ── the flows without a decision (UI redesign spec §9.2) ─────────────────────────────────────────────────────

MONITOR_ONLY = "monitor_only"  # the chapter's id
MONITOR_TOP = 10  # each ranking's rows: what a table prints on paper (PRINT_ROW_CAP), so none is cut there
MONITOR_HOSTS = HTML_ROW_CAP  # hosts listed: what the HTML prints
SHARE_LEAST = 0.1  # the smallest share one decimal can show: under it "less than 0.1%", never "0.0%"


@dataclass(frozen=True)
class Seen:
    """What a report saw in its period: every flow and connection, and the ones without a decision among them."""
    flows: int
    connections: int
    undecided: Undecided


def seen(*parts: FlowTotals) -> Seen:
    """Of one read, or of several disjoint reads added up (one app's inbound, outbound and intra-app traffic)."""
    return Seen(flows=sum(p.flows for p in parts), connections=sum(p.connections for p in parts),
                undecided=sum((p.undecided for p in parts), Undecided()))


def share_text(lang: Language, n: int, d: int) -> str:
    """n of d as a percentage to one decimal, for a sentence. A share that is there and would print as 0.0%, or
    that is not everything and would print as 100.0%, is said as "less than 0.1%" / "more than 99.9%"."""
    if not d:
        return "—"
    pct = 100 * n / d
    if 0 < pct < SHARE_LEAST:
        return tr(lang, "rpt_share_under", v=f"{SHARE_LEAST:.1f}")
    if 100 - SHARE_LEAST < pct < 100:
        return tr(lang, "rpt_share_over", v=f"{100 - SHARE_LEAST:.1f}")
    return f"{pct:.1f}%"


def undecided_caveat(lang: Language, saw: Seen, *, chapter: bool = True, elsewhere: str | None = None) -> tuple[str, ...]:
    """The sentence under the conclusion when some of the period's flows carry no decision: their share of every
    flow, and of every connection (the two differ widely: on lab 93% and 30%). chapter=False: the report has no
    monitor-only chapter to point at (readiness), and names the three factors that leave such connections out.
    elsewhere: the report has no such chapter and counts connections by decision (the weekly overview); the
    sentence names the report that lists these flows. Nothing when every flow has a decision."""
    if not saw.undecided.flows:
        return ()
    shares = {"pct_flows": share_text(lang, saw.undecided.flows, saw.flows),
              "pct_connections": share_text(lang, saw.undecided.connections, saw.connections)}
    if elsewhere is not None:
        return (tr(lang, "rpt_caveat_undecided_elsewhere", **shares, report=elsewhere),)
    if chapter:
        return (tr(lang, "rpt_caveat_undecided", **shares),)
    return (tr(lang, "rpt_caveat_undecided_plain", **shares, policy=tr(lang, "rpt_rdy_factor_policy"),
               staged=tr(lang, "rpt_rdy_factor_staged"), remote=tr(lang, "rpt_rdy_factor_remote")),)


def monitor_only_section(inp: BuildInput, spec: FilterSpec | Sequence[FilterSpec], saw: Seen, *,
                         hosts: Mapping[str, HostInfo]) -> tuple[Section, ...]:
    """The chapter "Traffic that can only be watched": the flows the PCE reported no decision for — how many of
    each kind, each kind's busiest sources and destinations, and the hosts with a VEN that appear in them.
    `spec`: the report's flows (several: the rows any of them matches); `saw`: their totals, read by the builder.
    `hosts`: the current inventory. A host's mode is the inventory's, today's, and the column says so: the mode
    stored with a flow is not the flow's. Only a host in Idle now gets a reason (an Idle VEN reports snapshots);
    the report gives none for the others. Nothing when every flow has a decision (and no read is made)."""
    u = saw.undecided
    if not u.flows:
        return ()
    lang = inp.lang

    def t(msg: str, /, **params: object) -> str:
        return tr(lang, msg, **params)

    def pct(n: int, d: int) -> str:
        return f"{100 * n / d:.1f}%" if d else "—"
    found = undecided_breakdown(inp.ctx, spec, top=MONITOR_TOP, hosts=MONITOR_HOSTS)
    empty = t("rpt_no_flows_filtered" if inp.params.filter is not None else "rpt_no_flows")
    kinds = TableBlock(
        title=t("rpt_mon_tbl_kinds"),
        columns=(Column(key="kind", label=t("rpt_mon_col_kind")), Column(key="means", label=t("rpt_mon_col_means")),
                 Column(key="flows", label=t("rpt_col_flows"), kind="number"),
                 Column(key="connections", label=t("rpt_col_connections"), kind="number"),
                 Column(key="share_flows", label=t("rpt_mon_col_share_flows")),
                 Column(key="share_connections", label=t("rpt_mon_col_share_connections"))),
        rows=((t("rpt_mon_kind_unmanaged"), t("rpt_mon_means_unmanaged"), u.unmanaged_flows, u.unmanaged_connections,
               pct(u.unmanaged_flows, saw.flows), pct(u.unmanaged_connections, saw.connections)),
              (t("rpt_mon_kind_managed"), t("rpt_mon_means_managed"), u.managed_flows, u.managed_connections,
               pct(u.managed_flows, saw.flows), pct(u.managed_connections, saw.connections))),
        total_rows=2, empty_text="")
    shown = [e.key for kind in (found.unmanaged, found.managed) for e in (*kind.sources, *kind.destinations)]
    names = display_names(inp.ctx, {*shown, *(h.key for h in found.managed_hosts)}, lang=lang)

    def ranking(title: str, label: str, ends: Sequence[UndecidedEnd], total: int) -> TableBlock:
        return TableBlock(
            title=t(title),
            columns=(Column(key="host", label=t(label), kind="host"),
                     Column(key="flows", label=t("rpt_col_flows"), kind="number"),
                     Column(key="connections", label=t("rpt_col_connections"), kind="number")),
            rows=tuple((names[e.key], e.flows, e.connections) for e in ends), total_rows=total,
            empty_text=empty, limit_note=t("rpt_limit_top_n", n=MONITOR_TOP) if total > len(ends) else None,
            host_keys=host_keys(host=(host_key({}, e.key) for e in ends)), host_section="connections")
    rankings = tuple(
        ranking(title, label, ends, total)
        for flows, title, label, ends, total in (
            (u.unmanaged_flows, "rpt_mon_tbl_src_unmanaged", "rpt_col_source", found.unmanaged.sources,
             found.unmanaged.sources_total),
            (u.unmanaged_flows, "rpt_mon_tbl_dst_unmanaged", "rpt_col_destination", found.unmanaged.destinations,
             found.unmanaged.destinations_total),
            (u.managed_flows, "rpt_mon_tbl_src_managed", "rpt_col_source", found.managed.sources,
             found.managed.sources_total),
            (u.managed_flows, "rpt_mon_tbl_dst_managed", "rpt_col_destination", found.managed.destinations,
             found.managed.destinations_total))
        if flows)  # a kind with no flow has its 0 in the first table and no ranking

    def mode_now(key: str) -> tuple[str, str]:
        """(the host's mode in the inventory now, the note beside it)."""
        host = hosts.get(key)
        if host is None:
            return t("rpt_mon_not_in_inventory"), ""
        if host.enforcement_mode == "idle":
            return mode_word(lang, "idle"), t("rpt_mon_idle_note")
        return (mode_word(lang, host.enforcement_mode) if host.enforcement_mode else "—"), ""

    def end(h: UndecidedHost) -> str:
        return t("rpt_mon_end_both" if h.as_source and h.as_destination
                 else "rpt_mon_end_source" if h.as_source else "rpt_mon_end_destination")
    listed = found.managed_hosts
    blocks: tuple[TableBlock | TextBlock, ...] = (kinds, *rankings)
    if u.managed_flows:
        blocks += (TextBlock(paragraphs=(t("rpt_mon_hosts_intro"),)), TableBlock(
            title=t("rpt_mon_tbl_hosts"),
            columns=(Column(key="host", label=t("rpt_col_host"), kind="host"),
                     Column(key="mode", label=t("rpt_mon_col_mode_now")),
                     Column(key="flows", label=t("rpt_col_flows"), kind="number"),
                     Column(key="connections", label=t("rpt_col_connections"), kind="number"),
                     Column(key="end", label=t("rpt_mon_col_end")), Column(key="note", label=t("rpt_mon_col_note"))),
            rows=tuple((names[h.key], mode_now(h.key)[0], h.flows, h.connections, end(h), mode_now(h.key)[1])
                       for h in listed),
            total_rows=found.managed_hosts_total, empty_text=empty,
            limit_note=(t("rpt_limit_top_n", n=MONITOR_HOSTS) if found.managed_hosts_total > len(listed) else None),
            host_keys=host_keys(host=(host_key({}, h.key) for h in listed))))
    return (Section(id=MONITOR_ONLY, title=t("rpt_mon_sec"), intro=t("rpt_mon_intro"), blocks=blocks),)
