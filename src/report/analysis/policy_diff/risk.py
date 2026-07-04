# src/report/analysis/policy_diff/risk.py
"""Risk grading for policy-diff rows.

PURE post-processing: adds a ``risk`` column (HIGH / MEDIUM / "") to the
ruleset_changes / rule_changes DataFrames. Microsegmentation-governance
heuristics:

  HIGH   — a ruleset or rule is being DISABLED in draft while ACTIVE has it
           enabled. Disabling e.g. a Quarantine ruleset silently removes
           containment when provisioned.
  MEDIUM — a ruleset or rule is being re-enabled, or removed entirely.
  ""     — everything else (informational).

Also grades the object tables (ip_list_changes / service_changes /
label_group_changes, if present): removed → MEDIUM; modified with
scope_expanded and hit in ``object_refs`` (allow-rule reference counts from
``scan_object_refs``) → HIGH; otherwise "".
"""
from __future__ import annotations

import pandas as pd


def _grade_row(row: pd.Series) -> str:
    change = str(row.get("change_type", ""))
    field = str(row.get("field", ""))
    draft = str(row.get("draft_value", ""))
    active = str(row.get("active_value", ""))
    if change == "modified" and field == "enabled":
        if draft == "False" and active == "True":
            return "HIGH"
        if draft == "True" and active == "False":
            return "MEDIUM"
    if change == "removed":
        return "MEDIUM"
    return ""


def _apply(df: pd.DataFrame | None) -> pd.DataFrame | None:
    if df is None or df.empty:
        return df
    df = df.copy()
    df["risk"] = df.apply(_grade_row, axis=1)
    return df


_OBJECT_TABLES = ("ip_list_changes", "service_changes", "label_group_changes")


def _grade_object_row(row: pd.Series, refs: dict) -> str:
    change = str(row.get("change_type", ""))
    if change == "removed":
        return "MEDIUM"
    if change == "modified" and bool(row.get("scope_expanded")):
        key = f"{row.get('object_kind', '')}:{row.get('object_id', '')}"
        if refs.get(key, 0) > 0:
            return "HIGH"
    return ""


def grade_changes(diff: dict, *, object_refs: dict | None = None) -> dict:
    diff["ruleset_changes"] = _apply(diff.get("ruleset_changes"))
    diff["rule_changes"] = _apply(diff.get("rule_changes"))
    refs = object_refs or {}
    for key in _OBJECT_TABLES:
        df = diff.get(key)
        if isinstance(df, pd.DataFrame) and not df.empty:
            df = df.copy()
            df["risk"] = df.apply(lambda r: _grade_object_row(r, refs), axis=1)
            diff[key] = df
    return diff
