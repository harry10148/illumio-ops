"""The period's stored detections and detection-category alert history; this report never queries the PCE."""
from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from illumio_ops.domain.alert_devices import devices_of_detection
from illumio_ops.domain.alertcategory import category_filter
from illumio_ops.domain.report import (
    BarBlock,
    Column,
    Kpi,
    ReportDocument,
    Section,
    TableBlock,
    TextBlock,
)
from illumio_ops.domain.values import (
    SEVERITY_ORDER,
    DeliveryStatus,
    DetectorKind,
    IngestSource,
    ReportType,
)
from illumio_ops.services.alerts.channels import scrub
from illumio_ops.services.analysis.context import load_lateral_context
from illumio_ops.services.collect.mode import collects
from illumio_ops.services.context import AppContext
from illumio_ops.services.reports.common import (
    detector_name,
    host_key,
    host_keys,
    host_name,
    severity_name,
    tr,
)
from illumio_ops.services.reports.reads import reading
from illumio_ops.services.reports.registry import BuildInput
from illumio_ops.services.reports.render_html import fmt_time
from illumio_ops.services.reports.weekly_overview import alerts_known_from
from illumio_ops.store import alerts as alert_store
from illumio_ops.store import detection_annotations
from illumio_ops.store.flowdb import analysis
from illumio_ops.store.flowdb.db import db_time

# The lateral-posture report uses 1,000 detections; keep the same ranked detail size here.
DETECTION_ROWS = 1000
TOP_HOSTS = 5
_DETECTION_CATEGORIES = ("lateral", "anomaly")
_SEVERITIES = tuple(reversed(SEVERITY_ORDER))
_DELIVERY_NOT_NOTIFIED = frozenset({DeliveryStatus.GROUPED.value, DeliveryStatus.NO_CHANNEL.value,
                                    DeliveryStatus.NOT_NOTIFIED.value})


def _host_rows(conn: sqlite3.Connection, start: datetime, end: datetime) -> list[sqlite3.Row]:
    return conn.execute("SELECT detector, fingerprint, subject_key, critical_asset FROM detections WHERE first_seen >= ? "
                        "AND first_seen < ?", (db_time(start), db_time(end))).fetchall()


def _marked(row: sqlite3.Row, marks: list[sqlite3.Row]) -> bool:
    return any(mark["detector"] == row["detector"] and
               (mark["fingerprint"] == row["fingerprint"] if mark["fingerprint"] is not None
                else mark["subject_key"] == row["subject_key"]) for mark in marks)


def _period_alerts(ctx: AppContext, pce_url: str, org_id: str, start: datetime,
                   end: datetime) -> list[sqlite3.Row]:
    out: list[sqlite3.Row] = []
    with ctx.db() as conn:
        for category_name in _DETECTION_CATEGORIES:
            types, inside, outside = category_filter(category_name)  # type: ignore[arg-type]
            out.extend(alert_store.period_alerts(conn, pce_url=pce_url, org_id=org_id, since=start, until=end,
                                                 rule_types=types, detectors_in=inside, detectors_not_in=outside))
    return out


def _deliveries(ctx: AppContext, alert_ids: list[int]) -> list[sqlite3.Row]:
    if not alert_ids:
        return []
    with ctx.db() as conn:
        return [row for i in range(0, len(alert_ids), 500)
                for row in alert_store.deliveries(conn, alert_ids[i:i + 500])]


def _local_day(at: str, tz: Any) -> date:
    return datetime.fromisoformat(at).astimezone(tz).date()


