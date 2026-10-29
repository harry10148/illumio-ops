"""The ransomware protection report (spec §6.5.6): the PCE's own judgement — services, severities, protection states,
exposure — with the three action lists the traffic overlay gives (fix first, block now, suspicious), each host's
score taken apart, the allow rules behind the deductions, and the trend from the daily snapshots. A host whose PCE
score contradicts its own services is flagged and left out of the ranking."""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Any

from loguru import logger

from illumio_ops.domain.report import (
    BarBlock,
    Column,
    Finding,
    Kpi,
    ReportDocument,
    Section,
    TableBlock,
    TextBlock,
)
from illumio_ops.domain.values import Severity
from illumio_ops.services.analysis.ransomware import host_ransomware
from illumio_ops.services.reports import reads
from illumio_ops.services.reports.common import port_text, severity_name, tr
from illumio_ops.services.reports.generate import previous_period
from illumio_ops.services.reports.history import previous_values
from illumio_ops.services.reports.registry import BuildInput
from illumio_ops.services.reports.render_html import fmt_time
from illumio_ops.store.flowdb import analysis, ransomware
from illumio_ops.store.flowdb.db import db_day

LIST_ROWS = 100
ALLOW_HOSTS = 20  # hosts of the fix-first list whose allow rules are looked up (one Rule Search per service)
_KPI_KEYS = {"rated_hosts": "rpt_rw_kpi_rated_hosts", "org_percent": "rpt_rw_kpi_org_percent",
             "priority": "rpt_rw_kpi_priority", "safe_to_block": "rpt_rw_kpi_safe", "suspicious": "rpt_rw_kpi_suspicious",
             "contradictions": "rpt_rw_kpi_contradictions"}
_LISTS = (("priority", "priority", "rpt_rw_sec_priority", "rpt_rw_priority_intro", "rpt_rw_none_priority"),
          ("safe", "safe_to_block", "rpt_rw_sec_safe", "rpt_rw_safe_intro", "rpt_rw_none_safe"),
          ("suspicious", "suspicious", "rpt_rw_sec_suspicious", "rpt_rw_suspicious_intro", "rpt_rw_none_suspicious"))
_STATUS_KEYS = {"error": "rpt_rw_allow_error", "partial": "rpt_rw_allow_partial"}
# "How to read this report": (term, what it means, what to do with it)
_TERMS = (("rpt_rw_col_pce_percent", "rpt_rw_term_pce_means", "rpt_rw_term_pce_use"),
          ("rpt_rw_col_computed", "rpt_rw_term_computed_means", "rpt_rw_term_computed_use"),
          ("rpt_rw_col_exposure", "rpt_rw_term_exposure_means", "rpt_rw_term_exposure_use"),
          ("rpt_rw_col_contradiction", "rpt_rw_term_contradiction_means", "rpt_rw_term_contradiction_use"),
          ("rpt_rw_col_state", "rpt_rw_term_state_means", "rpt_rw_term_state_use"),
          ("rpt_rw_sec_priority", "rpt_rw_priority_intro", "rpt_rw_term_priority_use"),
          ("rpt_rw_sec_safe", "rpt_rw_safe_intro", "rpt_rw_term_safe_use"),
          ("rpt_rw_sec_suspicious", "rpt_rw_suspicious_intro", "rpt_rw_term_suspicious_use"))


NAMES_SHOWN = 5  # service names in a host's explanation; the rest are counted
_EXPOSURE_KEYS = {"fully_protected": "rpt_rw_exposure_fully_protected"}


def _state_key(state: object) -> str:
    s = str(state or "")
    return ("rpt_rw_state_protected" if s.startswith("protected") else "rpt_rw_state_unprotected"
            if s == "unprotected" else "rpt_rw_state_unknown")


def _org_percent(summary: Mapping[str, Any]) -> float | None:
    rw = summary.get("ransomware")
    pct = rw.get("ransomware_protection_coverage_percent") if isinstance(rw, Mapping) else None
    return float(pct) if isinstance(pct, (int, float)) and not isinstance(pct, bool) else None


