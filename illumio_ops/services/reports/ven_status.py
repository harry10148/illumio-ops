"""The VEN status report (spec §6.5 報表, §6.5.5 營運: ven_status with tampering and its known causes): which VENs
are online, which went quiet and when, which do not have their policy, what versions, systems and modes the fleet
runs, and which hosts show tampering no known cause explains. From the current inventory; one definition each for
online, version, operating system and mode (5.x had two of each)."""
from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from illumio_ops.domain.report import (
    Column,
    Kpi,
    ReportDocument,
    Section,
    TableBlock,
    TextBlock,
)
from illumio_ops.services.analysis.context import load_lateral_context
from illumio_ops.services.analysis.tamper import list_annotations
from illumio_ops.services.reports import reads
from illumio_ops.services.reports.common import tr
from illumio_ops.services.reports.history import previous_values
from illumio_ops.services.reports.registry import BuildInput
from illumio_ops.services.reports.render_html import fmt_time
from illumio_ops.store.flowdb import analysis, labels, workloads
from illumio_ops.store.flowdb.workloads import WorkloadRow

ONLINE_WITHIN = timedelta(hours=1)
DAY = timedelta(hours=24)
IN_SYNC = frozenset({"applied", "synced"})
MODES = ("full", "selective", "visibility_only", "idle")
_KPI_KEYS = {"managed": "rpt_ven_kpi_managed", "online": "rpt_ven_kpi_online", "lost_24h": "rpt_ven_kpi_lost_24h",
             "lost_48h": "rpt_ven_kpi_lost_48h", "long_offline": "rpt_ven_kpi_long_offline",
             "status_unknown": "rpt_ven_kpi_status_unknown", "sync_problems": "rpt_ven_kpi_sync_problems",
             "unexplained_tamper": "rpt_ven_kpi_unexplained_tamper"}
_BUCKET_KEYS = {"lost_24h": "rpt_ven_bucket_24h", "lost_48h": "rpt_ven_bucket_48h",
                "long_offline": "rpt_ven_bucket_long"}
_PROBLEM_KEYS = {"sync_state": "rpt_ven_problem_sync_state", "fw_stale": "rpt_ven_problem_fw_stale",
                 "behind": "rpt_ven_problem_behind", "never_applied": "rpt_ven_problem_never_applied",
                 "health": "rpt_ven_problem_health"}


