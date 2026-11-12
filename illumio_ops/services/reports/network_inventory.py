"""The network inventory report (spec §6.5 報表, 5.x network_inventory): how the estate is labelled and how its apps
depend on each other — label hygiene in the inventory and the flows, app-to-app dependencies within and across
environments, the services each app provides, unmanaged sources reaching apps, and the rule findings."""
from __future__ import annotations

from collections import defaultdict

from illumio_ops.domain.report import (
    Column,
    Kpi,
    ReportDocument,
    Section,
    TableBlock,
    TextBlock,
)
from illumio_ops.domain.segment import FlowSegment, GroupBy
from illumio_ops.domain.values import SegmentDimension, SegmentMetric, SegmentView
from illumio_ops.services.analysis.context import load_lateral_context
from illumio_ops.services.analysis.segments import run_segment
from illumio_ops.services.flowsource import label_conflicts, label_mix
from illumio_ops.services.hosts import display_names
from illumio_ops.services.reports import findings, flowsections
from illumio_ops.services.reports.common import host_key, host_keys, port_text, tr
from illumio_ops.services.reports.generate import (
    coverage_text,
    previous_period,
    traffic_covered,
)
from illumio_ops.services.reports.registry import BuildInput

TOP = 20
TOP_SERVICES = 3
PAIR_LIMIT = 1000  # app x service and app x source-app pairs read for the per-app table
APP = "app"
HYGIENE_KEYS = (APP, "loc", "role")  # with the configured environment key
SETS_SHOWN = 5  # label combinations listed per endpoint; more are counted


def _service(key: object) -> str:
    port, _, proto = str(key).partition("/")
    return port_text(int(port), int(proto)) if port.lstrip("-").isdigit() and proto.isdigit() else str(key)


