"""Enforcement progress per app/env, and the flows that break when it is enforced.

Two things an operator moving towards enforcement needs and the traffic
reports did not show:

* how far each app(env) actually is — the enforcement mode of the workloads
  behind the flows (``dst_enforcement``/``src_enforcement``), not a proxy
  computed from traffic shares;
* which observed flows will be dropped the moment their destination is
  enforced — Potentially Blocked flows (no rule allows them) — grouped into the
  allow rule that would keep them working.
"""
from __future__ import annotations

import pandas as pd

from src.i18n import t

_MODES = ("full", "selective", "visibility_only", "idle")


def _label(app, env, unlabeled: str) -> str:
    app = "" if pd.isna(app) else str(app).strip()
    env = "" if pd.isna(env) else str(env).strip()
    app = app or unlabeled
    return f"{app} ({env})" if env else app


def _progress(df: pd.DataFrame, unlabeled: str, top_n: int) -> tuple[pd.DataFrame, int]:
    frames = []
    for side in ("src", "dst"):
        cols = [f"{side}_ip", f"{side}_app", f"{side}_env", f"{side}_enforcement"]
        if not all(c in df.columns for c in cols):
            continue
        part = df[cols].copy()
        part.columns = ["ip", "app", "env", "mode"]
        frames.append(part)
    if not frames:
        return pd.DataFrame(), 0
    wl = pd.concat(frames, ignore_index=True)
    wl["mode"] = wl["mode"].fillna("").astype(str).str.strip().str.lower()
    wl = wl[wl["mode"] != ""].drop_duplicates(subset=["ip"])
    if wl.empty:
        return pd.DataFrame(), 0
    wl["app_env"] = [_label(a, e, unlabeled) for a, e in zip(wl["app"], wl["env"])]
    counts = pd.crosstab(wl["app_env"], wl["mode"])
    for m in _MODES:
        if m not in counts.columns:
            counts[m] = 0
    total = counts.sum(axis=1)
    enforced = counts["full"] + 0.5 * counts["selective"]
    out = pd.DataFrame({
        "App (Env)": counts.index,
        "Workloads": total.values,
        "Full": counts["full"].values,
        "Selective": counts["selective"].values,
        "Visibility Only": counts["visibility_only"].values,
        "Idle": counts["idle"].values,
        "Enforced %": (enforced / total.replace(0, 1) * 100).round(1).values,
    }).sort_values(["Enforced %", "Workloads"], ascending=[True, False])
    n_total = len(out)
    return out.head(top_n).reset_index(drop=True), n_total


def _breaks(df: pd.DataFrame, unlabeled: str, top_n: int) -> tuple[pd.DataFrame, int]:
    if "policy_decision" not in df.columns:
        return pd.DataFrame(), 0
    pb = df[df["policy_decision"].astype(str).str.lower() == "potentially_blocked"].copy()
    if pb.empty:
        return pd.DataFrame(), 0
    for c in ("src_app", "src_env", "dst_app", "dst_env", "proto"):
        if c not in pb.columns:
            pb[c] = ""
    pb["Source"] = [_label(a, e, unlabeled) for a, e in zip(pb["src_app"], pb["src_env"])]
    pb["Destination"] = [_label(a, e, unlabeled) for a, e in zip(pb["dst_app"], pb["dst_env"])]
    port = pd.to_numeric(pb.get("port", 0), errors="coerce").fillna(0).astype(int).astype(str)
    proto = pb["proto"].fillna("").astype(str).str.strip()
    pb["Service"] = port.where(proto == "", port + "/" + proto)
    pb["num_connections"] = pd.to_numeric(pb.get("num_connections", 1), errors="coerce").fillna(1)
    grouped = (pb.groupby(["Source", "Destination", "Service"])
               .agg(Connections=("num_connections", "sum"),
                    **{"Source IPs": ("src_ip", "nunique") if "src_ip" in pb.columns else ("Source", "size")})
               .reset_index()
               .sort_values("Connections", ascending=False))
    grouped["Suggested Allow Rule"] = (grouped["Source"] + " → " + grouped["Destination"]
                                       + " : " + grouped["Service"])
    grouped["Connections"] = grouped["Connections"].astype("Int64")
    n_total = len(grouped)
    cols = ["Suggested Allow Rule", "Destination", "Source", "Service", "Connections", "Source IPs"]
    return grouped[cols].head(top_n).reset_index(drop=True), n_total


def analyze(df: pd.DataFrame, top_n: int = 20, *, lang: str = "en") -> dict:
    if df is None or df.empty:
        return {"error": t("rpt_mod_err_no_data", lang=lang)}
    unlabeled = t("rpt_ev_unlabeled", lang=lang)
    progress, progress_total = _progress(df, unlabeled, top_n)
    breaks, breaks_total = _breaks(df, unlabeled, top_n)
    return {
        "progress": progress,
        "progress_total": progress_total,
        "breaks_on_enforcement": breaks,
        "breaks_total": breaks_total,
    }