def build_ransomware(inp: BuildInput) -> ReportDocument:
    lang = inp.lang

    def t(msg: str, /, **params: object) -> str:
        return tr(lang, msg, **params)

    first_day, last_day = db_day(inp.start), db_day(inp.end - timedelta(microseconds=1))
    with reads.reading(inp.ctx) as conn:
        row = analysis.read_result(conn, "ransomware")
        by_day = ransomware.protected_by_day(conn, first_day, last_day)
        orgs = ransomware.org_summaries(conn, last_day)
        computed_at, run_error = reads.analysis_state(conn, "ransomware")
    result: dict[str, Any] | None = json.loads(row["result_json"]) if row is not None else None
    status = None if result is None else "unsupported" if result.get("unsupported") else "ok"
    missing = t("rpt_rw_not_computed") if status is None else t("rpt_rw_unsupported")
    hosts: list[dict[str, Any]] = list((result or {}).get("hosts") or ())
    lists = {key: list((result or {}).get(key) or ()) for _, key, *_ in _LISTS}
    # The organisation summary of the period (its latest day), and of the period before: never an older reading.
    prev_first = db_day(previous_period(inp.start, inp.end, inp.tz)[0])
    readings = [(d, p) for d, s in orgs if (p := _org_percent(s)) is not None]
    org_now = next((p for d, p in readings if d >= first_day), None)
    org_before = next((p for d, p in readings if prev_first <= d < first_day), None)
    org_last = readings[0][0] if readings and org_now is None else None
    before = previous_values(inp)
    values: dict[str, float | int | None] = {
        "rated_hosts": len(hosts), "org_percent": org_now, "priority": len(lists["priority"]),
        "safe_to_block": len(lists["safe_to_block"]), "suspicious": len(lists["suspicious"]),
        "contradictions": sum(1 for h in hosts if h.get("contradiction"))}
    ok = status == "ok"
    kpis = tuple(Kpi(key=k, label=t(label), value=(values[k] if ok or (k == "org_percent" and values[k] is not None)
                                                   else None),
                     previous=org_before if k == "org_percent" else (before or {}).get(k),
                     unit="percent" if k == "org_percent" else "count",
                     better="higher" if k in ("org_percent", "rated_hosts") else "lower",
                     note=(t("rpt_rw_org_last_known", day=org_last) if k == "org_percent" and org_last
                           else t("rpt_rw_org_missing") if k == "org_percent" and values[k] is None
                           else None if ok or k == "org_percent" else missing))
                 for k, label in _KPI_KEYS.items())

    def name(r: Mapping[str, Any]) -> str:
        return str(r.get("hostname") or str(r.get("host") or r.get("href") or "").rsplit("/", 1)[-1])

    def list_table(key: str, title: str, empty: str) -> TableBlock:
        items = lists[key]
        return TableBlock(
            title=title,
            columns=(Column(key="host", label=t("rpt_col_host")), Column(key="service", label=t("rpt_col_name")),
                     Column(key="port", label=t("rpt_col_service")), Column(key="severity", label=t("rpt_col_severity")),
                     Column(key="sources", label=t("rpt_col_recent_sources"), kind="number")),
            rows=tuple((name(r), r.get("name"), port_text(r.get("port"), int(r.get("proto") or 0)),
                        severity_name(lang, str(r.get("severity") or "").lower()), r.get("recent_sources"))
                       for r in items[:LIST_ROWS]),
            total_rows=len(items), empty_text=t(empty) if ok else missing,
            limit_note=t("rpt_limit_top_n", n=LIST_ROWS) if len(items) > LIST_ROWS else None)
    list_sections = tuple(Section(id=sid, title=t(title), intro=t(intro), blocks=(list_table(key, t(title), empty),))
                          for sid, key, title, intro, empty in _LISTS)

    # ── hosts, ranked by the computed share; contradictions last and flagged ─────
    def pct(v: Any) -> str:
        return f"{float(v):.1f}%" if isinstance(v, (int, float)) else "—"

    def explain(h: Mapping[str, Any]) -> str:
        """What the host's numbers mean, in words."""
        open_ = [s for s in h.get("services") or () if s.get("protection_state") == "unprotected"]
        if h.get("contradiction"):
            return t("rpt_rw_explain_contradiction", pce=pct(h.get("pce_percent")), n=len(open_))
        if not open_:
            return t("rpt_rw_explain_protected")
        names = list(dict.fromkeys(str(s.get("name")) for s in open_))  # a service on TCP and UDP is named once
        shown = ", ".join(names[:NAMES_SHOWN])
        if len(names) > NAMES_SHOWN:
            shown = t("rpt_rw_names_more", names=shown, n=len(names) - NAMES_SHOWN)
        return t("rpt_rw_explain_open", n=len(open_), names=shown)

    def exposure(v: Any) -> str:
        if not v:
            return "—"
        key = _EXPOSURE_KEYS.get(str(v).lower())
        return t(key) if key else severity_name(lang, str(v).lower())
    ranked = sorted(hosts, key=lambda h: (bool(h.get("contradiction")), h.get("computed_percent") is None,
                                          h.get("computed_percent") or 0.0, name(h)))
    host_table = TableBlock(
        title=t("rpt_rw_tbl_hosts"),
        columns=(Column(key="host", label=t("rpt_col_host")), Column(key="pce", label=t("rpt_rw_col_pce_percent")),
                 Column(key="computed", label=t("rpt_rw_col_computed")),
                 Column(key="exposure", label=t("rpt_rw_col_exposure")),
                 Column(key="unprotected", label=t("rpt_rw_col_unprotected"), kind="number"),
                 Column(key="contradiction", label=t("rpt_rw_col_contradiction")),
                 Column(key="explain", label=t("rpt_rdy_col_explain"))),
        rows=tuple((name(h), pct(h.get("pce_percent")), pct(h.get("computed_percent")),
                    exposure(h.get("pce_exposure")),
                    sum(1 for s in h.get("services") or () if s.get("protection_state") == "unprotected"),
                    t("rpt_rw_contradiction_yes") if h.get("contradiction") else "", explain(h)) for h in ranked),
        total_rows=len(ranked), empty_text=t("rpt_rw_none_hosts") if ok else missing)
    services = [(h, s) for h in ranked for s in h.get("services") or ()]
    service_table = TableBlock(
        title=t("rpt_rw_tbl_services"),
        columns=(Column(key="host", label=t("rpt_col_host")), Column(key="service", label=t("rpt_col_name")),
                 Column(key="port", label=t("rpt_col_service")), Column(key="severity", label=t("rpt_col_severity")),
                 Column(key="weight", label=t("rpt_rw_col_weight"), kind="number"),
                 Column(key="state", label=t("rpt_rw_col_state")),
                 Column(key="coverage", label=t("rpt_rw_col_coverage")),
                 Column(key="contribution", label=t("rpt_rw_col_contribution"))),
        rows=tuple((name(h), s.get("name"), port_text(s.get("port"), int(s.get("proto") or 0)),
                    severity_name(lang, str(s.get("severity") or "").lower()), s.get("weight"),
                    t(_state_key(s.get("protection_state"))),
                    pct(100 * s["coverage"]) if isinstance(s.get("coverage"), (int, float)) else "—",
                    f"{s['contribution']:.1f}" if isinstance(s.get("contribution"), (int, float)) else "—")
                   for h, s in services),
        total_rows=len(services), empty_text=t("rpt_rw_none_hosts") if ok else missing)

    # ── allow rules behind the deductions, for the top hosts of the fix-first list ─────
    top_hosts: list[str] = list(dict.fromkeys(str(r.get("host")) for r in lists["priority"] if r.get("host")))
    allow_rows: list[tuple[str, str, str]] = []
    names = {str(r.get("host")): name(r) for r in lists["priority"]}
    for href in top_hosts[:ALLOW_HOSTS]:
        try:
            found = host_ransomware(inp.ctx, href, now=inp.now, explain_allows=True)
        except Exception as exc:  # noqa: BLE001 - one host's lookup failing is said, the report goes on
            logger.warning("allow rules of {} could not be read: {}", href, exc)
            allow_rows.append((names[href], "—", t("rpt_rw_allow_error")))
            continue
        for key, rules in found.allow_rules.items():
            port, _, proto = key.partition("/")
            state = found.allow_status.get(key, "ok")
            text = (t(_STATUS_KEYS[state]) if state in _STATUS_KEYS and not rules
                    else "; ".join(f"{r.ruleset_name}: {r.description or r.href.rsplit('/', 1)[-1]}" for r in rules)
                    or t("rpt_rw_allow_none"))
            if state == "error":
                text = t("rpt_rw_allow_error")
            allow_rows.append((names[href], port_text(int(port), int(proto or 0)), text))
    allow_table = TableBlock(
        title=t("rpt_rw_tbl_allow"),
        columns=(Column(key="host", label=t("rpt_col_host")), Column(key="port", label=t("rpt_col_service")),
                 Column(key="rules", label=t("rpt_rw_col_rules"))),
        rows=tuple(allow_rows), total_rows=len(allow_rows),
        empty_text=t("rpt_rw_none_allow") if ok else missing,
        limit_note=t("rpt_rw_allow_top", n=ALLOW_HOSTS) if len(top_hosts) > ALLOW_HOSTS else None)

    # ── trend ───────────────────────────────────────────────────────────────
    # The snapshots are per UTC day: every UTC day the period touches, both ends included.
    first, last = date.fromisoformat(first_day), date.fromisoformat(last_day)
    days = [(first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)]
    trend = BarBlock(title=t("rpt_rw_bar_trend"),
                     points=tuple((d, round(100 * by_day[d][1] / by_day[d][0], 1) if d in by_day and by_day[d][0]
                                   else None) for d in days),
                     empty_text=t("rpt_rw_none_trend"))

    quality = [t("rpt_rw_quality_source"), t("rpt_rw_quality_approx")]
    if computed_at:
        quality.append(t("rpt_quality_analysis_at", at=fmt_time(computed_at, inp.tz)))
    if run_error:
        quality.append(t("rpt_quality_analysis_failed", error=run_error[:200]))
    if values["contradictions"]:
        quality.append(t("rpt_rw_quality_contradictions", n=values["contradictions"]))
    blocks_missing: Sequence[TextBlock] = () if ok else (TextBlock(paragraphs=(missing,)),)
    terms = TableBlock(
        title=t("rpt_rw_tbl_terms"),
        columns=(Column(key="term", label=t("rpt_rw_col_term")), Column(key="means", label=t("rpt_rdy_col_means")),
                 Column(key="use", label=t("rpt_rw_col_use"))),
        rows=tuple((t(term), t(means), t(use)) for term, means, use in _TERMS), total_rows=len(_TERMS), empty_text="")
    findings: list[Finding] = []
    if ok and lists["priority"]:
        findings.append(Finding(severity=Severity.HIGH, title=t("rpt_rw_finding_priority", n=len(lists["priority"])),
                                why=t("rpt_rw_finding_priority_why"), action=t("rpt_rw_finding_priority_action")))
    unsorted = sum(1 for h in hosts for s in h.get("services") or ()
                   if s.get("protection_state") == "unprotected" and s.get("traffic") == "unknown")
    if ok and unsorted:  # lightweight mode keeps no traffic: the lists stay empty, the services do not go away
        findings.append(Finding(severity=Severity.MEDIUM, title=t("rpt_rw_finding_unsorted", n=unsorted),
                                why=t("rpt_rw_finding_unsorted_why"), action=t("rpt_rw_finding_unsorted_action")))
    if ok and lists["safe_to_block"]:
        findings.append(Finding(severity=Severity.MEDIUM, title=t("rpt_rw_finding_safe", n=len(lists["safe_to_block"])),
                                why=t("rpt_rw_finding_safe_why"), action=t("rpt_rw_finding_safe_action")))
    return ReportDocument(
        report_type=inp.params.report_type, lang=lang, title=t("rpt_title_ransomware"), period_start=inp.start,
        period_end=inp.end, generated_at=inp.now, pce_label=inp.pce_label, kpis=kpis, findings=tuple(findings),
        data_quality=tuple(quality),
        sections=(Section(id="how", title=t("rpt_rdy_sec_how"), intro=t("rpt_rw_how_intro"), blocks=(terms,)),
                  *(s.model_copy(update={"blocks": (*blocks_missing, *s.blocks)}) for s in list_sections),
                  Section(id="hosts", title=t("rpt_rw_sec_hosts"), intro=t("rpt_rw_hosts_intro"),
                          blocks=(host_table, service_table)),
                  Section(id="allow", title=t("rpt_rw_sec_allow"), intro=t("rpt_rw_allow_intro"), blocks=(allow_table,)),
                  Section(id="trend", title=t("rpt_rw_sec_trend"), intro=t("rpt_rw_trend_intro"), blocks=(trend,))))
