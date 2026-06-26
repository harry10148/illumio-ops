"""Draft policy decision summary: 7-subtype counts + top workload pairs per subtype."""
import pandas as pd

DRAFT_SUBTYPES = [
    "allowed",
    "potentially_blocked",
    "blocked_by_boundary",
    "blocked_by_override_deny",
    "potentially_blocked_by_boundary",
    "potentially_blocked_by_override_deny",
    "allowed_across_boundary",
]

_CHART_TITLE_KEY = "rpt_draft_summary_chart_title"


def analyze(flows_df: pd.DataFrame) -> dict:
    if "draft_policy_decision" not in flows_df.columns:
        return {"skipped": True, "reason": "no draft_policy_decision column"}

    raw_counts = flows_df["draft_policy_decision"].value_counts().to_dict()
    counts = {s: int(raw_counts.get(s, 0)) for s in DRAFT_SUBTYPES}

    # The unified DataFrame uses src_ip/dst_ip; older callers pass src/dst.
    # Resolve like R05DraftReportedMismatch, then emit canonical src/dst keys.
    src_col = "src" if "src" in flows_df.columns else "src_ip"
    dst_col = "dst" if "dst" in flows_df.columns else "dst_ip"

    top_pairs: dict = {}
    for subtype in DRAFT_SUBTYPES:
        mask = flows_df["draft_policy_decision"] == subtype
        if not mask.any():
            continue
        top_pairs[subtype] = (
            flows_df[mask]
            .groupby([src_col, dst_col])
            .size()
            .sort_values(ascending=False)
            .head(10)
            .reset_index(name="flows")
            .rename(columns={src_col: "src", dst_col: "dst"})
            .to_dict("records")
        )

    return {
        "counts": counts,
        "top_pairs_by_subtype": top_pairs,
        "chart_spec": _build_chart_spec(counts),
    }


def _build_chart_spec(counts: dict) -> dict:
    return {
        "kind": "bar",
        "title_key": _CHART_TITLE_KEY,
        "categories": DRAFT_SUBTYPES,
        "values": [counts.get(s, 0) for s in DRAFT_SUBTYPES],
    }
