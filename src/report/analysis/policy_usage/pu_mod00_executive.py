"""
pu_mod00_executive.py
Executive summary KPIs and execution metadata for the Policy Usage report.
"""
import datetime
from collections import Counter

from src.report.analysis.attack_posture import (
    make_posture_item,
    rank_posture_items,
    summarize_attack_posture,
)


_HIGH_RISK_PORT_MARKERS = {"22/", "3389/", "445/", "5985/", "5986/", "135/"}


def pu_executive_summary(results: dict, lookback_days: int) -> dict:
    """Aggregate KPIs, attention items, execution stats, and deterministic attack posture."""
    mod01 = results.get("mod01", {})
    mod03 = results.get("mod03", {})
    execution = (results.get("meta", {}) or {}).get("execution_stats", {}) or {}

    total = mod01.get("total_rules", 0)
    hit = mod01.get("hit_count", 0)
    unused = mod01.get("unused_count", 0)
    rate = mod01.get("hit_rate_pct", 0.0)

    cached = int(execution.get("cached_rules", 0) or 0)
    submitted = int(execution.get("submitted_rules", 0) or 0)
    pending = int(execution.get("pending_jobs", 0) or 0)
    failed = int(execution.get("failed_jobs", 0) or 0)
    top_hit_ports = execution.get("top_hit_ports", []) or []
    top_port_label = top_hit_ports[0].get("port_proto", "N/A") if top_hit_ports else "N/A"

    kpis = [
        {"label": "Total Rules", "value": str(total)},
        {"label": "Hit Rules", "value": str(hit)},
        {"label": "Unused Rules", "value": str(unused)},
        {"label": "Hit Rate", "value": f"{rate}%"},
        {"label": "Lookback", "value": f"{lookback_days} days"},
        {"label": "Cached Reuse", "value": str(cached)},
        {"label": "New Queries", "value": str(submitted)},
        {"label": "Top Hit Port", "value": top_port_label},
    ]

    attention_items = []
    unused_df = mod03.get("unused_df")
    if unused_df is not None and not unused_df.empty and "Ruleset" in unused_df.columns:
        counts = Counter(unused_df["Ruleset"].tolist())
        for rs_name, cnt in counts.most_common(5):
            attention_items.append({"ruleset": rs_name, "unused_count": cnt})

    execution_notes = []
    if cached:
        execution_notes.append(f"Reused {cached} completed async summaries.")
    if submitted:
        execution_notes.append(f"Submitted {submitted} new async queries.")
    if pending:
        execution_notes.append(f"{pending} async queries were still pending at timeout.")
    if failed:
        execution_notes.append(f"{failed} async queries failed.")
    if top_hit_ports:
        top_summary = ", ".join(
            f"{item.get('port_proto', '')} ({int(item.get('flow_count', 0) or 0)})"
            for item in top_hit_ports[:3]
        )
        execution_notes.append(f"Top observed hit ports: {top_summary}.")

    attack_items = []
    if rate < 70:
        attack_items.append(
            make_posture_item(
                scope="policy_usage_report",
                framework="microseg_attack",
                app="policy_usage",
                env="global",
                finding_kind="boundary_breach",
                attack_stage="control_plane",
                confidence="high",
                recommended_action_code="REVIEW_UNUSED_RULESETS",
                severity="HIGH" if rate < 50 else "MEDIUM",
                evidence={"hit_rate_pct": rate, "total_rules": total, "unused_rules": unused},
            )
        )

    if attention_items:
        top = attention_items[0]
        top_unused = int(top.get("unused_count", 0) or 0)
        if top_unused > 0:
            attack_items.append(
                make_posture_item(
                    scope="policy_usage_report",
                    framework="microseg_attack",
                    app="policy_usage",
                    env="global",
                    finding_kind="blind_spot",
                    attack_stage="exposure",
                    confidence="medium",
                    recommended_action_code="REVIEW_UNUSED_RULESETS",
                    severity="HIGH" if top_unused >= 10 else "MEDIUM",
                    evidence={"ruleset": top.get("ruleset", ""), "unused_count": top_unused},
                )
            )

    if pending > 0 or failed > 0:
        attack_items.append(
            make_posture_item(
                scope="policy_usage_report",
                framework="microseg_attack",
                app="policy_usage",
                env="global",
                finding_kind="blind_spot",
                attack_stage="control_plane",
                confidence="medium",
                recommended_action_code="RESOLVE_QUERY_FAILURES",
                severity="HIGH" if failed > 0 else "MEDIUM",
                evidence={"pending_jobs": pending, "failed_jobs": failed},
            )
        )

    if top_hit_ports:
        first_port = str(top_hit_ports[0].get("port_proto", "") or "")
        if any(marker in first_port for marker in _HIGH_RISK_PORT_MARKERS):
            attack_items.append(
                make_posture_item(
                    scope="policy_usage_report",
                    framework="microseg_attack",
                    app="policy_usage",
                    env="global",
                    finding_kind="suspicious_pivot",
                    attack_stage="pivot",
                    confidence="medium",
                    recommended_action_code="INVESTIGATE_HIGH_RISK_PORT_HITS",
                    severity="HIGH",
                    evidence={
                        "top_hit_port": first_port,
                        "top_hit_port_flow_count": int(top_hit_ports[0].get("flow_count", 0) or 0),
                    },
                )
            )

    ranked_attack_items = rank_posture_items(attack_items)
    attack_sections = summarize_attack_posture(ranked_attack_items, top_n=5)

    return {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "lookback_days": lookback_days,
        "kpis": kpis,
        "attention_items": attention_items,
        "execution_stats": execution,
        "execution_notes": execution_notes,
        "attack_posture_items": ranked_attack_items,
        "boundary_breaches": attack_sections["boundary_breaches"],
        "suspicious_pivot_behavior": attack_sections["suspicious_pivot_behavior"],
        "blast_radius": attack_sections["blast_radius"],
        "blind_spots": attack_sections["blind_spots"],
        "action_matrix": attack_sections["action_matrix"],
    }