def build_network_inventory(inp: BuildInput) -> ReportDocument:
    lang = inp.lang

    def t(msg: str, /, **params: object) -> str:
        return tr(lang, msg, **params)

    lc = load_lateral_context(inp.ctx, now=inp.now)
    env_key = lc.settings.environment_label_key
    spec = flowsections.window(inp)
    no_flows = t("rpt_no_flows_filtered" if inp.params.filter is not None else "rpt_no_flows")
    no_label = t("rpt_no_label")

    # ── label hygiene ───────────────────────────────────────────────────────
    keys = (APP, env_key, *HYGIENE_KEYS[1:])
    scope_groups = flowsections.label_groups_of(inp.ctx, inp.params.filter)
    managed = [h for h in lc.hosts.values()
               if flowsections.host_in_scope(h, inp.params.filter, label_groups=scope_groups)]
    missing = sorted(((h.hostname or h.key, [k for k in keys if not h.labels.get(k)], h.key) for h in managed),
                     key=lambda r: (-len(r[1]), r[0]))
    missing = [(name, ks, key) for name, ks, key in missing if ks]
    hygiene = TableBlock(
        title=t("rpt_inv_tbl_hygiene"),
        columns=(Column(key="host", label=t("rpt_col_host"), kind="host"),
                 Column(key="missing", label=t("rpt_col_missing_labels"))),
        rows=tuple((name, ", ".join(ks)) for name, ks, _ in missing), total_rows=len(missing),
        empty_text=t("rpt_inv_hygiene_clean", keys=", ".join(keys)),
        host_keys=host_keys(host=(key for _, _, key in missing)))
    mix = label_mix(inp.ctx, spec, app_key=APP, env_key=env_key, top=TOP)
    prev_start, _ = previous_period(inp.start, inp.end, inp.tz)
    prev_cross = (label_mix(inp.ctx, spec.model_copy(update={"start": prev_start, "end": inp.start}), app_key=APP,
                            env_key=env_key, top=0).cross_env_connections
                  if traffic_covered(inp.ctx, prev_start, inp.start, now=inp.now, flows=True) else None)

    # ── dependencies ────────────────────────────────────────────────────────
    pairs = flowsections.ranking(
        inp, title=t("rpt_inv_tbl_pairs"), metric=SegmentMetric.CONNECTIONS, limit=TOP,
        group_by=(GroupBy(dimension=SegmentDimension.SRC_LABEL, label_key=APP),
                  GroupBy(dimension=SegmentDimension.DST_LABEL, label_key=APP)),
        columns=(Column(key="src", label=t("rpt_col_src_label", key=APP)),
                 Column(key="dst", label=t("rpt_col_dst_label", key=APP)),
                 Column(key="n", label=t("rpt_col_connections"), kind="number")))
    env_text = TextBlock(paragraphs=(t("rpt_inv_env_mix", same=f"{mix.same_env_connections:,}",
                                       cross=f"{mix.cross_env_connections:,}",
                                       unknown=f"{mix.unknown_env_connections:,}", key=env_key),))

    # ── services each app provides ──────────────────────────────────────────
    def pairs_of(second: GroupBy) -> tuple[list[tuple[object, object, int]], bool]:
        res = run_segment(inp.ctx, FlowSegment(
            filter=spec, metric=SegmentMetric.CONNECTIONS, view=SegmentView.RANKING, limit=PAIR_LIMIT,
            group_by=(GroupBy(dimension=SegmentDimension.DST_LABEL, label_key=APP), second)), now=inp.now)
        return [(r.keys[0], r.keys[1], int(r.value or 0)) for r in res.ranking or []], res.limit_hit
    by_service, hit_a = pairs_of(GroupBy(dimension=SegmentDimension.SERVICE))
    by_source, hit_b = pairs_of(GroupBy(dimension=SegmentDimension.SRC_LABEL, label_key=APP))
    totals: dict[object, int] = defaultdict(int)
    services: dict[object, list[tuple[int, str]]] = defaultdict(list)
    for app, svc, n in by_service:
        totals[app] += n
        services[app].append((n, _service(svc)))
    sources: dict[object, int] = defaultdict(int)
    for app, src, _n in by_source:
        if src not in (None, ""):
            sources[app] += 1
    apps = sorted(totals, key=lambda a: (-totals[a], str(a)))
    provided = TableBlock(
        title=t("rpt_inv_tbl_services"),
        columns=(Column(key="app", label=t("rpt_col_dst_label", key=APP)),
                 Column(key="n", label=t("rpt_col_connections"), kind="number"),
                 Column(key="services", label=t("rpt_col_top_services")),
                 Column(key="sources", label=t("rpt_col_source_apps"), kind="number")),
        rows=tuple((str(a) if a not in (None, "") else no_label, totals[a],
                    ", ".join(s for _, s in sorted(services[a], key=lambda x: -x[0])[:TOP_SERVICES]), sources[a])
                   for a in apps[:TOP]),
        total_rows=len(apps), empty_text=no_flows,
        limit_note=" ".join(n for n in (t("rpt_limit_top_n", n=TOP) if len(apps) > TOP else "",
                                        t("rpt_inv_pairs_limit", n=f"{PAIR_LIMIT:,}") if hit_a or hit_b else "")
                            if n) or None)

    # ── unmanaged sources into apps ─────────────────────────────────────────
    unmanaged = TableBlock(
        title=t("rpt_inv_tbl_unmanaged"),
        columns=(Column(key="app", label=t("rpt_col_dst_label", key=APP)),
                 Column(key="n", label=t("rpt_col_connections"), kind="number"),
                 Column(key="sources", label=t("rpt_col_unmanaged_sources"), kind="number")),
        rows=tuple((a or no_label, n, s) for a, n, s in mix.unmanaged_into_apps),
        total_rows=mix.unmanaged_into_apps_total, empty_text=t("rpt_inv_unmanaged_none"),
        limit_note=t("rpt_limit_top_n", n=TOP) if mix.unmanaged_into_apps_total > TOP else None)

    # ── label conflicts ─────────────────────────────────────────────────────
    found = label_conflicts(inp.ctx, spec, top=TOP)

    def sets_text(sets: list[dict[str, str]]) -> str:
        shown = [", ".join(f"{k}={v}" for k, v in sorted(s.items())) or t("rpt_inv_no_labels") for s in sets[:SETS_SHOWN]]
        more = [t("rpt_inv_more_sets", n=len(sets) - SETS_SHOWN)] if len(sets) > SETS_SHOWN else []
        return " | ".join(shown + more)
    shown_as = display_names(inp.ctx, [c.key for c in found.rows], lang=lang)
    conflicts = TableBlock(
        title=t("rpt_inv_tbl_conflicts"),
        columns=(Column(key="host", label=t("rpt_col_host"), kind="host"),
                 Column(key="n", label=t("rpt_inv_col_combinations"), kind="number"),
                 Column(key="sets", label=t("rpt_inv_col_label_sets")),
                 Column(key="connections", label=t("rpt_col_connections"), kind="number")),
        rows=tuple((shown_as.get(c.key, c.key), len(c.sets), sets_text(c.sets), c.connections)
                   for c in found.rows),
        total_rows=found.total, empty_text=t("rpt_inv_conflicts_none") if totals else no_flows,
        host_keys=host_keys(host=(host_key({}, c.key) for c in found.rows)),
        limit_note=t("rpt_limit_top_n", n=TOP) if found.total > TOP else None)

    outcomes = findings.run_rules(inp.ctx, spec, inp.ctx.settings.current().reports.rule_thresholds, lang,
                                  now=inp.now, scoped=inp.params.filter is not None) if totals else []
    kpis = (
        Kpi(key="managed_hosts", label=t("rpt_inv_kpi_managed_hosts"), value=len(managed), previous=None),
        Kpi(key="hosts_missing_labels", label=t("rpt_inv_kpi_missing_labels"), value=len(missing), previous=None,
            better="lower"),
        Kpi(key="apps", label=t("rpt_inv_kpi_apps"), value=sum(1 for a in apps if a not in (None, "")) if apps else None,
            previous=None, note=None if apps else no_flows),
        Kpi(key="cross_env_connections", label=t("rpt_inv_kpi_cross_env"),
            value=mix.cross_env_connections if apps else None, previous=prev_cross, better="lower",
            note=None if apps else no_flows),
    )
    filter_line = flowsections.filter_text(inp.params.filter, lang)
    cov = coverage_text(inp.ctx, inp.start, inp.end, lang, now=inp.now, tz=inp.tz, flows=True)
    quality = (*cov.lines,
               *((t("rpt_quality_filter", filter=filter_line),) if filter_line else ()),
               t("rpt_trf_quality_counts"), t("rpt_inv_quality_inventory"))
    return ReportDocument(
        report_type=inp.params.report_type, lang=lang, title=t("rpt_title_network_inventory"),
        period_start=inp.start, period_end=inp.end, generated_at=inp.now, pce_label=inp.pce_label, kpis=kpis,
        findings=findings.as_findings(outcomes, lang), caveats=cov.caveats,
        data_quality=(*quality, *flowsections.no_links_note(inp)),
        sections=(
            Section(id="hygiene", title=t("rpt_inv_sec_hygiene"), intro=t("rpt_inv_hygiene_intro", keys=", ".join(keys)),
                    blocks=(hygiene, TextBlock(paragraphs=(t("rpt_inv_unlabeled_flows",
                                                             n=f"{mix.unlabeled_app_flows:,}"),)),
                            conflicts, TextBlock(paragraphs=(t("rpt_inv_conflicts_note"),)))),
            Section(id="dependencies", title=t("rpt_inv_sec_dependencies"), blocks=(pairs, env_text),
                    workbench_link=flowsections.link(
                        inp, metric=SegmentMetric.CONNECTIONS, limit=TOP,
                        group_by=(GroupBy(dimension=SegmentDimension.SRC_LABEL, label_key=APP),
                                  GroupBy(dimension=SegmentDimension.DST_LABEL, label_key=APP)))),
            Section(id="services", title=t("rpt_inv_sec_services"), intro=t("rpt_inv_services_intro"),
                    blocks=(provided,)),
            Section(id="unmanaged", title=t("rpt_inv_sec_unmanaged"), blocks=(unmanaged,)),
            *findings.unevaluated_section(outcomes, lang,
                                          title=t("rpt_rules_sec_unevaluated"), intro=t("rpt_trf_findings_intro"),
                                          table_title=t("rpt_rules_tbl_unevaluated"), evaluated=bool(totals))))
