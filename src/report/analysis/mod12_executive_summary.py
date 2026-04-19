"""Module 12: Deterministic executive summary with attack-first sections."""
from __future__ import annotations

import datetime
from typing import Any

from .attack_posture import summarize_attack_posture
from src.i18n import t, get_language

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

def _enforcement_mode_distribution(results: dict[str, Any]) -> dict[str, int]:
    """Extract enforcement mode distribution from mod13 workload metadata."""
    mod13 = results.get("mod13", {})
    if isinstance(mod13, dict) and "enforcement_mode_distribution" in mod13:
        return mod13["enforcement_mode_distribution"]
    return {}

def _maturity_grade(score: float) -> str:
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 55:
        return "C"
    if score >= 40:
        return "D"
    return "F"

def _compute_maturity_score(results: dict[str, Any]) -> dict[str, Any]:
    """Compute a single 0-100 Microsegmentation Maturity Score.

    Dimensions and weights:
      - Enforcement coverage (40%): enforced + 0.5*staged
      - Policy coverage (25%): allowed / total flows
      - Lateral movement control (15%): inverse of lateral_pct
      - Unmanaged asset ratio (10%): inverse of unmanaged %
      - High-risk port exposure (10%): inverse of risk flow ratio
    """
    mod01 = results.get("mod01", {})
    mod03 = results.get("mod03", {})
    mod04 = results.get("mod04", {})
    mod15 = results.get("mod15", {})

    total_flows = mod01.get("total_flows", 0) or 1

    # Dimension 1: Enforcement coverage (enforced + half credit for staged)
    enforced_pct = mod03.get("enforced_coverage_pct", mod01.get("policy_coverage_pct", 0))
    staged_pct = mod03.get("staged_coverage_pct", 0)
    enforcement_ratio = min(100.0, enforced_pct + staged_pct * 0.5) / 100.0

    # Dimension 2: Policy coverage (same as enforced for now)
    policy_ratio = enforced_pct / 100.0

    # Dimension 3: Lateral movement control (lower lateral % = better)
    lateral_pct = 0.0
    if isinstance(mod15, dict):
        lateral_pct = mod15.get("lateral_pct", 0.0)
    # Cap at 30% — beyond that the score bottoms out
    lateral_control = max(0.0, 1.0 - min(lateral_pct, 30.0) / 30.0)

    # Dimension 4: Managed asset ratio (lower unmanaged = better)
    unmanaged_pct = 100.0 - mod01.get("src_managed_pct", 100)
    managed_ratio = max(0.0, 1.0 - min(unmanaged_pct, 50.0) / 50.0)

    # Dimension 5: Risk port exposure (lower risk flows = better)
    risk_flows = mod04.get("risk_flows_total", 0) if isinstance(mod04, dict) else 0
    risk_ratio = risk_flows / total_flows if total_flows > 0 else 0
    risk_control = max(0.0, 1.0 - min(risk_ratio * 5, 1.0))  # 20% risk flows = 0 score

    weights = {
        "enforcement_coverage": 40,
        "policy_coverage": 25,
        "lateral_movement_control": 15,
        "managed_asset_ratio": 10,
        "risk_port_control": 10,
    }
    scores = {
        "enforcement_coverage": round(weights["enforcement_coverage"] * enforcement_ratio, 1),
        "policy_coverage": round(weights["policy_coverage"] * policy_ratio, 1),
        "lateral_movement_control": round(weights["lateral_movement_control"] * lateral_control, 1),
        "managed_asset_ratio": round(weights["managed_asset_ratio"] * managed_ratio, 1),
        "risk_port_control": round(weights["risk_port_control"] * risk_control, 1),
    }
    total = round(sum(scores.values()), 1)

    return {
        "maturity_score": total,
        "maturity_grade": _maturity_grade(total),
        "maturity_dimensions": {
            "enforcement_coverage": {"weight": 40, "score": scores["enforcement_coverage"], "ratio": round(enforcement_ratio, 4)},
            "policy_coverage": {"weight": 25, "score": scores["policy_coverage"], "ratio": round(policy_ratio, 4)},
            "lateral_movement_control": {"weight": 15, "score": scores["lateral_movement_control"], "ratio": round(lateral_control, 4)},
            "managed_asset_ratio": {"weight": 10, "score": scores["managed_asset_ratio"], "ratio": round(managed_ratio, 4)},
            "risk_port_control": {"weight": 10, "score": scores["risk_port_control"], "ratio": round(risk_control, 4)},
        },
    }

