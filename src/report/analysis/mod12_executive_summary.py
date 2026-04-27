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

_KF = {
    "staged_enforcement": {
        "en": ("Only {cov:.0f}% of flows are enforced, but {staged:.0f}% are staged (rules ready, pending enforcement).",
               "Move workloads from test/visibility to selective or full enforcement."),
        "zh_TW": ("僅 {cov:.0f}% 的流量已強制執行，但 {staged:.0f}% 已暫存（政策已就緒，待啟用執行）。",
                  "將 workload 從 test/visibility 模式移至 selective 或 full enforcement。"),
    },
    "policy_gap": {
        "en": ("Only {cov:.0f}% of flows are covered by allow policies — true gap is {gap:.0f}%.",
               "Create segmentation rules for the top uncovered flows."),
        "zh_TW": ("僅 {cov:.0f}% 的流量有允許政策覆蓋 — 實際缺口為 {gap:.0f}%。",
                  "為最大宗的未覆蓋流量建立分段規則。"),
    },
    "ransomware": {
        "en": ("{n} flows on ransomware-associated ports detected.",
               "Review ransomware-port exposure and remove non-essential paths."),
        "zh_TW": ("偵測到 {n} 筆流量使用勒索軟體相關通訊埠。",
                  "檢查勒索軟體相關通訊埠的曝露情況，移除非必要路徑。"),
    },
    "lateral": {
        "en": ("{n} remote access / lateral movement flows found.",
               "Apply micro-segmentation controls for RDP/SSH/SMB lateral paths."),
        "zh_TW": ("發現 {n} 筆遠端存取 / 橫向移動流量。",
                  "對 RDP/SSH/SMB 橫向路徑套用微分段控制。"),
    },
    "unmanaged": {
        "en": ("{n} unique unmanaged source hosts.",
               "Onboard unmanaged hosts or isolate their access paths."),
        "zh_TW": ("{n} 個唯一的未受管理來源主機。",
                  "將未受管理的主機納管，或隔離其存取路徑。"),
    },
    "data_volume": {
        "en": ("Total data volume: {mb:.0f} MB across the analysis period.",
               "Review high-volume flows for data exfiltration patterns."),
        "zh_TW": ("分析期間總資料量：{mb:.0f} MB。",
                  "檢查高流量是否存在資料外洩模式。"),
    },
}

def _kf(key: str, lang: str, **kwargs) -> tuple[str, str]:
    tmpl = _KF[key].get(lang) or _KF[key]["en"]
    return tmpl[0].format(**kwargs), tmpl[1].format(**kwargs)


def executive_summary(results: dict[str, Any], profile: str = "security_risk", lang: str = "en") -> dict:
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
        {"label": "PB Uncovered Exposure", "value": _fmt(
            mod01.get("potentially_blocked_flows") or
            mod03.get("pb_uncovered_count", mod03.get("n_potentially_blocked", 0))
        )},
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
            f, a = _kf("staged_enforcement", lang, cov=coverage, staged=staged_cov)
            key_findings.append({"severity": "MEDIUM", "finding": f, "action": a})
        else:
            f, a = _kf("policy_gap", lang, cov=coverage, gap=true_gap)
            key_findings.append({"severity": "HIGH", "finding": f, "action": a})

    ransomware_total = mod04.get("risk_flows_total", 0)
    if ransomware_total > 0:
        f, a = _kf("ransomware", lang, n=_fmt(ransomware_total))
        key_findings.append({
            "severity": "CRITICAL" if findings_summary.get("CRITICAL", 0) > 0 else "HIGH",
            "finding": f, "action": a,
        })

    lateral_total = mod15.get("total_lateral_flows", 0) if isinstance(mod15, dict) else 0
    if lateral_total > 0:
        f, a = _kf("lateral", lang, n=_fmt(lateral_total))
        key_findings.append({"severity": "HIGH", "finding": f, "action": a})

    unmanaged_count = mod08.get("unique_unmanaged_src", 0) if isinstance(mod08, dict) else 0
    if unmanaged_count > 10:
        f, a = _kf("unmanaged", lang, n=_fmt(unmanaged_count))
        key_findings.append({"severity": "MEDIUM", "finding": f, "action": a})

    if mod11.get("bytes_data_available"):
        total_mb = mod11.get("total_mb", 0)
        if total_mb > 1000:
            f, a = _kf("data_volume", lang, mb=total_mb)
            key_findings.append({"severity": "INFO", "finding": f, "action": a})

    rank = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}
    key_findings.sort(key=lambda x: rank.get(x.get("severity", "INFO"), 99))

    attack_items = _collect_attack_items(results)
    mod15_node_ips = results.get("mod15", {}).get("node_ips") if isinstance(results.get("mod15"), dict) else None
    attack_sections = summarize_attack_posture(attack_items, top_n=5, lang=lang, node_ips=mod15_node_ips)

    # A3: Organization-level Microsegmentation Maturity Score
    maturity = _compute_maturity_score(results)
    kpis.insert(0, {"label": "Maturity Score", "value": f"{maturity['maturity_score']}/100 ({maturity['maturity_grade']})"})

    dim_labels = [
        'Enforcement Coverage',
        'Policy Coverage',
        'Lateral Control',
        'Managed Asset Ratio',
        'Risk Port Control',
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
            "title": "Microsegmentation Maturity Dimensions",
            "x_label": t("rpt_dimension", default="Dimension"),
            "y_label": t("rpt_score", default="Score"),
            "data": {"labels": dim_labels, "values": dim_values},
            "i18n": {"lang": get_language()},
        },
    }


