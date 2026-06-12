# src/report/analysis/mod_app_baseline.py
"""Per-app connection baseline — the App Group Summary concept for one app.

PURE functions. filter_app_flows() scopes the estate DataFrame to flows where
the app is source OR destination (optional env refinement); app_baseline()
summarizes inbound services and outbound dependencies for the app owner /
auditor reader.
"""
from __future__ import annotations

import pandas as pd


def filter_app_flows(df: pd.DataFrame, app: str, env: str | None = None) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    src_hit = df["src_app"].fillna("") == app
    dst_hit = df["dst_app"].fillna("") == app
    if env:
        src_hit &= df["src_env"].fillna("") == env
        dst_hit &= df["dst_env"].fillna("") == env
    return df[src_hit | dst_hit].copy()


def _grouped(sub: pd.DataFrame, peer_col: str, top_n: int) -> pd.DataFrame:
    if sub.empty:
        return pd.DataFrame()
    g = (sub.groupby([peer_col, "port", "proto", "policy_decision"], dropna=False)
            ["num_connections"].sum().reset_index()
            .sort_values("num_connections", ascending=False).head(top_n))
    g.columns = [{"src_app": "Src App", "dst_app": "Dst App"}[peer_col],
                 "Port", "Proto", "Decision", "Connections"]
    return g.reset_index(drop=True)


def app_baseline(df: pd.DataFrame, app: str, env: str | None = None, top_n: int = 30) -> dict:
    scoped = filter_app_flows(df, app, env)
    inbound = scoped[scoped["dst_app"].fillna("") == app] if not scoped.empty else scoped
    outbound = scoped[scoped["src_app"].fillna("") == app] if not scoped.empty else scoped
    return {
        "app": app,
        "env": env or "",
        "flow_count": int(len(scoped)),
        "inbound_count": int(len(_grouped(inbound, "src_app", 10**9))) if not inbound.empty else 0,
        "outbound_count": int(len(_grouped(outbound, "dst_app", 10**9))) if not outbound.empty else 0,
        "inbound": _grouped(inbound, "src_app", top_n),
        "outbound": _grouped(outbound, "dst_app", top_n),
    }