def build_detections(inp: BuildInput) -> ReportDocument:
    ctx, lang = inp.ctx, inp.lang
    settings = ctx.settings.current()
    pce = settings.pce
    detection_mode = collects(settings, IngestSource.TRAFFIC)
    lateral = load_lateral_context(ctx, now=inp.now)
    with reading(ctx) as conn:
        if detection_mode:
            kind_counts = analysis.detection_counts(conn, inp.start, inp.end)
            detection_rows, detection_total = analysis.detections_first_seen_between(
                conn, inp.start, inp.end, limit=DETECTION_ROWS)
            all_detection_rows = _host_rows(conn, inp.start, inp.end)
        else:
            kind_counts, detection_rows, detection_total, all_detection_rows = {}, [], 0, []
    with ctx.db() as conn:
        marks = detection_annotations.for_pce(conn, pce.url, pce.org_id)
    known_from = alerts_known_from(ctx, pce, inp.now)
    alerts = _period_alerts(ctx, pce.url, pce.org_id, inp.start, inp.end)
    deliveries = _deliveries(ctx, [int(a["id"]) for a in alerts])
    alerts_by_id = {int(a["id"]): a for a in alerts}
    deliveries_by_alert: dict[int, list[sqlite3.Row]] = defaultdict(list)
    for delivery in deliveries:
        deliveries_by_alert[int(delivery["alert_id"])].append(delivery)

    failed = [d for d in deliveries if d["status"] == DeliveryStatus.FAILED.value]
    known_alerts = sum(1 for a in alerts if a["grouped_annotation"] is not None)
    # All counters are delivery rows; pending is kept separate from a rule that does not notify.
    rule_stats: dict[str, dict[str, Any]] = {}
    for rule in settings.alerts.rules:
        if rule.type == "lateral":
            rule_stats[rule.id] = {"name": rule.name or tr(lang, rule.pack_key or ""), "fired": 0,
                                   "severity": Counter(), "known": 0, "sent": 0, "failed": 0,
                                   "not_notified": 0, "pending": 0}
    for alert in alerts:
        rid = str(alert["rule_id"])
        info = rule_stats.setdefault(rid, {"name": str(alert["rule_name"]), "fired": 0,
                                           "severity": Counter(), "known": 0, "sent": 0, "failed": 0,
                                           "not_notified": 0, "pending": 0})
        info["name"] = str(alert["rule_name"] or info["name"])
        info["fired"] += 1
        info["severity"][str(alert["severity"])] += 1
        info["known"] += int(alert["grouped_annotation"] is not None)
        for delivery in deliveries_by_alert[int(alert["id"])]:
            status = str(delivery["status"])
            if status in info:
                info[status] += 1
            elif status in _DELIVERY_NOT_NOTIFIED:
                info["not_notified"] += 1

    by_kind_hosts: dict[str, set[str]] = defaultdict(set)
    host_kinds: dict[str, Counter[str]] = defaultdict(Counter)
    for row in all_detection_rows:
        for device in devices_of_detection(str(row["fingerprint"])):
            by_kind_hosts[str(row["detector"])].add(device.key)
            host_kinds[device.key][str(row["detector"])] += 1
    all_kinds = [kind.value for kind in DetectorKind]
    empty_kinds = [kind for kind in all_kinds if kind_counts.get(kind, (0, 0))[0] == 0]
    by_kind = TableBlock(
        title=tr(lang, "rpt_det_tbl_by_kind"),
        columns=(Column(key="kind", label=tr(lang, "rpt_col_detector")),
                 Column(key="new", label=tr(lang, "rpt_det_col_new"), kind="number"),
                 Column(key="high_critical", label=tr(lang, "rpt_col_high_or_critical"), kind="number"),
                 Column(key="hosts", label=tr(lang, "rpt_det_col_hosts"), kind="number"),
                 Column(key="critical_assets", label=tr(lang, "rpt_det_col_critical_assets"), kind="number")),
        rows=tuple((detector_name(lang, kind), *kind_counts.get(kind, (0, 0)), len(by_kind_hosts[kind]),
                    sum(1 for row in all_detection_rows if row["detector"] == kind and row["critical_asset"]))
                   for kind in all_kinds),
        total_rows=len(all_kinds), empty_text=tr(lang, "rpt_det_none"))
    none_line = (TextBlock(paragraphs=(tr(lang, "rpt_det_no_kinds", kinds=tr(
        lang, "rpt_list_sep").join(detector_name(lang, kind) for kind in empty_kinds)),)) if empty_kinds else None)

    detection_table_rows = tuple(
        (severity_name(lang, str(row["severity"])), detector_name(lang, str(row["detector"])),
         host_name(lateral.hosts, str(row["subject_key"]), lang), row["first_seen"], row["last_seen"], row["occurrences"],
         tr(lang, "rpt_yes") if row["critical_asset"] else tr(lang, "rpt_no"),
         tr(lang, "rpt_yes") if _marked(row, marks) else tr(lang, "rpt_no"))
        for row in detection_rows)
    detail = TableBlock(
        title=tr(lang, "rpt_det_tbl_list"),
        columns=(Column(key="severity", label=tr(lang, "rpt_col_severity")),
                 Column(key="kind", label=tr(lang, "rpt_col_detector")),
                 Column(key="host", label=tr(lang, "rpt_col_host"), kind="host"),
                 Column(key="first", label=tr(lang, "rpt_col_first_seen"), kind="time"),
                 Column(key="last", label=tr(lang, "rpt_col_last_seen"), kind="time"),
                 Column(key="occurrences", label=tr(lang, "rpt_col_occurrences"), kind="number"),
                 Column(key="critical", label=tr(lang, "rpt_det_col_critical_assets")),
                 Column(key="known", label=tr(lang, "rpt_det_col_known"))),
        rows=detection_table_rows, total_rows=detection_total, empty_text=tr(lang, "rpt_det_none"),
        limit_note=tr(lang, "rpt_limit_top", shown=len(detection_rows), total=detection_total)
        if detection_total > len(detection_rows) else None,
        host_keys=host_keys(host=(host_key({}, str(row["subject_key"])) for row in detection_rows)),
        host_section="connections")

    host_ranked = sorted(host_kinds.items(), key=lambda item: (-sum(item[1].values()), item[0]))[:TOP_HOSTS]
    host_table = TableBlock(
        title=tr(lang, "rpt_det_tbl_hosts"),
        columns=(Column(key="host", label=tr(lang, "rpt_col_host"), kind="host"),
                 Column(key="detections", label=tr(lang, "rpt_col_count"), kind="number"),
                 Column(key="kinds", label=tr(lang, "rpt_col_detector"))),
        rows=tuple((host_name(lateral.hosts, key, lang), sum(kinds.values()), tr(lang, "rpt_list_sep").join(
            f"{detector_name(lang, kind)}: {count}" for kind, count in
            sorted(kinds.items(), key=lambda item: (-item[1], item[0])))) for key, kinds in host_ranked),
        total_rows=len(host_kinds), empty_text=tr(lang, "rpt_det_hosts_none"),
        limit_note=tr(lang, "rpt_limit_top", shown=len(host_ranked), total=len(host_kinds))
        if len(host_kinds) > len(host_ranked) else None,
        host_keys=host_keys(host=(host_key({}, key) for key, _ in host_ranked)), host_section="connections")

    alert_rows = []
    for rule_id, stats in sorted(rule_stats.items(), key=lambda item: (str(item[1]["name"]).casefold(), item[0])):
        severity_counts = stats["severity"]
        alert_rows.append((f"{stats['name']} ({rule_id})", stats["fired"],
                           *(severity_counts.get(s.value, 0) for s in _SEVERITIES), stats["known"],
                           stats["sent"], stats["failed"], stats["not_notified"], stats["pending"]))
    history = TableBlock(
        title=tr(lang, "rpt_det_tbl_rules"),
        columns=(Column(key="rule", label=tr(lang, "rpt_det_col_rule")),
                 Column(key="fired", label=tr(lang, "rpt_det_col_fired"), kind="number"),
                 *(Column(key=f"severity_{s.value}", label=severity_name(lang, s.value), kind="number")
                   for s in _SEVERITIES),
                 Column(key="known", label=tr(lang, "rpt_det_col_known"), kind="number"),
                 Column(key="sent", label=tr(lang, "rpt_det_col_sent"), kind="number"),
                 Column(key="failed", label=tr(lang, "rpt_det_col_failed"), kind="number"),
                 Column(key="not_notified", label=tr(lang, "rpt_det_col_not_notified"), kind="number"),
                 Column(key="pending", label=tr(lang, "rpt_det_col_pending"), kind="number")),
        rows=tuple(alert_rows), total_rows=len(alert_rows), empty_text=tr(lang, "rpt_det_rules_none"))

    local_start = inp.start.astimezone(inp.tz).date()
    local_end = inp.end.astimezone(inp.tz).date()
    by_day = Counter(_local_day(str(a["fired_at"]), inp.tz) for a in alerts)
    days = []
    day = local_start
    while day < local_end:
        days.append((day.isoformat(), by_day.get(day, 0)))
        day += timedelta(days=1)
    day_spread = BarBlock(title=tr(lang, "rpt_det_chart_days"), points=tuple(days),
                          empty_text=tr(lang, "rpt_det_alerts_none"))

    channel_settings = settings.alerts.channels
    failed_rows = []
    for delivery in sorted(failed, key=lambda row: (str(alerts_by_id[int(row["alert_id"])]["fired_at"]),
                                                    int(row["alert_id"]), str(row["channel"])), reverse=True):
        alert = alerts_by_id[int(delivery["alert_id"])]
        error = scrub(str(delivery["last_error"] or ""), channel_settings)
        failed_rows.append((fmt_time(str(alert["fired_at"]), inp.tz), str(alert["rule_name"]),
                            severity_name(lang, str(alert["severity"])), str(delivery["channel"]),
                            int(delivery["attempts"]), error))
    failed_table = TableBlock(
        title=tr(lang, "rpt_det_tbl_failed"),
        columns=(Column(key="fired", label=tr(lang, "rpt_det_col_fired_at")),
                 Column(key="rule", label=tr(lang, "rpt_det_col_rule")),
                 Column(key="severity", label=tr(lang, "rpt_col_severity")),
                 Column(key="channel", label=tr(lang, "rpt_det_col_channel")),
                 Column(key="attempts", label=tr(lang, "rpt_det_col_attempts"), kind="number"),
                 Column(key="error", label=tr(lang, "rpt_det_col_last_error"))),
        rows=tuple(failed_rows), total_rows=len(failed_rows), empty_text=tr(lang, "rpt_det_failed_none"))

    limits = [tr(lang, "rpt_det_limits_suppressed")]
    if not detection_mode:
        limits.insert(0, tr(lang, "lat_detections_need_mode"))
    if known_from is None:
        limits.append(tr(lang, "rpt_det_alert_floor_unknown"))
    elif inp.start < known_from:
        limits.append(tr(lang, "rpt_det_alert_floor_partial", since=fmt_time(known_from.isoformat(), inp.tz)))

    total_detections = sum(n for n, _ in kind_counts.values())
    high_critical = sum(high for _, high in kind_counts.values())
    kpis = (
        Kpi(key="new_detections", label=tr(lang, "rpt_det_kpi_new"), value=total_detections, previous=None),
        Kpi(key="high_critical_detections", label=tr(lang, "rpt_det_kpi_high_critical"), value=high_critical,
            previous=None),
        Kpi(key="detection_alerts", label=tr(lang, "rpt_det_kpi_alerts"), value=len(alerts), previous=None),
        Kpi(key="failed_deliveries", label=tr(lang, "rpt_det_kpi_failed"), value=len(failed), previous=None),
        Kpi(key="known_alerts", label=tr(lang, "rpt_det_kpi_known"), value=known_alerts, previous=None),
    )
    if not detection_mode:
        kpis = (kpis[0].model_copy(update={"value": None, "note": tr(lang, "lat_detections_need_mode")}),
                kpis[1].model_copy(update={"value": None, "note": tr(lang, "lat_detections_need_mode")}), *kpis[2:])

    return ReportDocument(
        report_type=ReportType.DETECTIONS, lang=lang, title=tr(lang, "rpt_title_detections"),
        period_start=inp.start, period_end=inp.end, generated_at=inp.now, pce_label=inp.pce_label, kpis=kpis,
        findings=(), data_quality=tuple(limits),
        sections=(
            Section(id="by_kind", title=tr(lang, "rpt_det_sec_by_kind"), blocks=tuple(
                b for b in (none_line, by_kind) if b is not None)),
            Section(id="detection_list", title=tr(lang, "rpt_det_sec_list"), blocks=(detail,)),
            Section(id="hosts", title=tr(lang, "rpt_det_sec_hosts"), blocks=(host_table,)),
            Section(id="alert_history", title=tr(lang, "rpt_det_sec_alerts"),
                    blocks=(history, day_spread, TextBlock(paragraphs=(tr(lang, "rpt_det_delivery_unit"),)))),
            Section(id="failed_deliveries", title=tr(lang, "rpt_det_sec_failed"), blocks=(failed_table,)),
            Section(id="data_limits", title=tr(lang, "rpt_det_sec_limits"), blocks=(TextBlock(paragraphs=tuple(limits)),)),
        ))