def analyze(flows_df: "pd.DataFrame", profile: str = "security_risk", **kwargs) -> dict:
    """Profile-aware executive summary from raw flows DataFrame.

    profile: "security_risk" | "network_inventory"
    kwargs: optional pre-computed summaries (attack_summary, lateral_summary,
            readiness_summary for security_risk; label_summary, ringfence_summary,
            unmanaged_summary for network_inventory).
    """
    if profile == "security_risk":
        return _security_risk_kpis(flows_df, **kwargs)
    if profile == "network_inventory":
        return _network_inventory_kpis(flows_df, **kwargs)
    raise ValueError(f"unknown profile: {profile!r}")


def _security_risk_kpis(flows_df, *, attack_summary=None, lateral_summary=None,
                        readiness_summary=None, **_) -> dict:
    total = len(flows_df)
    allowed = int((flows_df["policy_decision"] == "allowed").sum())
    pb = int((flows_df["policy_decision"] == "potentially_blocked").sum())
    blocked = int((flows_df["policy_decision"] == "blocked").sum())
    allowed_share = (allowed / total) if total else 0.0
    maturity = allowed_share if readiness_summary is None else (
        allowed_share * readiness_summary.get("ready_to_enforce_share", 1.0))
    high_risk_lateral = (lateral_summary or {}).get("high_risk_path_count", 0)
    top_action = (attack_summary or {}).get("action_matrix", {}).get("top1", {
        "code": "NONE", "count": 0, "text": ""})
    kpis = {
        "microsegmentation_maturity": round(maturity, 4),
        "active_allow_coverage": round(allowed_share, 4),
        "pb_uncovered_exposure": pb,
        "blocked_flows": blocked,
        "high_risk_lateral_paths": high_risk_lateral,
        "top_remediation_action": top_action,
    }
    return {
        "profile": "security_risk",
        "kpis": kpis,
        "kpi_aliases": {"staged_coverage": pb},  # DEPRECATED alias for v3.21 removal
        "top_actions": _build_top_actions(attack_summary, limit=3),
    }


def _build_top_actions(attack_summary, *, limit=3):
    if not attack_summary:
        return []
    rows = attack_summary.get("action_matrix", {}).get("ranked", [])
    return [{"code": r.get("code", ""), "count": r.get("count", 0), **r} for r in rows[:limit]]


def _network_inventory_kpis(flows_df, *, label_summary=None, ringfence_summary=None,
                             unmanaged_summary=None, **_) -> dict:
    import pandas as pd
    total = len(flows_df)
    # Count distinct apps and envs from destination labels
    app_col = "app" if "app" in flows_df.columns else ("dst_app" if "dst_app" in flows_df.columns else None)
    apps = flows_df[app_col].dropna().nunique() if app_col and total else 0
    env_col = "env" if "env" in flows_df.columns else ("dst_env" if "dst_env" in flows_df.columns else None)
    envs = flows_df[env_col].dropna().nunique() if env_col and total else 0
    # Known dependency coverage: flows where src+dst labels are fully resolved
    if "src_label" in flows_df.columns and "dst_label" in flows_df.columns:
        known = int((flows_df["src_label"].notna() & flows_df["dst_label"].notna()).sum())
    else:
        known = 0
    label_complete = (label_summary or {}).get("fill_rate",
        (known / total) if total else 0.0)
    rule_candidates = (ringfence_summary or {}).get("candidate_rules_count", 0)
    unmanaged = (unmanaged_summary or {}).get("count", 0)
    top_gap = (ringfence_summary or {}).get("top_rule_gap", {
        "src_label": None, "dst_label": None, "flows": 0})
    kpis = {
        "observed_apps_envs": {"apps": apps, "envs": envs},
        "known_dependency_coverage": round((known / total) if total else 0.0, 4),
        "label_completeness": round(label_complete, 4),
        "rule_candidate_count": rule_candidates,
        "unmanaged_unknown_dependencies": unmanaged,
        "top_rule_building_gap": top_gap,
    }
    return {"profile": "network_inventory", "kpis": kpis}
