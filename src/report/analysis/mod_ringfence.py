"""Application Ringfence: per-app dependency profile + candidate allow rules."""
from __future__ import annotations

import pandas as pd


def analyze(flows_df: pd.DataFrame, *, app: str | None = None) -> dict:
    if "src_app" not in flows_df.columns and "dst_app" not in flows_df.columns:
        return {"skipped": True, "reason": "no app labels"}
    if app is None:
        return {"top_apps": _top_apps(flows_df, limit=20)}
    return _profile_for_app(flows_df, app)


def _top_apps(flows_df, limit):
    series_dst = flows_df.get("dst_app", pd.Series(dtype=object)).dropna()
    series_src = flows_df.get("src_app", pd.Series(dtype=object)).dropna()
    combined = pd.concat([series_dst, series_src])
    counts = combined.value_counts().head(limit).reset_index()
    counts.columns = ["app", "flows"]
    return counts.to_dict("records")


def _profile_for_app(flows_df, app):
    src_col = flows_df.get("src_app", pd.Series(dtype=object))
    dst_col = flows_df.get("dst_app", pd.Series(dtype=object))
    is_app = (src_col == app) | (dst_col == app)
    sub = flows_df[is_app]
    intra = sub[(src_col[is_app] == app) & (dst_col[is_app] == app)]
    cross = sub[(src_col[is_app] == app) ^ (dst_col[is_app] == app)]

    cross_env = pd.DataFrame()
    if "src_env" in sub.columns and "dst_env" in sub.columns:
        cross_env = sub[
            (sub["src_env"].notna()) & (sub["dst_env"].notna())
            & (sub["src_env"] != sub["dst_env"])
        ]

    candidates = _candidate_allows(sub)
    return {
        "app": app,
        "intra_app_flows": int(len(intra)),
        "cross_app_dependencies": _summarize_cross_app(cross, app),
        "cross_env_exceptions": _summarize_cross_env(cross_env),
        "candidate_allow_rules": candidates,
        "candidate_rules_count": len(candidates),
        "boundary_deny_candidates": _boundary_deny_candidates(sub),
    }


def _summarize_cross_app(cross_df, app):
    if cross_df.empty:
        return []
    by_pair = cross_df.groupby(["src_app", "dst_app"]).size()
    return [{"src_app": s, "dst_app": d, "flows": int(c)}
            for (s, d), c in by_pair.items() if s != d]


def _summarize_cross_env(cross_env_df):
    if cross_env_df.empty:
        return []
    return [{"src_env": s, "dst_env": d, "flows": int(c)}
            for (s, d), c in cross_env_df.groupby(["src_env", "dst_env"]).size().items()]


def _candidate_allows(sub):
    pb = sub[sub["policy_decision"] == "potentially_blocked"]
    if pb.empty:
        return []
    grouped = pb.groupby(["src", "dst", "port"]).size().reset_index(name="flows")
    return [{
        "src_label": _label_of(sub, row["src"]),
        "dst_label": _label_of(sub, row["dst"]),
        "port": int(row["port"]),
        "flows": int(row["flows"]),
    } for _, row in grouped.iterrows()]


def _label_of(sub, addr):
    if "src_label" in sub.columns:
        match = sub[sub["src"] == addr]["src_label"].dropna()
        if not match.empty:
            return match.iloc[0]
    if "dst_label" in sub.columns:
        match = sub[sub["dst"] == addr]["dst_label"].dropna()
        if not match.empty:
            return match.iloc[0]
    return addr


def _boundary_deny_candidates(sub):
    if "src_env" not in sub.columns or "dst_env" not in sub.columns:
        return []
    crosses = sub[
        (sub["src_env"].notna()) & (sub["dst_env"].notna())
        & (sub["src_env"] != sub["dst_env"])
    ]
    return [{"src_env": s, "dst_env": d, "flows": int(c)}
            for (s, d), c in crosses.groupby(["src_env", "dst_env"]).size().items()]
