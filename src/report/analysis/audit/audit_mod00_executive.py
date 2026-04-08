"""Module 0: Executive summary for the audit report."""

from __future__ import annotations

import datetime

import pandas as pd

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

    return {
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "kpis": kpis,
        "top_events_overall": top_events,
        "severity_distribution": severity_dist,
        "attention_items": attention_items,
    }
