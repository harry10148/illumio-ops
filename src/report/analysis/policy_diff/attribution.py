"""Operator attribution for the policy diff.

PURE derivation: decorates each diff row with the most-recent matching audit
event (last_actor / last_changed / last_event). The event source is the output
of audit_policy_changes(df) — specifically its ``draft_events`` DataFrame, whose
columns include resource_name / actor / timestamp / event_type.

Matching is by OBJECT NAME (audit events carry ``resource_name``, not a
href-bearing id). The most recent event per name wins. Names that the event
window does not cover stay blank — a known limitation of live diff.
"""
from __future__ import annotations

import pandas as pd


def _latest_by_name(policy_events: dict) -> dict:
    """name -> {actor, timestamp, event_type} for the most recent event per name."""
    if not isinstance(policy_events, dict):
        return {}
    df = policy_events.get("draft_events")
    if not isinstance(df, pd.DataFrame) or df.empty or "resource_name" not in df.columns:
        return {}
    work = df.copy()
    if "timestamp" not in work.columns:
        work["timestamp"] = ""
    work = work.sort_values("timestamp", ascending=True)  # last row per name = newest
    latest: dict = {}
    for _, row in work.iterrows():
        name = str(row.get("resource_name", "")).strip()
        if not name:
            continue
        latest[name] = {
            "actor": str(row.get("actor", "") or ""),
            "timestamp": str(row.get("timestamp", "") or ""),
            "event_type": str(row.get("event_type", "") or ""),
        }
    return latest


def _apply(df: pd.DataFrame, latest: dict) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    df = df.copy()
    for idx, row in df.iterrows():
        hit = latest.get(str(row.get("ruleset_name", "")).strip())
        if hit:
            df.at[idx, "last_actor"] = hit["actor"]
            df.at[idx, "last_changed"] = hit["timestamp"]
            df.at[idx, "last_event"] = hit["event_type"]
    return df


def attribute_changes(diff: dict, policy_events: dict) -> dict:
    latest = _latest_by_name(policy_events)
    diff["ruleset_changes"] = _apply(diff.get("ruleset_changes"), latest)
    diff["rule_changes"] = _apply(diff.get("rule_changes"), latest)
    return diff
