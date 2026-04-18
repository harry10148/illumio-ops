"""Module 4: Temporal event correlation for attack chain detection.

Detects suspicious event sequences within configurable time windows:
  - Failed logins followed by high-risk policy changes (credential compromise → privilege escalation)
  - Agent tampering/offline events followed by policy provisions (cover-up pattern)
  - Burst of failed logins from same source IP (brute force)
  - Off-hours high-risk operations (policy changes outside business hours)
"""
from __future__ import annotations

import pandas as pd

_AUTH_FAILURE_EVENTS = frozenset({
    "request.authentication_failed",
    "request.authorization_failed",
    "user.use_expired_password",
})

_HIGH_RISK_POLICY_EVENTS = frozenset({
    "sec_policy.create",
    "sec_policy.delete",
    "workloads.unpair",
    "agents.unpair",
    "authentication_settings.update",
    "firewall_settings.update",
    "api_key.create",
    "api_key.delete",
})

_AGENT_SECURITY_EVENTS = frozenset({
    "agent.tampering",
    "agent.clone_detected",
    "agent.suspend",
})

_BUSINESS_HOURS = range(8, 19)  # 08:00–18:59 local time

def _parse_ts(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure timestamp column is datetime and sorted."""
    work = df.copy()
    if "timestamp" not in work.columns:
        return work
    work["_ts"] = pd.to_datetime(work["timestamp"], errors="coerce", utc=True)
    return work.dropna(subset=["_ts"]).sort_values("_ts")

def _actor_key(row) -> str:
    """Best-effort actor identifier from available columns."""
    for col in ("actor", "created_by", "target_name"):
        val = str(row.get(col, "") or "").strip()
        if val and val.lower() not in ("", "none", "nan"):
            return val
    return ""

def audit_event_correlation(df: pd.DataFrame, window_minutes: int = 30) -> dict:
    """Find temporally correlated suspicious event sequences."""
    if df.empty or "event_type" not in df.columns or "timestamp" not in df.columns:
        return {"error": "No event data with timestamps available"}

    work = _parse_ts(df)
    if work.empty:
        return {"error": "No parseable timestamps in event data"}

    window = pd.Timedelta(minutes=window_minutes)
    correlated_sequences: list[dict] = []

    # Pattern 1: Failed login → High-risk policy change (same actor or IP)
    auth_failures = work[work["event_type"].isin(_AUTH_FAILURE_EVENTS)].copy()
    policy_changes = work[work["event_type"].isin(_HIGH_RISK_POLICY_EVENTS)].copy()

    if not auth_failures.empty and not policy_changes.empty:
        for _, fail_row in auth_failures.iterrows():
            fail_ts = fail_row["_ts"]
            fail_ip = str(fail_row.get("src_ip", "")).strip()
            fail_actor = _actor_key(fail_row)

            # Find policy changes within window AFTER the failure
            candidates = policy_changes[
                (policy_changes["_ts"] > fail_ts)
                & (policy_changes["_ts"] <= fail_ts + window)
            ]
            if candidates.empty:
                continue

            for _, change_row in candidates.iterrows():
                change_ip = str(change_row.get("src_ip", "")).strip()
                change_actor = _actor_key(change_row)

                # Match on IP or actor
                ip_match = fail_ip and change_ip and fail_ip == change_ip
                actor_match = fail_actor and change_actor and fail_actor == change_actor
                if not ip_match and not actor_match:
                    continue

                correlated_sequences.append({
                    "Pattern": "Auth Failure → Policy Change",
                    "Risk": "CRITICAL",
                    "Trigger Event": fail_row["event_type"],
                    "Trigger Time": str(fail_row.get("timestamp", "")),
                    "Follow-up Event": change_row["event_type"],
                    "Follow-up Time": str(change_row.get("timestamp", "")),
                    "Gap (min)": round((change_row["_ts"] - fail_ts).total_seconds() / 60, 1),
                    "Matched On": "IP" if ip_match else "Actor",
                    "Actor / IP": fail_ip if ip_match else fail_actor,
                })

    # Pattern 2: Agent security event → Policy provision (cover-up)
    agent_events = work[work["event_type"].isin(_AGENT_SECURITY_EVENTS)].copy()
    provisions = work[work["event_type"].isin({"sec_policy.create", "sec_policy.delete"})].copy()

    if not agent_events.empty and not provisions.empty:
        for _, agent_row in agent_events.iterrows():
            agent_ts = agent_row["_ts"]
            candidates = provisions[
                (provisions["_ts"] > agent_ts)
                & (provisions["_ts"] <= agent_ts + window)
            ]
            for _, prov_row in candidates.iterrows():
                correlated_sequences.append({
                    "Pattern": "Agent Security → Policy Change",
                    "Risk": "HIGH",
                    "Trigger Event": agent_row["event_type"],
                    "Trigger Time": str(agent_row.get("timestamp", "")),
                    "Follow-up Event": prov_row["event_type"],
                    "Follow-up Time": str(prov_row.get("timestamp", "")),
                    "Gap (min)": round((prov_row["_ts"] - agent_ts).total_seconds() / 60, 1),
                    "Matched On": "Temporal",
                    "Actor / IP": _actor_key(prov_row) or _actor_key(agent_row),
                })

    # Pattern 3: Brute force detection (≥5 auth failures from same IP within window)
    brute_force_rows: list[dict] = []
    if not auth_failures.empty and "src_ip" in auth_failures.columns:
        ip_groups = auth_failures.groupby(
            auth_failures["src_ip"].astype(str).str.strip()
        )
        for src_ip, group in ip_groups:
            if not src_ip or src_ip in ("", "nan", "None"):
                continue
            sorted_group = group.sort_values("_ts")
            # Sliding window: count events within each window
            ts_list = sorted_group["_ts"].tolist()
            for i, ts in enumerate(ts_list):
                count_in_window = sum(
                    1 for t in ts_list[i:] if t <= ts + window
                )
                if count_in_window >= 5:
                    targets = sorted_group[
                        (sorted_group["_ts"] >= ts)
                        & (sorted_group["_ts"] <= ts + window)
                    ]
                    actors = targets.apply(_actor_key, axis=1).unique().tolist()
                    brute_force_rows.append({
                        "Source IP": str(src_ip),
                        "Failures in Window": count_in_window,
                        "Window Start": str(targets.iloc[0].get("timestamp", "")),
                        "Window End": str(targets.iloc[-1].get("timestamp", "")),
                        "Target Accounts": ", ".join(a for a in actors[:5] if a),
                    })
                    break  # one detection per IP

    # Pattern 4: Off-hours high-risk operations
    off_hours_rows: list[dict] = []
    high_risk_all = work[work["event_type"].isin(_HIGH_RISK_POLICY_EVENTS)].copy()
    if not high_risk_all.empty:
        high_risk_all["_hour"] = high_risk_all["_ts"].dt.hour
        off_hours = high_risk_all[~high_risk_all["_hour"].isin(_BUSINESS_HOURS)]
        if not off_hours.empty:
            for _, row in off_hours.head(20).iterrows():
                off_hours_rows.append({
                    "Event Type": row["event_type"],
                    "Timestamp": str(row.get("timestamp", "")),
                    "Hour (UTC)": int(row["_hour"]),
                    "Actor": _actor_key(row),
                    "Source IP": str(row.get("src_ip", "")),
                })

    # Deduplicate correlated sequences
    seen = set()
    deduped = []
    for seq in correlated_sequences:
        key = (seq["Trigger Event"], seq["Trigger Time"], seq["Follow-up Event"], seq["Follow-up Time"])
        if key not in seen:
            seen.add(key)
            deduped.append(seq)

    # Sort by risk
    risk_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2}
    deduped.sort(key=lambda x: risk_order.get(x.get("Risk", "MEDIUM"), 9))

    return {
        "correlated_sequences": pd.DataFrame(deduped[:30]) if deduped else pd.DataFrame(),
        "total_correlations": len(deduped),
        "brute_force_detections": pd.DataFrame(brute_force_rows[:20]) if brute_force_rows else pd.DataFrame(),
        "total_brute_force": len(brute_force_rows),
        "off_hours_operations": pd.DataFrame(off_hours_rows[:20]) if off_hours_rows else pd.DataFrame(),
        "total_off_hours": len(off_hours_rows),
        "window_minutes": window_minutes,
    }
