"""The lateral movement posture report (spec §6.5.5 flagship): exposure now and after enforcement, the critical
assets and where to cut, the period's detections, cross-environment management connections, and directory and
authentication traffic (roadmap: P5 adds that section). Every number comes from what the analysis jobs stored;
nothing is recomputed here."""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any

from illumio_ops.domain.report import (
    BarBlock,
    Column,
    Finding,
    Kpi,
    ReportDocument,
    Section,
    TableBlock,
)
from illumio_ops.domain.values import FocusKind, Language, Severity
from illumio_ops.services.analysis.anomaly_inputs import directory_servers
from illumio_ops.services.analysis.context import LateralContext, load_lateral_context
from illumio_ops.services.reports import reads
from illumio_ops.services.reports.common import (
    detector_name,
    host_name,
    port_text,
    ports_text,
    severity_name,
    tr,
)
from illumio_ops.services.reports.generate import (
    coverage_note,
    previous_period,
    traffic_covered,
)
from illumio_ops.services.reports.registry import BuildInput
from illumio_ops.store.flowdb import analysis
from illumio_ops.store.flowdb.db import db_day

DETECTION_ROWS = 1000
REACH_ROWS = 50
DIRECTORY_SOURCES = 20
STALE_AFTER = timedelta(hours=2)  # the exposure job runs hourly; older means at least one run was missed
FINDING_KINDS = {FocusKind.DETECTION.value: "rpt_action_detection",
                 FocusKind.EXPOSURE_ASSET.value: "rpt_action_exposure_asset",
                 FocusKind.PIVOT_HOST.value: "rpt_action_pivot_host",
                 FocusKind.CROSS_ENV.value: "rpt_action_cross_env"}
DIRECTORY_DETECTORS = ("auth_to_non_dc", "new_dc_client", "directory_surge")
EDGE_STATE_KEYS = {"allowed": "decision_allowed", "potentially_blocked": "decision_potentially_blocked",
                   "unknown": "decision_unknown"}


def _snapshot_on_or_before(snaps: Sequence[tuple[str, dict[str, Any]]], day: str) -> dict[str, Any] | None:
    found = None
    for d, metrics in snaps:
        if d <= day:
            found = metrics
    return found


def _findings(focus: Mapping[str, Any] | None, lang: Language) -> tuple[Finding, ...]:
    out = []
    for item in (focus or {}).get("items") or ():
        action = FINDING_KINDS.get(item.get("kind"))
        if action is None:
            continue
        params = {k: v for k, v in (item.get("params") or {}).items() if not isinstance(v, (dict, list))}
        out.append(Finding(severity=Severity(item.get("severity", "medium")),
                           title=tr(lang, item["title_key"], **params), why=tr(lang, item["why_key"], **params),
                           action=tr(lang, action)))
        if len(out) == 5:
            break
    return tuple(out)


