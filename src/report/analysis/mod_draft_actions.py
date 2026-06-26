"""Actionable analysis for draft_policy_decision sub-categories that need
human review or remediation: Override Deny, Allowed Across Boundary, what-if.

Distinct from mod_draft_summary (B2.2) which only counts and lists top pairs.
"""
from __future__ import annotations

import pandas as pd


def _pair_cols(flows_df: pd.DataFrame) -> tuple[str, str]:
    """Resolve the src/dst columns. The unified DataFrame uses src_ip/dst_ip;
    older callers pass src/dst. Mirrors R05DraftReportedMismatch."""
    src_col = "src" if "src" in flows_df.columns else "src_ip"
    dst_col = "dst" if "dst" in flows_df.columns else "dst_ip"
    return src_col, dst_col


def _top_pairs(sub: pd.DataFrame, src_col: str, dst_col: str) -> list[dict]:
    """Top (src, dst, port) flow groups, emitted with canonical src/dst keys."""
    return (sub.groupby([src_col, dst_col, "port"]).size()
            .sort_values(ascending=False).head(20)
            .reset_index(name="flows")
            .rename(columns={src_col: "src", dst_col: "dst"})
            .to_dict("records"))


def analyze(flows_df: pd.DataFrame) -> dict:
    if "draft_policy_decision" not in flows_df.columns:
        return {"skipped": True, "reason": "no draft_policy_decision column"}
    return {
        "override_deny": _override_deny_block(flows_df),
        "potentially_blocked_by_override_deny": _potentially_override_deny_block(flows_df),
        "allowed_across_boundary": _allowed_across_boundary_block(flows_df),
        "what_if_summary": _what_if_summary(flows_df),
    }


def _override_deny_block(flows_df):
    src_col, dst_col = _pair_cols(flows_df)
    mask = flows_df["draft_policy_decision"] == "blocked_by_override_deny"
    top = _top_pairs(flows_df[mask], src_col, dst_col)
    return {
        "count": int(mask.sum()),
        "top_pairs": top,
        "remediation": _remediation_for_override_deny(top),
    }


def _potentially_override_deny_block(flows_df):
    src_col, dst_col = _pair_cols(flows_df)
    mask = flows_df["draft_policy_decision"] == "potentially_blocked_by_override_deny"
    top = _top_pairs(flows_df[mask], src_col, dst_col)
    return {"count": int(mask.sum()), "top_pairs": top}


def _allowed_across_boundary_block(flows_df):
    src_col, dst_col = _pair_cols(flows_df)
    mask = flows_df["draft_policy_decision"] == "allowed_across_boundary"
    top = _top_pairs(flows_df[mask], src_col, dst_col)
    return {
        "count": int(mask.sum()),
        "top_pairs": top,
        "review_workflow": _build_review_workflow(top),
    }


def _what_if_summary(flows_df):
    if "policy_decision" not in flows_df.columns:
        return {"skipped": True}
    same = (flows_df["policy_decision"] == flows_df["draft_policy_decision"])
    differ = ~same
    return {
        "total": len(flows_df),
        "would_change": int(differ.sum()),
        "would_change_share": (float(differ.sum()) / len(flows_df)) if len(flows_df) else 0.0,
    }


def _remediation_for_override_deny(top_pairs):
    return [{
        "action_code": "REVIEW_OVERRIDE_DENY",
        "description_key": "rpt_draft_actions_remediate_override_deny",
        "src": p["src"], "dst": p["dst"], "port": p["port"], "flows": p["flows"],
    } for p in top_pairs]


def _build_review_workflow(top_pairs):
    return [{
        "step": "verify_intent",
        "description_key": "rpt_draft_actions_aab_verify_intent",
        "pair": p,
    } for p in top_pairs]
