"""Module 0: Executive summary for the audit report."""

from __future__ import annotations

import datetime

import pandas as pd

from src.report.analysis.attack_posture import (
    make_posture_item,
    rank_posture_items,
    summarize_attack_posture,
)
from src.report.analysis.audit.audit_risk import AUDIT_RISK_MAP, RISK_ORDER


def _non_empty_values(df: pd.DataFrame, column: str, limit: int = 3) -> list[str]:
    if column not in df.columns:
        return []
    values = (
        df[column]
        .astype(str)
        .str.strip()
        .replace("", pd.NA)
        .dropna()
        .unique()
        .tolist()
    )
    return [str(value) for value in values[:limit]]


def audit_executive_summary(results: dict, df: pd.DataFrame) -> dict:
    mod01 = results.get("mod01", {})
    mod02 = results.get("mod02", {})
    mod03 = results.get("mod03", {})

    kpis = [
        {"label": "Total Events", "value": f"{len(df):,}"},
        {"label": "Health Events", "value": f"{mod01.get('total_health_events', 0):,}"},
        {"label": "Security Concerns", "value": str(mod01.get("security_concern_count", 0))},
        {"label": "Agent Connectivity", "value": str(mod01.get("connectivity_event_count", 0))},
        {"label": "Failed Logins", "value": str(mod02.get("failed_logins", 0))},
        {"label": "Policy Provisions", "value": str(mod03.get("provision_count", 0))},
        {"label": "Draft Rule Changes", "value": str(mod03.get("rule_change_count", 0))},
        {"label": "High-Risk Events", "value": str(mod03.get("high_risk_count", 0))},
    ]

    total_wa = mod03.get("total_workloads_affected", 0)
    if total_wa > 0:
        kpis.append({"label": "Workloads Affected", "value": f"{total_wa:,}"})

    if "src_ip" in df.columns:
        unique_ips = (
            df["src_ip"].astype(str).str.strip().replace("", pd.NA).dropna().nunique()
        )
        if unique_ips > 0:
            kpis.append({"label": "Unique Source IPs", "value": str(int(unique_ips))})

    if "known_event_type" in df.columns:
        unknown_count = int((~df["known_event_type"].fillna(False)).sum())
        kpis.append({"label": "Unknown Event Types", "value": str(unknown_count)})

    if "parser_note_count" in df.columns:
        parser_note_rows = int((pd.to_numeric(df["parser_note_count"], errors="coerce").fillna(0) > 0).sum())
        kpis.append({"label": "Parser Notes", "value": str(parser_note_rows)})

    top_events = pd.DataFrame()
    if "event_type" in df.columns and not df.empty:
        top_events = df["event_type"].value_counts().reset_index().head(15)
        top_events.columns = ["Event Type", "Count"]

    severity_dist = pd.DataFrame()
    if "severity" in df.columns and not df.empty:
        severity_dist = df["severity"].value_counts().reset_index()
        severity_dist.columns = ["Severity", "Count"]

    attention_items = []
    if not df.empty and "event_type" in df.columns:
        for event_type, (risk, desc, rec) in AUDIT_RISK_MAP.items():
            if RISK_ORDER.get(risk, 99) > RISK_ORDER.get("MEDIUM", 2):
                continue
            subset = df[df["event_type"] == event_type]
            if subset.empty:
                continue

            extra = ""
            if event_type == "sec_policy.create" and "workloads_affected" in subset.columns:
                total = int(pd.to_numeric(subset["workloads_affected"], errors="coerce").fillna(0).sum())
                if total:
                    extra = f" Total workloads affected: {total}."

            attention_items.append({
                "risk": risk,
                "event_type": event_type,
                "count": len(subset),
                "summary": desc + extra,
                "actors": _non_empty_values(subset, "actor") or _non_empty_values(subset, "created_by"),
                "targets": _non_empty_values(subset, "target_name"),
                "resources": _non_empty_values(subset, "resource_name"),
                "src_ips": _non_empty_values(subset, "src_ip"),
                "recommendation": rec,
            })

    attention_items.sort(key=lambda item: RISK_ORDER.get(item["risk"], 99))

    attack_items = []
    for item in attention_items:
        event_type = str(item.get("event_type", "") or "")
        risk = str(item.get("risk", "INFO") or "INFO")
        severity = "CRITICAL" if risk == "CRITICAL" else ("HIGH" if risk == "HIGH" else ("MEDIUM" if risk == "MEDIUM" else "LOW"))
        count = int(item.get("count", 0) or 0)

        finding_kind = "blind_spot"
        attack_stage = "exposure"
        action_code = "MOVE_TO_ENFORCEMENT"

        if event_type.startswith("sec_policy."):
            finding_kind = "boundary_breach"
            attack_stage = "control_plane"
            action_code = "REVIEW_HIGH_IMPACT_PROVISIONS"
        elif "authentication_failed" in event_type or "login" in event_type:
            finding_kind = "suspicious_pivot"
            attack_stage = "initial_access"
            action_code = "HARDEN_AUTH_CHANNELS"
        elif event_type.startswith("agent."):
            finding_kind = "suspicious_pivot"
            attack_stage = "pivot"
            action_code = "RESTRICT_TRANSIT_NODE_ACCESS"

        if event_type.startswith("sec_policy.") and "workloads affected" in str(item.get("summary", "")).lower():
            finding_kind = "blast_radius"
            attack_stage = "blast_radius"

        attack_items.append(
            make_posture_item(
                scope="audit_report",
                framework="microseg_attack",
                app="audit",
                env="global",
                finding_kind=finding_kind,
                attack_stage=attack_stage,
                confidence="high" if count >= 3 else "medium",
                recommended_action_code=action_code,
                severity=severity,
                evidence={
                    "event_type": event_type,
                    "count": count,
                    "actors": item.get("actors", []),
                    "src_ips": item.get("src_ips", []),
                },
            )
        )

    unknown_count = 0
    parser_note_rows = 0
    if "known_event_type" in df.columns:
        unknown_count = int((~df["known_event_type"].fillna(False)).sum())
    if "parser_note_count" in df.columns:
        parser_note_rows = int((pd.to_numeric(df["parser_note_count"], errors="coerce").fillna(0) > 0).sum())
    if unknown_count > 0:
        attack_items.append(
            make_posture_item(
                scope="audit_report",
                framework="microseg_attack",
                app="audit",
                env="global",
                finding_kind="blind_spot",
                attack_stage="exposure",
                confidence="medium",
                recommended_action_code="ONBOARD_UNMANAGED",
                severity="HIGH" if unknown_count >= 5 else "MEDIUM",
                evidence={"unknown_event_types": unknown_count},
            )
        )
    if parser_note_rows > 0:
        attack_items.append(
            make_posture_item(
                scope="audit_report",
                framework="microseg_attack",
                app="audit",
                env="global",
                finding_kind="blind_spot",
                attack_stage="control_plane",
                confidence="medium",
                recommended_action_code="RESOLVE_QUERY_FAILURES",
                severity="MEDIUM",
                evidence={"parser_note_rows": parser_note_rows},
            )
        )

    ranked_attack_items = rank_posture_items(attack_items)
    attack_sections = summarize_attack_posture(ranked_attack_items, top_n=5)

    return {
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "kpis": kpis,
        "top_events_overall": top_events,
        "severity_distribution": severity_dist,
        "attention_items": attention_items,
        "attack_posture_items": ranked_attack_items,
        "boundary_breaches": attack_sections["boundary_breaches"],
        "suspicious_pivot_behavior": attack_sections["suspicious_pivot_behavior"],
        "blast_radius": attack_sections["blast_radius"],
        "blind_spots": attack_sections["blind_spots"],
        "action_matrix": attack_sections["action_matrix"],
    }
