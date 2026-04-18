"""Shared builders for dashboard summary JSON artifacts."""
from __future__ import annotations

import datetime
import json
import os

def _records_from_table(table, limit: int = 10) -> list[dict]:
    try:
        if table is None:
            return []
        if hasattr(table, "head") and hasattr(table, "to_dict"):
            return table.head(limit).to_dict(orient="records")
    except Exception:
        return []
    return []

def build_audit_dashboard_summary(result) -> dict:
    mod00 = result.module_results.get("mod00", {}) if result else {}
    mod01 = result.module_results.get("mod01", {}) if result else {}
    mod03 = result.module_results.get("mod03", {}) if result else {}
    attention_items = []
    for item in (mod00.get("attention_items") or [])[:5]:
        attention_items.append(
            {
                "risk": item.get("risk", "INFO"),
                "event_type": item.get("event_type", ""),
                "count": int(item.get("count", 0) or 0),
                "summary": item.get("summary", ""),
                "recommendation": item.get("recommendation", ""),
            }
        )

    return {
        "generated_at": mod00.get("generated_at")
        or getattr(result, "generated_at", datetime.datetime.now()).strftime("%Y-%m-%d %H:%M:%S"),
        "record_count": int(getattr(result, "record_count", 0) or 0),
        "date_range": list(getattr(result, "date_range", ("", "")) or ("", "")),
        "kpis": mod00.get("kpis", [])[:8],
        "attention_items": attention_items,
        "top_events": _records_from_table(mod00.get("top_events_overall"), limit=10),
        "boundary_breaches": list(mod00.get("boundary_breaches", [])[:5]),
        "suspicious_pivot_behavior": list(mod00.get("suspicious_pivot_behavior", [])[:5]),
        "blast_radius": list(mod00.get("blast_radius", [])[:5]),
        "blind_spots": list(mod00.get("blind_spots", [])[:5]),
        "action_matrix": list(mod00.get("action_matrix", [])[:5]),
        "health": {
            "total_health_events": int(mod01.get("total_health_events", 0) or 0),
            "security_concern_count": int(mod01.get("security_concern_count", 0) or 0),
            "connectivity_event_count": int(mod01.get("connectivity_event_count", 0) or 0),
        },
        "policy": {
            "provision_count": int(mod03.get("provision_count", 0) or 0),
            "rule_change_count": int(mod03.get("rule_change_count", 0) or 0),
            "high_risk_count": int(mod03.get("high_risk_count", 0) or 0),
            "total_workloads_affected": int(mod03.get("total_workloads_affected", 0) or 0),
        },
    }

def write_audit_dashboard_summary(output_dir: str, result) -> str:
    os.makedirs(output_dir, exist_ok=True)
    summary_path = os.path.join(output_dir, "latest_audit_summary.json")
    summary = build_audit_dashboard_summary(result)
    with open(summary_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    return summary_path

def build_policy_usage_dashboard_summary(result) -> dict:
    mod00 = result.module_results.get("mod00", {}) if result else {}
    execution = getattr(result, "execution_stats", {}) or mod00.get("execution_stats", {}) or {}

    def _detail_rows(items, limit=5):
        rows = []
        for item in (items or [])[:limit]:
            rows.append(
                {
                    "rule_href": item.get("rule_href", ""),
                    "rule_no": item.get("rule_no", ""),
                    "rule_id": item.get("rule_id", ""),
                    "ruleset_name": item.get("ruleset_name", ""),
                    "description": item.get("description", ""),
                    "status": item.get("status", ""),
                }
            )
        return rows

    return {
        "generated_at": mod00.get("generated_at")
        or getattr(result, "generated_at", datetime.datetime.now()).strftime("%Y-%m-%d %H:%M:%S"),
        "record_count": int(getattr(result, "record_count", 0) or 0),
        "date_range": list(getattr(result, "date_range", ("", "")) or ("", "")),
        "kpis": mod00.get("kpis", [])[:8],
        "execution_stats": execution,
        "execution_notes": mod00.get("execution_notes", [])[:5],
        "boundary_breaches": list(mod00.get("boundary_breaches", [])[:5]),
        "suspicious_pivot_behavior": list(mod00.get("suspicious_pivot_behavior", [])[:5]),
        "blast_radius": list(mod00.get("blast_radius", [])[:5]),
        "blind_spots": list(mod00.get("blind_spots", [])[:5]),
        "action_matrix": list(mod00.get("action_matrix", [])[:5]),
        "top_hit_ports": (execution.get("top_hit_ports") or [])[:10],
        "reused_rule_details": _detail_rows(execution.get("reused_rule_details"), limit=5),
        "pending_rule_details": _detail_rows(execution.get("pending_rule_details"), limit=5),
        "failed_rule_details": _detail_rows(execution.get("failed_rule_details"), limit=5),
    }

def write_policy_usage_dashboard_summary(output_dir: str, result) -> str:
    os.makedirs(output_dir, exist_ok=True)
    summary_path = os.path.join(output_dir, "latest_policy_usage_summary.json")
    summary = build_policy_usage_dashboard_summary(result)
    with open(summary_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    return summary_path