def _when(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def bucket(w: WorkloadRow, now: datetime) -> str:
    """online, lost_24h, lost_48h, long_offline, or unknown (no heartbeat reported: never counted as offline)."""
    beat = _when(w.last_heartbeat_at)
    if beat is None:
        return "unknown"
    age = now - beat
    if w.online == 1 and age <= ONLINE_WITHIN:
        return "online"
    return "lost_24h" if age <= DAY else "lost_48h" if age <= 2 * DAY else "long_offline"


def problems(w: WorkloadRow) -> list[str]:
    """Policy sync problems of an online VEN; fields it did not report are not held against it."""
    out = []
    if w.policy_sync_state is not None and w.policy_sync_state not in IN_SYNC:
        out.append("sync_state")
    if w.fw_config_current == 0:
        out.append("fw_stale")
    received, applied = _when(w.policy_received_at), _when(w.policy_applied_at)
    if w.agent_status is not None and applied is None:
        out.append("never_applied")
    elif received is not None and applied is not None and received > applied:
        out.append("behind")
    health: Any = json.loads(w.agent_health_json) if w.agent_health_json else []
    if any(isinstance(h, Mapping) and str(h.get("severity", "")).lower() in ("error", "warning") for h in health):
        out.append("health")
    return out


def build_ven_status(inp: BuildInput) -> ReportDocument:
    lang, now = inp.lang, inp.now

    def t(msg: str, /, **params: object) -> str:
        return tr(lang, msg, **params)

    lc = load_lateral_context(inp.ctx, now=now)
    env_key = lc.settings.environment_label_key
    with reads.reading(inp.ctx) as conn:
        fleet = [w for w in workloads.all_workloads(conn) if w.managed]
        sets = labels.label_sets(conn, {w.label_set for w in fleet if w.label_set is not None})
        tamper_row = analysis.read_result(conn, "tamper")
        computed_at, run_error = reads.analysis_state(conn, "tamper")
    name = {w.href: w.hostname or w.href.rsplit("/", 1)[-1] for w in fleet}
    buckets = {w.href: bucket(w, now) for w in fleet}
    counts = Counter(buckets.values())
    trouble = {w.href: problems(w) for w in fleet if buckets[w.href] == "online"}
    trouble = {h: p for h, p in trouble.items() if p}
    tamper = json.loads(tamper_row["result_json"]) if tamper_row is not None else None
    tamper_hosts = list((tamper or {}).get("hosts") or ())
    unexplained = sum(1 for h in tamper_hosts if int(h.get("unexplained_7d") or 0) > 0)
    values: dict[str, int | None] = {
        "managed": len(fleet), "online": counts["online"], "lost_24h": counts["lost_24h"],
        "lost_48h": counts["lost_48h"], "long_offline": counts["long_offline"], "status_unknown": counts["unknown"],
        "sync_problems": len(trouble), "unexplained_tamper": unexplained if tamper is not None else None}
    before = previous_values(inp)
    kpis = tuple(Kpi(key=k, label=t(label), value=values[k], previous=(before or {}).get(k),
                     better="higher" if k in ("managed", "online") else "lower",
                     note=t("rpt_lat_not_computed") if values[k] is None else None) for k, label in _KPI_KEYS.items())

    def stamp(value: str | None) -> str | None:
        return value or None  # time columns: the renderers show it in the display zone; missing stays blank
    offline = sorted((w for w in fleet if buckets[w.href] in _BUCKET_KEYS),
                     key=lambda w: w.last_heartbeat_at or "", reverse=True)
    offline_table = TableBlock(
        title=t("rpt_ven_tbl_offline"),
        columns=(Column(key="host", label=t("rpt_col_host")), Column(key="bucket", label=t("rpt_ven_col_bucket")),
                 Column(key="heartbeat", label=t("rpt_ven_col_heartbeat"), kind="time"),
                 Column(key="sync", label=t("rpt_ven_col_sync")), Column(key="version", label=t("rpt_ven_col_version"))),
        rows=tuple((name[w.href], t(_BUCKET_KEYS[buckets[w.href]]), stamp(w.last_heartbeat_at),
                    w.policy_sync_state or "—", w.ven_version or "—") for w in offline),
        total_rows=len(offline), empty_text=t("rpt_ven_none_offline"))
    by_href = {w.href: w for w in fleet}
    sync_rows = sorted(trouble.items(), key=lambda kv: name[kv[0]])
    sync_table = TableBlock(
        title=t("rpt_ven_tbl_sync"),
        columns=(Column(key="host", label=t("rpt_col_host")), Column(key="problems", label=t("rpt_ven_col_problems")),
                 Column(key="sync", label=t("rpt_ven_col_sync")),
                 Column(key="received", label=t("rpt_ven_col_received"), kind="time"),
                 Column(key="applied", label=t("rpt_ven_col_applied"), kind="time")),
        rows=tuple((name[h], ", ".join(t(_PROBLEM_KEYS[p]) for p in ps), by_href[h].policy_sync_state or "—",
                    stamp(by_href[h].policy_received_at), stamp(by_href[h].policy_applied_at)) for h, ps in sync_rows),
        total_rows=len(sync_rows), empty_text=t("rpt_ven_none_sync"))

    def tally(title: str, label: str, keyfn: Any) -> TableBlock:
        c = Counter(keyfn(w) or t("rpt_ven_unknown") for w in fleet)
        rows = tuple(sorted(c.items(), key=lambda kv: (-kv[1], kv[0])))
        return TableBlock(title=title, columns=(Column(key="k", label=label),
                                                Column(key="n", label=t("rpt_col_managed_hosts"), kind="number")),
                          rows=rows, total_rows=len(rows), empty_text=t("rpt_ven_none_hosts"))
    versions = tally(t("rpt_ven_tbl_versions"), t("rpt_ven_col_version"), lambda w: w.ven_version)
    systems = tally(t("rpt_ven_tbl_os"), t("rpt_ven_col_os"), lambda w: w.os_id)

    no_label = t("rpt_no_label")
    groups: dict[str, Counter[str]] = {}
    for w in fleet:
        lab = sets.get(w.label_set, {}) if w.label_set is not None else {}
        g = f"{lab.get('app') or no_label} ({lab.get(env_key) or no_label})"
        groups.setdefault(g, Counter())[w.enforcement_mode if w.enforcement_mode in MODES else "unknown"] += 1

    def pct(n: int, d: int) -> str:
        return f"{100 * n / d:.1f}%" if d else "—"
    ordered = sorted(groups.items(), key=lambda kv: (-sum(kv[1].values()), kv[0]))
    modes = TableBlock(
        title=t("rpt_sec_tbl_enforcement"),
        columns=(Column(key="app", label=t("rpt_col_app_env")),
                 Column(key="hosts", label=t("rpt_col_managed_hosts"), kind="number"),
                 Column(key="full", label=t("rpt_col_mode_full"), kind="number"),
                 Column(key="selective", label=t("rpt_col_mode_selective"), kind="number"),
                 Column(key="visibility_only", label=t("rpt_col_mode_visibility"), kind="number"),
                 Column(key="idle", label=t("rpt_col_mode_idle"), kind="number"),
                 Column(key="unknown", label=t("rpt_ven_unknown"), kind="number"),
                 Column(key="enforced", label=t("rpt_col_enforced_pct"))),
        rows=tuple((g, sum(c.values()), *(c[m] for m in MODES), c["unknown"],
                    pct(c["full"] + c["selective"], sum(c.values()))) for g, c in ordered),
        total_rows=len(ordered), empty_text=t("rpt_ven_none_hosts"))

    tamper_blocks: tuple[TableBlock | TextBlock, ...]
    if tamper is None:
        tamper_blocks = (TextBlock(paragraphs=(t("rpt_ven_tamper_not_computed"),)),)
    else:
        notes = list_annotations(inp.ctx)
        tamper_blocks = (TableBlock(
            title=t("rpt_ven_tbl_tamper"),
            columns=(Column(key="host", label=t("rpt_col_host")),
                     Column(key="n60", label=t("rpt_ven_col_tamper_60d"), kind="number"),
                     Column(key="n7", label=t("rpt_ven_col_tamper_7d"), kind="number"),
                     Column(key="unexplained", label=t("rpt_ven_col_unexplained"), kind="number"),
                     Column(key="pattern", label=t("rpt_ven_col_pattern")),
                     Column(key="last", label=t("rpt_ven_col_last"), kind="time")),
            rows=tuple((h.get("hostname") or name.get(str(h.get("href")), str(h.get("href"))), int(h.get("n_60d") or 0),
                        int(h.get("n_7d") or 0), int(h.get("unexplained_7d") or 0), str(h.get("pattern") or "—"),
                        stamp(h.get("last_at"))) for h in tamper_hosts),
            total_rows=len(tamper_hosts), empty_text=t("rpt_ven_none_tamper")),
            TextBlock(paragraphs=(t("rpt_ven_tamper_known", n=len(notes)),)))

    latest = max((w.fetched_at for w in fleet), default=None)
    quality = [t("rpt_ven_quality_inventory", at=fmt_time(latest, inp.tz)) if latest else t("rpt_ven_quality_no_inventory"),
               t("rpt_ven_quality_online")]
    if computed_at:
        quality.append(t("rpt_quality_analysis_at", at=fmt_time(computed_at, inp.tz)))
    if run_error:
        quality.append(t("rpt_quality_analysis_failed", error=run_error[:200]))
    if counts["unknown"]:
        quality.append(t("rpt_ven_quality_unknown", n=counts["unknown"]))
    return ReportDocument(
        report_type=inp.params.report_type, lang=lang, title=t("rpt_title_ven_status"), period_start=inp.start,
        period_end=inp.end, generated_at=now, pce_label=inp.pce_label, kpis=kpis, findings=(),
        data_quality=tuple(quality),
        sections=(Section(id="offline", title=t("rpt_ven_sec_offline"), intro=t("rpt_ven_offline_intro"),
                          blocks=(offline_table,)),
                  Section(id="sync", title=t("rpt_ven_sec_sync"), intro=t("rpt_ven_sync_intro"), blocks=(sync_table,)),
                  Section(id="versions", title=t("rpt_ven_sec_versions"), blocks=(versions, systems)),
                  Section(id="modes", title=t("rpt_sec_sec_enforcement"), blocks=(modes,)),
                  Section(id="tamper", title=t("rpt_ven_sec_tamper"), intro=t("rpt_ven_tamper_intro"),
                          blocks=tamper_blocks)))
