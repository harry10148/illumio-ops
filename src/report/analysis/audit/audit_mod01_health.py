"""Module 1: System health and agent status."""

from __future__ import annotations

import pandas as pd

_HEALTH_EVENTS = [
    "system_health",
    "system_task.agent_missed_heartbeats_check",
    "system_task.agent_offline_check",
    "lost_agent.found",
    "agent.suspend",
    "agent.clone_detected",
    "agent.tampering",
    "agent.update",
    "agent.activate",
    "agent.deactivate",
    "agent.goodbye",
    "agent.service_not_available",
    "agent.unsuspend",
]

_SECURITY_CONCERN_EVENTS = {
    "agent.suspend",
    "agent.tampering",
    "agent.clone_detected",
    "agent.service_not_available",
}

_CONNECTIVITY_EVENTS = {
    "system_task.agent_missed_heartbeats_check",
    "system_task.agent_offline_check",
    "lost_agent.found",
    "agent.goodbye",
    "agent.deactivate",
    "agent.activate",
}

_CONTEXT_COLS = (
    "actor",
    "target_name",
    "resource_name",
    "action",
    "agent_hostname",
    "src_ip",
    "notification_detail",
    "parser_notes",
)

def _meaningful(df: pd.DataFrame, column: str) -> bool:
    return column in df.columns and df[column].astype(str).str.strip().ne("").any()

def _select_cols(df: pd.DataFrame, base_cols: list[str]) -> list[str]:
    cols = list(base_cols)
    for column in ("status",):
        if column in df.columns and column not in cols:
            cols.append(column)

    actor_column = "actor" if _meaningful(df, "actor") else "created_by"
    if actor_column in df.columns and actor_column not in cols:
        cols.append(actor_column)

    for column in _CONTEXT_COLS:
        if column not in cols and _meaningful(df, column):
            cols.append(column)
    return cols

def audit_system_health(df: pd.DataFrame) -> dict:
    if df.empty or "event_type" not in df.columns:
        return {"error": "No event data available"}

    target_df = df[df["event_type"].isin(_HEALTH_EVENTS)].copy()
    if target_df.empty:
        return {
            "total_health_events": 0,
            "security_concern_count": 0,
            "connectivity_event_count": 0,
            "summary": pd.DataFrame(),
            "severity_breakdown": pd.DataFrame(),
            "connectivity_events": pd.DataFrame(),
            "security_concerns": pd.DataFrame(),
            "recent": pd.DataFrame(),
        }

    summary = target_df["event_type"].value_counts().reset_index()
    summary.columns = ["Event Type", "Count"]

    severity_breakdown = pd.DataFrame()
    if "severity" in target_df.columns:
        severity_breakdown = (
            target_df.groupby(["event_type", "severity"])
            .size()
            .reset_index(name="Count")
            .sort_values(["event_type", "Count"], ascending=[True, False])
        )
        severity_breakdown.columns = ["Event Type", "Severity", "Count"]

    conn_df = target_df[target_df["event_type"].isin(_CONNECTIVITY_EVENTS)]
    connectivity_events = pd.DataFrame()
    if not conn_df.empty:
        cols = _select_cols(conn_df, ["timestamp", "event_type", "severity"])
        connectivity_events = conn_df[cols].sort_values("timestamp", ascending=False).head(30)

    sec_df = target_df[target_df["event_type"].isin(_SECURITY_CONCERN_EVENTS)]
    security_concerns = pd.DataFrame()
    if not sec_df.empty:
        cols = _select_cols(sec_df, ["timestamp", "event_type", "severity"])
        security_concerns = sec_df[cols].sort_values("timestamp", ascending=False).head(30)

    recent_cols = _select_cols(target_df, ["timestamp", "event_type", "severity"])
    recent = target_df[recent_cols].sort_values("timestamp", ascending=False).head(50)

    return {
        "total_health_events": len(target_df),
        "security_concern_count": len(sec_df),
        "connectivity_event_count": len(conn_df),
        "summary": summary,
        "severity_breakdown": severity_breakdown,
        "connectivity_events": connectivity_events,
        "security_concerns": security_concerns,
        "recent": recent,
    }
