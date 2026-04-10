"""Module 12: Deterministic executive summary with attack-first sections."""
from __future__ import annotations

import datetime
from typing import Any

from .attack_posture import summarize_attack_posture


def _fmt(n) -> str:
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return str(n)


def _collect_attack_items(results: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for mod_id in ("mod13", "mod14", "mod15"):
        module = results.get(mod_id, {})
        if isinstance(module, dict):
            module_items = module.get("attack_posture_items", [])
            if isinstance(module_items, list):
                items.extend(module_items)
    return items


def executive_summary(results: dict[str, Any]) -> dict:
    mod01 = results.get("mod01", {})
    mod04 = results.get("mod04", {})
    mod05 = results.get("mod05", {})
    mod08 = results.get("mod08", {})
    mod11 = results.get("mod11", {})
    findings = results.get("findings", [])

    kpis = [
        {"label": "Total Flows", "value": _fmt(mod01.get("total_flows", 0))},
        {"label": "Total Connections", "value": _fmt(mod01.get("total_connections", 0))},
        {"label": "Unique Source IPs", "value": _fmt(mod01.get("unique_src_ips", 0))},
        {"label": "Unique Dest IPs", "value": _fmt(mod01.get("unique_dst_ips", 0))},
        {"label": "Policy Coverage", "value": f"{mod01.get('policy_coverage_pct', 0)}%"},
        {"label": "Blocked Flows", "value": _fmt(mod01.get("blocked_flows", 0))},
        {"label": "Potentially Blocked", "value": _fmt(mod01.get("potentially_blocked_flows", 0))},
        {"label": "Unmanaged Src %", "value": f"{100 - mod01.get('src_managed_pct', 100):.1f}%"},
        {"label": "Total Data Volume", "value": f"{mod01.get('total_mb', 0):.1f} MB"},
        {"label": "Date Range", "value": mod01.get("date_range", "N/A")},
    ]

    findings_summary: dict[str, int] = {}
    for f in findings:
        findings_summary[f.severity] = findings_summary.get(f.severity, 0) + 1

    key_findings: list[dict[str, str]] = []
    coverage = mod01.get("policy_coverage_pct", 100)
    if coverage < 50:
        key_findings.append(
            {
                "severity": "HIGH",
                "finding": f"Only {coverage:.0f}% of flows are covered by allow policies.",
                "action": "Create segmentation rules for the top uncovered flows.",
            }
        )

    ransomware_total = mod04.get("risk_flows_total", 0)
    if ransomware_total > 0:
        key_findings.append(
            {
                "severity": "CRITICAL" if findings_summary.get("CRITICAL", 0) > 0 else "HIGH",
                "finding": f"{ransomware_total} flows on ransomware-associated ports detected.",
                "action": "Review ransomware-port exposure and remove non-essential paths.",
            }
        )

    lateral_total = mod05.get("total_lateral_flows", 0) if isinstance(mod05, dict) else 0
    if lateral_total > 0:
        key_findings.append(
            {
                "severity": "HIGH",
                "finding": f"{lateral_total} remote access / lateral movement flows found.",
                "action": "Apply micro-segmentation controls for RDP/SSH/SMB lateral paths.",
            }
        )

    unmanaged_count = mod08.get("unique_unmanaged_src", 0) if isinstance(mod08, dict) else 0
    if unmanaged_count > 10:
        key_findings.append(
            {
                "severity": "MEDIUM",
                "finding": f"{unmanaged_count} unique unmanaged source hosts.",
                "action": "Onboard unmanaged hosts or isolate their access paths.",
            }
        )

    if mod11.get("bytes_data_available"):
        total_mb = mod11.get("total_mb", 0)
        if total_mb > 1000:
            key_findings.append(
                {
                    "severity": "INFO",
                    "finding": f"Total data volume: {total_mb:.0f} MB across the analysis period.",
                    "action": "Review high-volume flows for data exfiltration patterns.",
                }
            )

    rank = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}
    key_findings.sort(key=lambda x: rank.get(x.get("severity", "INFO"), 99))

    attack_items = _collect_attack_items(results)
    attack_sections = summarize_attack_posture(attack_items, top_n=5)

    return {
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "kpis": kpis,
        "findings_summary": findings_summary,
        "total_findings": len(findings),
        "key_findings": key_findings,
        "findings": findings,
        "boundary_breaches": attack_sections["boundary_breaches"],
        "suspicious_pivot_behavior": attack_sections["suspicious_pivot_behavior"],
        "blast_radius": attack_sections["blast_radius"],
        "blind_spots": attack_sections["blind_spots"],
        "action_matrix": attack_sections["action_matrix"],
    }

