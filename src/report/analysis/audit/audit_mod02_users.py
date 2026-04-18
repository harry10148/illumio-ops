"""Module 2: User activity and authentication."""

from __future__ import annotations

import pandas as pd

_USER_EVENTS = [
    "user.sign_in",
    "user.login",
    "user.authenticate",
    "user.sign_out",
    "user.logout",
    "user.create",
    "user.delete",
    "user.update",
    "user.reset_password",
    "user.update_password",
    "user.use_expired_password",
    "user.invite",
    "user.accept_invitation",
    "request.authentication_failed",
    "request.authorization_failed",
]

_ALWAYS_FAILURE_EVENTS = {
    "request.authentication_failed",
    "request.authorization_failed",
}

def _meaningful(df: pd.DataFrame, column: str) -> bool:
    return column in df.columns and df[column].astype(str).str.strip().ne("").any()

def _principal_series(df: pd.DataFrame) -> pd.Series:
    if _meaningful(df, "target_name"):
        principal = df["target_name"].fillna("").astype(str).str.strip()
        fallback_column = "actor" if "actor" in df.columns else "created_by"
        if fallback_column in df.columns:
            fallback = df[fallback_column].fillna("").astype(str).str.strip()
            principal = principal.mask(principal.eq(""), fallback)
        return principal

    fallback_column = "actor" if "actor" in df.columns else "created_by"
    if fallback_column in df.columns:
        return df[fallback_column].fillna("").astype(str).str.strip()
    return pd.Series([""] * len(df), index=df.index, dtype="object")

def audit_user_activity(df: pd.DataFrame) -> dict:
    if df.empty or "event_type" not in df.columns:
        return {"error": "No event data available"}

    target_df = df[df["event_type"].isin(_USER_EVENTS)].copy()
    if target_df.empty:
        return {
            "total_user_events": 0,
            "failed_logins": 0,
            "unique_src_ips": 0,
            "summary": pd.DataFrame(),
            "per_user": pd.DataFrame(),
            "failed_login_detail": pd.DataFrame(),
            "recent": pd.DataFrame(),
        }

    if "status" in target_df.columns:
        fail_mask = (
            target_df["event_type"].isin(_ALWAYS_FAILURE_EVENTS)
            | target_df["status"].astype(str).str.lower().eq("failure")
        )
    else:
        fail_mask = target_df["event_type"].isin(_ALWAYS_FAILURE_EVENTS)
    failed_logins = int(fail_mask.sum())

    unique_src_ips = 0
    if "src_ip" in target_df.columns:
        non_empty = target_df["src_ip"].astype(str).str.strip().replace("", pd.NA).dropna()
        unique_src_ips = int(non_empty.nunique())

    summary = target_df["event_type"].value_counts().reset_index()
    summary.columns = ["Event Type", "Count"]

    target_df["_is_failure"] = fail_mask
    target_df["_principal"] = _principal_series(target_df)

    per_user = pd.DataFrame()
    if target_df["_principal"].astype(str).str.strip().ne("").any():
        user_stats = (
            target_df.groupby("_principal")
            .agg(
                Total=("event_type", "size"),
                Failures=("_is_failure", "sum"),
            )
            .reset_index()
        )
        user_stats.columns = ["User", "Total Events", "Failures"]
        user_stats["Failures"] = user_stats["Failures"].astype(int)

        if "src_ip" in target_df.columns:
            ip_counts = (
                target_df[target_df["src_ip"].astype(str).str.strip() != ""]
                .groupby("_principal")["src_ip"]
                .nunique()
                .reset_index()
            )
            ip_counts.columns = ["User", "Source IPs"]
            user_stats = user_stats.merge(ip_counts, on="User", how="left")
            user_stats["Source IPs"] = user_stats["Source IPs"].fillna(0).astype(int)

        per_user = user_stats.sort_values(["Failures", "Total Events"], ascending=[False, False]).head(20)

    failed_login_detail = pd.DataFrame()
    if failed_logins > 0:
        fail_df = target_df[fail_mask]
        detail_cols = ["timestamp", "event_type"]
        for column in (
            "_principal",
            "actor",
            "supplied_username",
            "src_ip",
            "action",
            "notification_detail",
            "severity",
            "parser_notes",
        ):
            if _meaningful(fail_df, column):
                detail_cols.append(column)
        failed_login_detail = fail_df[detail_cols].rename(columns={"_principal": "user"})
        failed_login_detail = failed_login_detail.sort_values("timestamp", ascending=False).head(30)

    recent_cols = ["timestamp", "event_type", "severity"]
    for column in ("status", "_principal", "actor", "src_ip", "action", "supplied_username"):
        if _meaningful(target_df, column):
            recent_cols.append(column)
    recent = target_df[recent_cols].rename(columns={"_principal": "user"})
    recent = recent.sort_values("timestamp", ascending=False).head(50)

    return {
        "total_user_events": len(target_df),
        "failed_logins": failed_logins,
        "unique_src_ips": unique_src_ips,
        "summary": summary,
        "per_user": per_user,
        "failed_login_detail": failed_login_detail,
        "recent": recent,
    }
