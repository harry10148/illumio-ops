"""Module 3: Policy and rule modifications."""

from __future__ import annotations

import pandas as pd

_POLICY_EVENTS = [
    "rule_set.create",
    "rule_set.update",
    "rule_sets.delete",
    "rule_set.delete",
    "sec_rule.create",
    "sec_rule.update",
    "sec_rule.delete",
    "sec_policy.create",
    "sec_policy.delete",
    "sec_policy.restore",
    "label.create",
    "label.update",
    "label.delete",
    "label_group.create",
    "label_group.update",
    "label_group.delete",
    "ip_list.create",
    "ip_list.update",
    "ip_list.delete",
    "service.create",
    "service.update",
    "service.delete",
    "enforcement_boundary.create",
    "enforcement_boundary.update",
    "enforcement_boundary.delete",
    "api_key.create",
    "api_key.update",
    "api_key.delete",
    "authentication_settings.update",
    "firewall_settings.update",
    "workloads.unpair",
    "agents.unpair",
    "pairing_profile.create",
    "pairing_profile.delete",
]

_PROVISION_EVENTS = {"sec_policy.create", "sec_policy.delete", "sec_policy.restore"}
_DRAFT_RULE_EVENTS = {
    "rule_set.create",
    "rule_set.update",
    "rule_sets.delete",
    "rule_set.delete",
    "sec_rule.create",
    "sec_rule.update",
    "sec_rule.delete",
}
_HIGH_RISK_EVENTS = {
    "workloads.unpair",
    "agents.unpair",
    "authentication_settings.update",
    "firewall_settings.update",
    "api_key.create",
    "api_key.delete",
}
_HIGH_IMPACT_THRESHOLD = 50
_CONTEXT_COLS = ("actor", "target_name", "resource_name", "action", "src_ip", "change_detail", "api_method")

def _meaningful(df: pd.DataFrame, column: str) -> bool:
    return column in df.columns and df[column].astype(str).str.strip().ne("").any()

def _select_cols(df: pd.DataFrame, base_cols: list[str], extra_cols: tuple[str, ...] = _CONTEXT_COLS) -> list[str]:
    cols = list(base_cols)
    for column in ("status",):
        if column in df.columns and column not in cols:
            cols.append(column)
    actor_column = "actor" if _meaningful(df, "actor") else "created_by"
    if actor_column in df.columns and actor_column not in cols:
        cols.append(actor_column)
    for column in extra_cols:
        if column not in cols and _meaningful(df, column):
            cols.append(column)
    return cols

def audit_policy_changes(df: pd.DataFrame) -> dict:
    if df.empty or "event_type" not in df.columns:
        return {"error": "No event data available"}

    target_df = df[df["event_type"].isin(_POLICY_EVENTS)].copy()
    if target_df.empty:
        return {
            "total_policy_events": 0,
            "provision_count": 0,
            "rule_change_count": 0,
            "high_risk_count": 0,
            "summary": pd.DataFrame(),
            "per_user": pd.DataFrame(),
            "provisions": pd.DataFrame(),
            "draft_events": pd.DataFrame(),
            "recent": pd.DataFrame(),
            "total_workloads_affected": 0,
            "max_workloads_affected": 0,
            "high_impact_provisions": [],
            "high_impact_threshold": _HIGH_IMPACT_THRESHOLD,
        }

    summary = target_df["event_type"].value_counts().reset_index()
    summary.columns = ["Event Type", "Count"]

    draft_mask = target_df["event_type"].isin(_DRAFT_RULE_EVENTS)
    rule_change_count = int(draft_mask.sum())
    draft_events = pd.DataFrame()
    if rule_change_count > 0:
        draft_df = target_df[draft_mask]
        cols = _select_cols(draft_df, ["timestamp", "event_type", "severity"], extra_cols=("resource_name", "action", "src_ip", "change_detail"))
        draft_events = draft_df[cols].sort_values("timestamp", ascending=False).head(50)

    prov_mask = target_df["event_type"].isin(_PROVISION_EVENTS)
    provision_count = int(prov_mask.sum())
    provisions = pd.DataFrame()
    total_workloads_affected = 0
    max_workloads_affected = 0
    high_impact_provisions: list[dict] = []
    if provision_count > 0:
        prov_df = target_df[prov_mask].copy()
        if "workloads_affected" not in prov_df.columns:
            prov_df["workloads_affected"] = 0
        prov_df["workloads_affected"] = pd.to_numeric(prov_df["workloads_affected"], errors="coerce").fillna(0).astype(int)

        total_workloads_affected = int(prov_df["workloads_affected"].sum())
        max_workloads_affected = int(prov_df["workloads_affected"].max())

        cols = ["timestamp", "event_type", "workloads_affected", "severity"]
        for column in ("status", "actor", "resource_name", "src_ip", "change_detail"):
            if _meaningful(prov_df, column):
                cols.append(column)
        provisions = prov_df[cols].sort_values("timestamp", ascending=False).head(30)

        high_impact_df = prov_df[prov_df["workloads_affected"] >= _HIGH_IMPACT_THRESHOLD]
        for _, row in high_impact_df.iterrows():
            high_impact_provisions.append({
                "timestamp": str(row.get("timestamp", "")),
                "event_type": str(row.get("event_type", "")),
                "workloads_affected": int(row.get("workloads_affected", 0)),
                "actor": str(row.get("actor", row.get("created_by", ""))),
                "src_ip": str(row.get("src_ip", "")),
                "resource_name": str(row.get("resource_name", "")),
                "status": str(row.get("status", "")),
            })

    high_risk_count = int(target_df["event_type"].isin(_HIGH_RISK_EVENTS).sum())

    per_user = pd.DataFrame()
    actor_column = "actor" if _meaningful(target_df, "actor") else "created_by"
    if actor_column in target_df.columns:
        user_stats = target_df.groupby(actor_column).agg(Total=("event_type", "size")).reset_index()
        user_stats.columns = ["User", "Total Changes"]
        if "src_ip" in target_df.columns:
            ip_counts = (
                target_df[target_df["src_ip"].astype(str).str.strip() != ""]
                .groupby(actor_column)["src_ip"]
                .nunique()
                .reset_index()
            )
            ip_counts.columns = ["User", "Source IPs"]
            user_stats = user_stats.merge(ip_counts, on="User", how="left")
            user_stats["Source IPs"] = user_stats["Source IPs"].fillna(0).astype(int)
        per_user = user_stats.sort_values("Total Changes", ascending=False).head(20)

    recent_cols = _select_cols(target_df, ["timestamp", "event_type", "severity"], extra_cols=("target_name", "resource_name", "action", "src_ip", "change_detail"))
    recent = target_df[recent_cols].sort_values("timestamp", ascending=False).head(50)

    return {
        "total_policy_events": len(target_df),
        "provision_count": provision_count,
        "rule_change_count": rule_change_count,
        "high_risk_count": high_risk_count,
        "total_workloads_affected": total_workloads_affected,
        "max_workloads_affected": max_workloads_affected,
        "high_impact_threshold": _HIGH_IMPACT_THRESHOLD,
        "high_impact_provisions": high_impact_provisions,
        "summary": summary,
        "per_user": per_user,
        "provisions": provisions,
        "draft_events": draft_events,
        "recent": recent,
    }