class _Builder:
    def __init__(self, inp: BuildInput) -> None:
        self.inp, self.lang = inp, inp.lang
        self.lc: LateralContext = load_lateral_context(inp.ctx, now=inp.now)
        self.critical_set = bool(self.lc.settings.critical_assets)

    def t(self, msg: str, /, **params: object) -> str:
        return tr(self.lang, msg, **params)

    def name(self, key: str) -> str:
        return host_name(self.lc.hosts, key, self.lang)

    def not_computed(self, title: str) -> TableBlock:
        return TableBlock(title=title, columns=(Column(key="x", label=title),), rows=(), total_rows=0,
                          empty_text=self.t("rpt_lat_not_computed"))

    # ── key metrics ──────────────────────────────────────────────────────────
    def kpis(self, exposure: Mapping[str, Any] | None, snaps: Sequence[tuple[str, dict[str, Any]]],
             detections_now: int, detections_before: int | None) -> tuple[Kpi, ...]:
        inp = self.inp
        last_day = db_day(inp.end - timedelta(microseconds=1))
        prev_day = db_day(inp.start - timedelta(microseconds=1))
        current = _snapshot_on_or_before([s for s in snaps if s[0] >= db_day(inp.start)], last_day)
        previous = _snapshot_on_or_before(snaps, prev_day)
        note = None
        if current is None and exposure is not None:
            current = {"assets_reachable_now": sum(1 for a in exposure.get("assets") or () if a.get("sources_now")),
                       "pivots_now": sum(1 for h in exposure.get("hosts") or () if h.get("pivot_now")),
                       "cross_env_edges": exposure.get("cross_env_total")}
            note = self.t("rpt_lat_kpi_from_current")

        def metric(key: str, metric_key: str, label_key: str, *, extra_note: str | None = None,
                   unset: bool = False) -> Kpi:
            if unset:
                return Kpi(key=key, label=self.t(label_key), value=None, previous=None, better="lower",
                           note=self.t("rpt_lat_no_critical_assets"))
            value = None if current is None else current.get(metric_key)
            prev = None if previous is None else previous.get(metric_key)
            return Kpi(key=key, label=self.t(label_key), value=value, previous=prev, better="lower",
                       note=extra_note if value is not None else self.t("rpt_lat_not_computed"))

        return (
            metric("assets_reachable", "assets_reachable_now", "rpt_lat_kpi_assets_reachable", extra_note=note,
                   unset=not self.critical_set),
            metric("pivots", "pivots_now", "rpt_lat_kpi_pivots", extra_note=note),
            Kpi(key="new_detections", label=self.t("rpt_lat_kpi_new_detections"), value=detections_now,
                previous=detections_before, better="lower"),
            metric("cross_env", "cross_env_edges", "rpt_lat_kpi_cross_env", extra_note=note),
        )

    # ── sections ─────────────────────────────────────────────────────────────
    def exposure_section(self, exposure: Mapping[str, Any] | None,
                         snaps: Sequence[tuple[str, dict[str, Any]]]) -> Section:
        title = self.t("rpt_lat_sec_exposure")
        if exposure is None:
            return Section(id="exposure", title=title, blocks=(self.not_computed(title),))
        hosts = exposure.get("hosts") or ()
        rows = (
            (self.t("rpt_lat_row_hosts"), exposure.get("nodes"), exposure.get("nodes")),
            (self.t("rpt_lat_row_edges"), exposure.get("edges_now"), exposure.get("edges_enforced")),
            (self.t("rpt_lat_row_pivots"), sum(1 for h in hosts if h.get("pivot_now")),
             sum(1 for h in hosts if h.get("pivot_enforced"))),
            (self.t("rpt_lat_row_max_reach"), max((h.get("reach_now", 0) for h in hosts), default=0),
             max((h.get("reach_enforced", 0) for h in hosts), default=0)),
        )
        table = TableBlock(title=self.t("rpt_lat_tbl_now_vs_enforced"), columns=(
            Column(key="metric", label=self.t("rpt_col_metric")),
            Column(key="now", label=self.t("rpt_col_now"), kind="number"),
            Column(key="enforced", label=self.t("rpt_col_enforced"), kind="number")),
            rows=rows, total_rows=len(rows), empty_text="")
        in_period = [(d, m) for d, m in snaps if db_day(self.inp.start) <= d]
        trend = BarBlock(title=self.t("rpt_lat_trend_edges"),
                         points=tuple((d[5:], m.get("edges_now")) for d, m in in_period),
                         empty_text=self.t("rpt_lat_trend_none"))
        intro = self.t("rpt_lat_exposure_intro", hops=exposure.get("hops"),
                       days=(datetime.fromisoformat(exposure["observation_to"])
                             - datetime.fromisoformat(exposure["observation_from"])).days)
        return Section(id="exposure", title=title, intro=intro, blocks=(table, trend))

    def assets_section(self, exposure: Mapping[str, Any] | None) -> Section:
        title = self.t("rpt_lat_sec_assets")
        if exposure is None:
            return Section(id="assets", title=title, blocks=(self.not_computed(title),))
        rows = []
        for a in sorted(exposure.get("assets") or (), key=lambda a: (-a.get("sources_now", 0), a["key"])):
            path = min(a.get("paths") or [[]], key=len)
            cuts = "; ".join(self.t("rpt_lat_cut_edge" if c["kind"] == "edge" else "rpt_lat_cut_node",
                                    src=self.name(c["src"]), dst=self.name(c.get("dst") or ""),
                                    ports=ports_text(c.get("ports")), asset=self.name(a["key"]),
                                    before=c["before"], after=c["after"]) for c in a.get("cuts") or ())
            rows.append((self.name(a["key"]), a.get("sources_now"), a.get("sources_enforced"),
                         " → ".join(self.name(k) for k in path), cuts or self.t("rpt_lat_no_cut")))
        empty = self.t("rpt_lat_assets_none" if self.critical_set else "rpt_lat_no_critical_assets")
        table = TableBlock(title=title, columns=(
            Column(key="asset", label=self.t("rpt_col_asset"), kind="host"),
            Column(key="now", label=self.t("rpt_col_sources_now"), kind="number"),
            Column(key="enforced", label=self.t("rpt_col_sources_enforced"), kind="number"),
            Column(key="path", label=self.t("rpt_col_shortest_path")),
            Column(key="cut", label=self.t("rpt_col_suggested_cut"))),
            rows=tuple(rows), total_rows=len(rows), empty_text=empty)
        return Section(id="assets", title=title, intro=self.t("rpt_lat_assets_intro"), blocks=(table,))

    def reach_section(self, exposure: Mapping[str, Any] | None) -> Section:
        title = self.t("rpt_lat_sec_reach")
        if exposure is None:
            return Section(id="reach", title=title, blocks=(self.not_computed(title),))
        hosts = sorted(exposure.get("hosts") or (), key=lambda h: (-h.get("reach_now", 0), h["key"]))
        shown = [h for h in hosts if h.get("reach_now")]
        rows = tuple((self.name(h["key"]), h.get("reach_now"), h.get("reach_enforced"),
                      self.t("rpt_yes") if h.get("pivot_now") else "") for h in shown[:REACH_ROWS])
        table = TableBlock(title=title, columns=(
            Column(key="host", label=self.t("rpt_col_host"), kind="host"),
            Column(key="now", label=self.t("rpt_col_reach_now"), kind="number"),
            Column(key="enforced", label=self.t("rpt_col_reach_enforced"), kind="number"),
            Column(key="pivot", label=self.t("rpt_col_pivot"))),
            rows=rows, total_rows=len(shown), empty_text=self.t("rpt_lat_reach_none"),
            limit_note=self.t("rpt_limit_top", shown=len(rows), total=len(shown)) if len(shown) > len(rows) else None)
        return Section(id="reach", title=title, intro=self.t("rpt_lat_reach_intro", hops=exposure.get("hops")),
                       blocks=(table,))

    def pivots_section(self, exposure: Mapping[str, Any] | None) -> Section:
        title = self.t("rpt_lat_sec_pivots")
        if exposure is None:
            return Section(id="pivots", title=title, blocks=(self.not_computed(title),))
        pivots = sorted((h for h in exposure.get("hosts") or () if h.get("pivot_now")),
                        key=lambda h: (-h.get("reach_now", 0), h["key"]))
        rows = tuple((self.name(h["key"]), h.get("reach_now"),
                      self.t("rpt_yes") if h.get("pivot_enforced") else self.t("rpt_no")) for h in pivots)
        table = TableBlock(title=title, columns=(
            Column(key="host", label=self.t("rpt_col_host"), kind="host"),
            Column(key="now", label=self.t("rpt_col_reach_now"), kind="number"),
            Column(key="enforced", label=self.t("rpt_col_pivot_after_enforcement"))),
            rows=rows, total_rows=len(rows), empty_text=self.t("rpt_lat_pivots_none"))
        return Section(id="pivots", title=title, intro=self.t("rpt_lat_pivots_intro"), blocks=(table,))

    def detections_section(self, counts: Mapping[str, tuple[int, int]], rows: Sequence[Any], total: int) -> Section:
        title = self.t("rpt_lat_sec_detections")
        by = sorted(counts.items(), key=lambda kv: (-kv[1][0], kv[0]))
        count_table = TableBlock(title=self.t("rpt_lat_tbl_by_detector"), columns=(
            Column(key="detector", label=self.t("rpt_col_detector")),
            Column(key="count", label=self.t("rpt_col_count"), kind="number"),
            Column(key="high", label=self.t("rpt_col_high_or_critical"), kind="number")),
            rows=tuple((detector_name(self.lang, d), n, int(h or 0)) for d, (n, h) in by), total_rows=len(by),
            empty_text=self.t("rpt_lat_detections_none"))
        detail = TableBlock(title=self.t("rpt_lat_tbl_detections"), columns=(
            Column(key="severity", label=self.t("rpt_col_severity")),
            Column(key="detector", label=self.t("rpt_col_detector")),
            Column(key="subject", label=self.t("rpt_col_subject"), kind="host"),
            Column(key="first", label=self.t("rpt_col_first_seen"), kind="time"),
            Column(key="last", label=self.t("rpt_col_last_seen"), kind="time"),
            Column(key="occurrences", label=self.t("rpt_col_occurrences"), kind="number"),
            Column(key="late", label=self.t("rpt_col_late")),
            Column(key="critical", label=self.t("rpt_col_critical_asset"))),
            rows=tuple((severity_name(self.lang, r["severity"]), detector_name(self.lang, r["detector"]),
                        self.name(r["subject_key"]), r["first_seen"], r["last_seen"], r["occurrences"],
                        self.t("rpt_yes") if r["late"] else "", self.t("rpt_yes") if r["critical_asset"] else "")
                       for r in rows),
            total_rows=total, empty_text=self.t("rpt_lat_detections_none"),
            limit_note=self.t("rpt_limit_top", shown=len(rows), total=total) if total > len(rows) else None)
        return Section(id="detections", title=title, intro=self.t("rpt_lat_detections_intro"),
                       blocks=(count_table, detail))

    def cross_env_section(self, exposure: Mapping[str, Any] | None) -> Section:
        title = self.t("rpt_lat_sec_cross_env")
        if exposure is None:
            return Section(id="cross_env", title=title, blocks=(self.not_computed(title),))
        edges = exposure.get("cross_env") or ()
        total = int(exposure.get("cross_env_total") or len(edges))
        rows = tuple((self.name(e["src"]), e.get("src_env"), self.name(e["dst"]), e.get("dst_env"),
                      ports_text(e.get("ports")), self.t(EDGE_STATE_KEYS.get(e.get("state", ""), "decision_unknown")))
                     for e in edges)
        table = TableBlock(title=title, columns=(
            Column(key="src", label=self.t("rpt_col_source"), kind="host"),
            Column(key="src_env", label=self.t("rpt_col_source_env")),
            Column(key="dst", label=self.t("rpt_col_destination"), kind="host"),
            Column(key="dst_env", label=self.t("rpt_col_destination_env")),
            Column(key="ports", label=self.t("rpt_col_ports")),
            Column(key="state", label=self.t("rpt_col_decision"))),
            rows=rows, total_rows=max(total, len(rows)), empty_text=self.t("rpt_lat_cross_env_none"),
            limit_note=self.t("rpt_limit_top", shown=len(rows), total=total) if total > len(rows) else None)
        return Section(id="cross_env", title=title,
                       intro=self.t("rpt_lat_cross_env_intro", key=self.lc.settings.environment_label_key),
                       blocks=(table,))

    def directory_section(self) -> Section:
        inp, lc = self.inp, self.lc
        title = self.t("rpt_lat_sec_directory")
        ds = directory_servers(inp.ctx, lc, lc.admin_ports, since=inp.start)
        servers: list[tuple[str, int | None, str]] = []
        for key in sorted(ds.servers, key=self.name):
            basis = ("rpt_lat_dir_both" if key in ds.inferred and key in ds.declared
                     else "rpt_lat_dir_inferred" if key in ds.inferred else "rpt_lat_dir_declared")
            servers.append((self.name(key), ds.sources.get(key, 0), self.t(basis)))
        servers += [(ip, None, self.t("rpt_lat_dir_declared_ip")) for ip in sorted(ds.ips)]
        server_table = TableBlock(title=self.t("rpt_lat_tbl_directory_servers"), columns=(
            Column(key="server", label=self.t("rpt_col_server"), kind="host"),
            Column(key="sources", label=self.t("rpt_col_sources_in_period"), kind="number"),
            Column(key="basis", label=self.t("rpt_col_basis"))),
            rows=tuple(servers), total_rows=len(servers), empty_text=self.t("rpt_lat_dir_none"))
        prev_start, _ = previous_period(inp.start, inp.end, inp.tz)
        prev_known = traffic_covered(inp.ctx, prev_start, inp.start, now=inp.now)
        with reads.reading(inp.ctx) as conn:
            dets, det_total = analysis.detections_first_seen_between(conn, inp.start, inp.end, limit=DETECTION_ROWS)
            days = reads.utc_days(inp.start, inp.end)
            prev_days = reads.utc_days(prev_start, inp.start)
            top = reads.rollup_sources_on_ports(conn, days, ds.ports, limit=DIRECTORY_SOURCES) if ds.ports else []
            prev = reads.rollup_connections_of(conn, prev_days, ds.ports, [s for s, _ in top]) if ds.ports else {}
        directory_ports = {p for p, _ in ds.ports}
        relevant = [r for r in dets if r["detector"] in DIRECTORY_DETECTORS
                    or (r["detector"] == "suspicious_tool"
                        and json.loads(r["summary_json"]).get("port") in directory_ports)]
        det_table = TableBlock(title=self.t("rpt_lat_tbl_directory_detections"), columns=(
            Column(key="detector", label=self.t("rpt_col_detector")),
            Column(key="subject", label=self.t("rpt_col_subject"), kind="host"),
            Column(key="detail", label=self.t("rpt_col_detail")),
            Column(key="first", label=self.t("rpt_col_first_seen"), kind="time")),
            rows=tuple((detector_name(self.lang, r["detector"]), self.name(r["subject_key"]),
                        self._detail(json.loads(r["summary_json"])), r["first_seen"]) for r in relevant),
            total_rows=len(relevant), empty_text=self.t("rpt_lat_dir_detections_none"),
            limit_note=self.t("rpt_limit_detections_read", n=DETECTION_ROWS, total=det_total)
            if det_total > len(dets) else None)
        source_rows: list[tuple[str, int, int | None, str]] = []
        for src, n in top:
            if not prev_known:  # the previous period was not (fully) collected: nothing to compare with
                source_rows.append((self.name(src), n, None, self.t("rpt_kpi_no_previous")))
                continue
            before = prev.get(src, 0)
            change = self.t("rpt_lat_dir_prev_none") if before == 0 else self.t("rpt_lat_dir_times",
                                                                                 x=f"{n / before:.1f}")
            source_rows.append((self.name(src), n, before, change))
        source_table = TableBlock(title=self.t("rpt_lat_tbl_directory_sources"), columns=(
            Column(key="source", label=self.t("rpt_col_source"), kind="host"),
            Column(key="now", label=self.t("rpt_col_connections"), kind="number"),
            Column(key="before", label=self.t("rpt_col_connections_previous"), kind="number"),
            Column(key="change", label=self.t("rpt_col_change"))),
            rows=tuple(source_rows), total_rows=len(source_rows), empty_text=self.t("rpt_lat_dir_sources_none"),
            limit_note=self.t("rpt_lat_dir_sources_top", n=DIRECTORY_SOURCES)
            if len(source_rows) == DIRECTORY_SOURCES else None)
        intro = self.t("rpt_lat_directory_intro", ports=", ".join(port_text(p, q or 6) for p, q in ds.ports))
        return Section(id="directory", title=title, intro=intro, blocks=(server_table, det_table, source_table))

    def _detail(self, summary: Mapping[str, Any]) -> str:
        parts = []
        if summary.get("target"):
            parts.append(self.t("rpt_detail_target", target=summary["target"]))
        if summary.get("port") is not None:
            parts.append(self.t("rpt_detail_port", port=summary["port"]))
        if summary.get("process"):
            parts.append(self.t("rpt_detail_process", process=summary["process"]))
        if summary.get("connections") is not None:
            parts.append(self.t("rpt_detail_connections", n=summary["connections"]))
        return "; ".join(parts)

    def quality(self, exposure_row: Any) -> tuple[str, ...]:
        inp, lc = self.inp, self.lc
        lines = list(coverage_note(inp.ctx, inp.start, inp.end, self.lang, now=inp.now, tz=inp.tz))
        lines.append(self.t("rpt_quality_utc_days"))
        if exposure_row is None:
            lines.append(self.t("rpt_lat_not_computed"))
        else:
            computed = datetime.fromisoformat(exposure_row["computed_at"])
            age_hours = (inp.now - computed).total_seconds() / 3600
            if inp.now - computed > STALE_AFTER:
                lines.append(self.t("rpt_lat_exposure_stale", hours=f"{age_hours:.0f}"))
            result = json.loads(exposure_row["result_json"])
            if result.get("unknown_edges"):
                lines.append(self.t("rpt_lat_unknown_edges", n=result["unknown_edges"]))
            if result.get("limits_hit"):
                lines.append(self.t("rpt_lat_limits_hit", what=", ".join(result["limits_hit"])))
        if not lc.baseline_full():
            lines.append(self.t("rpt_lat_baseline_accumulating", days=f"{lc.baseline_days:.0f}",
                                required=lc.baseline_required))
        return tuple(lines)


