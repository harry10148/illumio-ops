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


_ENFORCED_MODES = ("full", "selective")


def policy_impact(mod02: dict) -> dict:
    """Derive the app's Security Policy Impact from the mod02 policy-decision result.

    coverage_pct = allowed / total; would_be_blocked = potentially_blocked count
    (flows allowed today only because the workload is in visibility/test mode —
    they have no rule and would drop under Full Enforcement).
    """
    if not mod02 or mod02.get("error"):
        return {"available": False}
    counts = {d: int(mod02.get(d, {}).get("count", 0))
              for d in ("allowed", "blocked", "potentially_blocked", "unknown")}
    total = sum(counts.values())
    if total == 0:
        return {"available": False}
    return {
        "available": True,
        "allowed": counts["allowed"],
        "blocked": counts["blocked"],
        "potentially_blocked": counts["potentially_blocked"],
        "unknown": counts["unknown"],
        "total": total,
        "coverage_pct": round(counts["allowed"] / total * 100, 1),
        "would_be_blocked": counts["potentially_blocked"],
    }


def _workload_has_label(wl: dict, key: str, value: str) -> bool:
    return any(l.get("key") == key and l.get("value") == value
              for l in (wl.get("labels") or []))


def enforcement_summary(workloads, app: str, env: str | None = None) -> dict:
    """Per-workload enforcement-mode summary for one app (optional env refine)."""
    if not workloads:
        return {"available": False}
    scoped = [w for w in workloads if _workload_has_label(w, "app", app)
              and (not env or _workload_has_label(w, "env", env))]
    by_mode: dict[str, int] = {}
    rows = []
    for w in scoped:
        mode = w.get("enforcement_mode", "") or "(unknown)"
        by_mode[mode] = by_mode.get(mode, 0) + 1
        rows.append({"Workload": w.get("hostname", w.get("href", "")), "Enforcement": mode})
    enforced = sum(by_mode.get(m, 0) for m in _ENFORCED_MODES)
    return {
        "available": True,
        "total": len(scoped),
        "by_mode": by_mode,
        "enforced": enforced,
        "table": pd.DataFrame(rows, columns=["Workload", "Enforcement"]),
    }
