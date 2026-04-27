"""Enforcement Rollout Plan: rank apps for moving to enforcement."""
from __future__ import annotations

import pandas as pd


def analyze(flows_df: pd.DataFrame, *, draft_summary: dict | None = None,
            readiness_summary: dict | None = None) -> dict:
    if "dst_app" not in flows_df.columns and "src_app" not in flows_df.columns:
        return {"skipped": True, "reason": "no app labels"}

    apps = sorted(set(flows_df.get("dst_app", pd.Series(dtype=object)).dropna().unique())
                  | set(flows_df.get("src_app", pd.Series(dtype=object)).dropna().unique()))

    rows = []
    for app in apps:
        mask = (flows_df.get("src_app") == app) | (flows_df.get("dst_app") == app)
        app_flows = flows_df[mask]
        total = len(app_flows)
        if total == 0:
            continue
        allowed = int((app_flows["policy_decision"] == "allowed").sum())
        pb = int((app_flows["policy_decision"] == "potentially_blocked").sum())
        blocked = int((app_flows["policy_decision"] == "blocked").sum())
        readiness = (allowed / total) if total else 0.0
        risk_penalty = (pb / total) if total else 0.0
        score = readiness - risk_penalty
        rows.append({
            "app": app,
            "_score": round(score, 4),
            "priority": 0,
            "why_now": _why_now(allowed, pb, blocked, total),
            "expected_default_deny_impact": pb,
            "required_allow_rules": _required_allows(app_flows),
            "risk_reduction": _risk_reduction(app_flows),
        })
    rows.sort(key=lambda r: r["_score"], reverse=True)
    for i, r in enumerate(rows, start=1):
        r["priority"] = i
    return {
        "ranked": rows,
        "top3_callout": rows[:3],
    }


def _why_now(allowed, pb, blocked, total):
    if pb == 0:
        return "all_flows_have_policy"
    if pb / max(total, 1) > 0.3:
        return "high_pb_share"
    if blocked > 0:
        return "active_block_signal"
    return "ready_with_minor_gaps"


def _required_allows(app_flows):
    pb_mask = app_flows["policy_decision"] == "potentially_blocked"
    if not pb_mask.any():
        return 0
    pb_pairs = app_flows[pb_mask].groupby(["src", "dst", "port"]).size()
    return int(len(pb_pairs))


def _risk_reduction(app_flows):
    return int((app_flows["policy_decision"] == "potentially_blocked").sum())