def executive_summary(results: dict[str, Any]) -> dict:
    mod01 = results.get("mod01", {})
    mod03 = results.get("mod03", {})
    mod04 = results.get("mod04", {})
    mod08 = results.get("mod08", {})
    mod11 = results.get("mod11", {})
    mod15 = results.get("mod15", {})
    findings = results.get("findings", [])

    # Three-tier coverage from mod03
    enforced_cov = mod03.get("enforced_coverage_pct", mod01.get("policy_coverage_pct", 0))
    staged_cov = mod03.get("staged_coverage_pct", 0)
    true_gap = mod03.get("true_gap_pct", 0)

    # Enforcement mode distribution
    enforcement_dist = _enforcement_mode_distribution(results)

    kpis = [
        {"label": "Total Flows", "value": _fmt(mod01.get("total_flows", 0))},
        {"label": "Total Connections", "value": _fmt(mod01.get("total_connections", 0))},
        {"label": "Unique Source IPs", "value": _fmt(mod01.get("unique_src_ips", 0))},
        {"label": "Unique Dest IPs", "value": _fmt(mod01.get("unique_dst_ips", 0))},
        {"label": "Enforced Coverage", "value": f"{enforced_cov}%"},
        {"label": "Staged Coverage", "value": f"{staged_cov}%"},
        {"label": "True Gap", "value": f"{true_gap}%"},
        {"label": "Blocked Flows", "value": _fmt(mod01.get("blocked_flows", 0))},
        {"label": "Potentially Blocked", "value": _fmt(mod01.get("potentially_blocked_flows", 0))},
        {"label": "Unmanaged Src %", "value": f"{100 - mod01.get('src_managed_pct', 100):.1f}%"},
        {"label": "Total Data Volume", "value": f"{mod01.get('total_mb', 0):.1f} MB"},
        {"label": "Date Range", "value": mod01.get("date_range", "N/A")},
    ]

    # Add enforcement mode distribution KPIs if available
    if enforcement_dist:
        for mode in ("full", "selective", "visibility_only", "idle"):
            count = enforcement_dist.get(mode, 0)
            if count > 0:
                label = mode.replace("_", " ").title()
                kpis.append({"label": f"Enforcement: {label}", "value": _fmt(count)})

    findings_summary: dict[str, int] = {}
    for f in findings:
        findings_summary[f.severity] = findings_summary.get(f.severity, 0) + 1

    key_findings: list[dict[str, str]] = []
    coverage = enforced_cov
    if coverage < 50:
        if staged_cov > 20:
            key_findings.append(
                {
                    "severity": "MEDIUM",
                    "finding": (
                        f"Only {coverage:.0f}% of flows are enforced, but {staged_cov:.0f}% "
                        f"are staged (rules ready, pending enforcement)."
                    ),
                    "action": "Move workloads from test/visibility to selective or full enforcement.",
                }
            )
        else:
            key_findings.append(
                {
                    "severity": "HIGH",
                    "finding": f"Only {coverage:.0f}% of flows are covered by allow policies — true gap is {true_gap:.0f}%.",
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

    lateral_total = mod15.get("total_lateral_flows", 0) if isinstance(mod15, dict) else 0
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

    # A3: Organization-level Microsegmentation Maturity Score
    maturity = _compute_maturity_score(results)
    kpis.insert(0, {"label": "Maturity Score", "value": f"{maturity['maturity_score']}/100 ({maturity['maturity_grade']})"})

    dim_labels = [
        t('rpt_dim_enforcement', default='Enforcement Coverage'),
        t('rpt_dim_policy', default='Policy Coverage'),
        t('rpt_dim_lateral', default='Lateral Control'),
        t('rpt_dim_managed', default='Managed Asset Ratio'),
        t('rpt_dim_risk', default='Risk Port Control'),
    ]
    dim_keys = ['enforcement_coverage', 'policy_coverage', 'lateral_movement_control',
                'managed_asset_ratio', 'risk_port_control']
    dim_values = [maturity['maturity_dimensions'][k]['score'] for k in dim_keys]

    return {
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "kpis": kpis,
        "findings_summary": findings_summary,
        "total_findings": len(findings),
        "key_findings": key_findings,
        "findings": findings,
        "enforced_coverage_pct": enforced_cov,
        "staged_coverage_pct": staged_cov,
        "true_gap_pct": true_gap,
        "enforcement_mode_distribution": enforcement_dist,
        "maturity_score": maturity["maturity_score"],
        "maturity_grade": maturity["maturity_grade"],
        "maturity_dimensions": maturity["maturity_dimensions"],
        "boundary_breaches": attack_sections["boundary_breaches"],
        "suspicious_pivot_behavior": attack_sections["suspicious_pivot_behavior"],
        "blast_radius": attack_sections["blast_radius"],
        "blind_spots": attack_sections["blind_spots"],
        "action_matrix": attack_sections["action_matrix"],
        "chart_spec": {
            "type": "bar",
            "title": t("rpt_mod12_chart_title", default="Microsegmentation Maturity Dimensions"),
            "x_label": t("rpt_dimension", default="Dimension"),
            "y_label": t("rpt_score", default="Score"),
            "data": {"labels": dim_labels, "values": dim_values},
            "i18n": {"lang": get_language()},
        },
    }

