"""The one sentence a report opens with (UI redesign spec §6.5, §8): a fixed template per report type whose every
placeholder is one of that report's own key numbers (Kpi.key). A number the report could not compute makes the
sentence say which and why, never a 0. Custom reports have no key numbers: their sentence counts their sections."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import tzinfo

from illumio_ops.domain.report import Kpi, ReportDocument, period_text
from illumio_ops.domain.values import ReportType

Translate = Callable[[str, dict[str, str]], str]

CONCLUSION_KEYS: Mapping[ReportType, str] = {
    ReportType.LATERAL_POSTURE: "rpt_conclusion_lateral_posture",
    ReportType.NEW_CONNECTIONS: "rpt_conclusion_new_connections",
    ReportType.UNMANAGED_ENDPOINTS: "rpt_conclusion_unmanaged_endpoints",
    ReportType.TRAFFIC: "rpt_conclusion_traffic",
    ReportType.SECURITY_RISK: "rpt_conclusion_security_risk",
    ReportType.NETWORK_INVENTORY: "rpt_conclusion_network_inventory",
    ReportType.APP_SUMMARY: "rpt_conclusion_app_summary",
    ReportType.VEN_STATUS: "rpt_conclusion_ven_status",
    ReportType.AUDIT: "rpt_conclusion_audit",
    ReportType.RANSOMWARE: "rpt_conclusion_ransomware",
    ReportType.READINESS: "rpt_conclusion_readiness",
    ReportType.POLICY_USAGE: "rpt_conclusion_policy_usage",
    ReportType.RULE_HIT_COUNT: "rpt_conclusion_rule_hit_count",
    ReportType.POLICY_DIFF: "rpt_conclusion_policy_diff",
    ReportType.POLICY_RESOLVER: "rpt_conclusion_policy_resolver",
    ReportType.CUSTOM: "rpt_conclusion_custom",
}
CONCLUSION_KPIS: Mapping[ReportType, tuple[str, ...]] = {
    ReportType.LATERAL_POSTURE: ("assets_reachable", "pivots", "cross_env", "new_detections"),
    ReportType.NEW_CONNECTIONS: ("new", "admin", "critical", "unmanaged_source"),
    ReportType.UNMANAGED_ENDPOINTS: ("total", "private", "public", "admin_sources"),
    ReportType.TRAFFIC: ("flows", "connections", "sources", "destinations"),
    ReportType.SECURITY_RISK: ("maturity", "enforced_hosts_pct", "critical_high_findings"),
    ReportType.NETWORK_INVENTORY: ("managed_hosts", "hosts_missing_labels", "apps", "cross_env_connections"),
    ReportType.APP_SUMMARY: ("inbound_connections", "outbound_connections", "intra_connections", "allowed_pct"),
    ReportType.VEN_STATUS: ("managed", "online", "long_offline", "status_unknown", "sync_problems"),
    ReportType.AUDIT: ("total", "high_risk", "auth_failed", "authz_denied", "policy_provisions"),
    ReportType.RANSOMWARE: ("rated_hosts", "priority", "safe_to_block"),
    ReportType.READINESS: ("apps", "ready", "held_back", "predicted_blocked"),
    ReportType.POLICY_USAGE: ("rules", "used", "unused", "disabled", "no_rule"),
    ReportType.RULE_HIT_COUNT: ("rules", "hit", "zero", "no_record"),
    ReportType.POLICY_DIFF: ("total", "rule_sets", "rules", "objects", "high"),
    ReportType.POLICY_RESOLVER: ("rules", "rulesets", "rows", "not_expanded", "no_address"),
    ReportType.CUSTOM: ("sections", "period"),
}


def _value(k: Kpi) -> str:
    v = k.value
    assert v is not None
    text = f"{v:,}" if isinstance(v, int) else f"{v:,.1f}"
    return text + ("%" if k.unit == "percent" else "")


def conclusion(doc: ReportDocument, tr: Translate, *, tz: tzinfo | None = None) -> str:
    """tz: the report's display zone (its dates as the cover shows them)."""
    if doc.report_type is ReportType.CUSTOM:
        return tr(CONCLUSION_KEYS[ReportType.CUSTOM], {"sections": f"{len(doc.sections):,}",
                                                      "period": period_text(doc.period_start, doc.period_end, tz)})
    wanted = CONCLUSION_KPIS[doc.report_type]
    kpis = {k.key: k for k in doc.kpis}
    missing = [kpis[w] for w in wanted if w in kpis and kpis[w].value is None]
    absent = [w for w in wanted if w not in kpis]
    if missing or absent:
        names = "、" if doc.lang.value == "zh_TW" else ", "
        reasons = [k.note.rstrip("。.") for k in missing if k.note]  # the sentence closes after the brackets
        return tr("rpt_conclusion_incomplete", {"title": doc.title,
                                                "missing": names.join([k.label for k in missing] + absent),
                                                "reasons": names.join(dict.fromkeys(reasons)) or "—"})
    return tr(CONCLUSION_KEYS[doc.report_type], {w: _value(kpis[w]) for w in wanted})
