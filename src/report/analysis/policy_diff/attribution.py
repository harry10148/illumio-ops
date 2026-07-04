"""Operator attribution for the policy diff.

PURE derivation: decorates each diff row with the most-recent matching audit
event (last_actor / last_changed / last_event). The event source is the output
of audit_policy_changes(df) — specifically its ``draft_events`` (rule/ruleset
tables) and ``object_events`` (ip_list/service/label_group tables) DataFrames,
whose columns include resource_name / actor / timestamp / event_type.

Matching is by OBJECT NAME (audit events carry ``resource_name``, not a
href-bearing id). The most recent event per name wins. Names that the event
window does not cover stay blank — a known limitation of live diff.
"""
from __future__ import annotations

import pandas as pd

_OBJECT_TABLES = ("ip_list_changes", "service_changes", "label_group_changes")


def _s(value) -> str:
    """Normalize None/NaN to "" before stringifying (NaN is truthy, so `or ""` alone misses it)."""
    if value is None or (isinstance(value, float) and value != value):
        return ""
    return str(value)


def _latest_by_name(events) -> dict:
    """events 為 DataFrame（draft_events 或 object_events）；防禦同前。"""
    if not isinstance(events, pd.DataFrame) or events.empty:
        return {}
    if "resource_name" not in events.columns:
        return {}
    df = events.copy()
    if "timestamp" not in df.columns:
        df["timestamp"] = ""
    df["timestamp"] = df["timestamp"].fillna("")
    df = df.sort_values("timestamp", ascending=True)
    latest = {}
    for _, row in df.iterrows():
        name = str(row.get("resource_name", "")).strip()
        if name:
            latest[name] = {
                "actor": _s(row.get("actor", "")),
                "timestamp": _s(row.get("timestamp", "")),
                "event_type": _s(row.get("event_type", "")),
            }
    return latest


def _apply(df, latest: dict, name_col: str) -> None:
    if not isinstance(df, pd.DataFrame) or df.empty or name_col not in df.columns:
        return
    for idx, row in df.iterrows():
        hit = latest.get(str(row.get(name_col, "")).strip())
        if hit:
            df.at[idx, "last_actor"] = hit["actor"]
            df.at[idx, "last_changed"] = hit["timestamp"]
            df.at[idx, "last_event"] = hit["event_type"]


def attribute_changes(diff: dict, policy_events: dict) -> dict:
    events = policy_events if isinstance(policy_events, dict) else {}
    latest_rules = _latest_by_name(events.get("draft_events"))
    if latest_rules:
        for key in ("ruleset_changes", "rule_changes"):
            _apply(diff.get(key), latest_rules, "ruleset_name")
    latest_objects = _latest_by_name(events.get("object_events"))
    if latest_objects:
        for key in _OBJECT_TABLES:
            _apply(diff.get(key), latest_objects, "name")
    return diff