def build_lateral_posture(inp: BuildInput) -> ReportDocument:
    b = _Builder(inp)
    period = inp.end - inp.start
    with reads.reading(inp.ctx) as conn:
        exposure_row = analysis.read_result(conn, "exposure")
        focus_row = analysis.read_result(conn, "focus")
        snaps = analysis.lateral_snapshots(conn, db_day(inp.start - period - timedelta(days=1)),
                                           db_day(inp.end - timedelta(microseconds=1)))
        counts = analysis.detection_counts(conn, inp.start, inp.end)
        before = sum(n for n, _ in analysis.detection_counts(
            conn, previous_period(inp.start, inp.end, inp.tz)[0], inp.start).values())
        rows, total = analysis.detections_first_seen_between(conn, inp.start, inp.end, limit=DETECTION_ROWS)
    prev_start, _ = previous_period(inp.start, inp.end, inp.tz)
    if not traffic_covered(inp.ctx, prev_start, inp.start, now=inp.now):
        before_count: int | None = None
    else:
        before_count = before
    exposure = json.loads(exposure_row["result_json"]) if exposure_row is not None else None
    focus = json.loads(focus_row["result_json"]) if focus_row is not None else None
    return ReportDocument(
        report_type=inp.params.report_type, lang=inp.lang, title=b.t("rpt_title_lateral_posture"),
        period_start=inp.start, period_end=inp.end, generated_at=inp.now, pce_label=inp.pce_label,
        kpis=b.kpis(exposure, snaps, sum(n for n, _ in counts.values()), before_count),
        findings=_findings(focus, inp.lang), data_quality=b.quality(exposure_row),
        sections=(b.exposure_section(exposure, snaps), b.assets_section(exposure), b.reach_section(exposure),
                  b.pivots_section(exposure), b.detections_section(counts, rows, total),
                  b.cross_env_section(exposure), b.directory_section()))

