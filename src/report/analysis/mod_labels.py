# src/report/analysis/mod_labels.py
"""Label hygiene — labeling quality metrics for microsegmentation governance.

Bad labels mean bad policy: this module measures (1) workload-inventory label
coverage (unlabeled VENs even when silent), (2) traffic from/to managed-but-
unlabeled endpoints, (3) endpoints observed with conflicting label sets.
PURE function: workloads list is fetched by the caller (best-effort).
"""
from __future__ import annotations

import pandas as pd

LABEL_KEYS = ("app", "env", "loc", "role")


def _workload_labels(wl: dict) -> dict[str, str]:
    out = {}
    for item in wl.get("labels") or []:
        if isinstance(item, dict) and item.get("key"):
            out[item["key"]] = item.get("value", "")
    return out


def _workload_metrics(workloads: list | None, top_n: int) -> dict:
    if not workloads:
        return {"workload_data_available": False}
    rows = []
    fully = 0
    for wl in workloads:
        labels = _workload_labels(wl)
        missing = [k for k in LABEL_KEYS if not labels.get(k)]
        if missing:
            rows.append({"Hostname": wl.get("hostname") or wl.get("name", ""),
                         "Missing Keys": ", ".join(missing)})
        else:
            fully += 1
    total = len(workloads)
    return {
        "workload_data_available": True,
        "total_workloads": total,
        "fully_labeled_count": fully,
        "fully_labeled_pct": round(fully / total * 100, 1) if total else 0.0,
        "unlabeled_workload_count": len(rows),
        "unlabeled_workloads": pd.DataFrame(rows[:top_n]),
        "chart_spec": {
            "type": "bar",
            "title_key": "rpt_labels_chart_title",
            "title": "Label Coverage",
            "data": {"labels": ["Fully labeled", "Missing labels"],
                     "values": [fully, len(rows)]},
        },
    }


def _flow_metrics(df: pd.DataFrame, top_n: int) -> dict:
    if df is None or df.empty:
        return {"managed_unlabeled_flow_count": 0,
                "label_conflicts": pd.DataFrame()}
    src_unlabeled = (df["src_managed"] == True) & (df["src_app"].fillna("") == "")  # noqa: E712
    dst_unlabeled = (df["dst_managed"] == True) & (df["dst_app"].fillna("") == "")  # noqa: E712
    gap_count = int((src_unlabeled | dst_unlabeled).sum())

    # 同一 managed IP 出現多組 (app,env,loc,role) → 標籤衝突
    frames = []
    for side in ("src", "dst"):
        sub = df[df[f"{side}_managed"] == True]  # noqa: E712
        if sub.empty:
            continue
        cols = [f"{side}_ip"] + [f"{side}_{k}" for k in LABEL_KEYS]
        part = sub[cols].copy()
        part.columns = ["IP"] + list(LABEL_KEYS)
        frames.append(part)
    conflicts = pd.DataFrame(columns=["IP", "Distinct Label Sets"])
    if frames:
        seen = pd.concat(frames, ignore_index=True).drop_duplicates()
        counts = seen.groupby("IP").size()
        bad_ips = counts[counts > 1]
        conflicts = pd.DataFrame({
            "IP": bad_ips.index.tolist(),
            "Distinct Label Sets": bad_ips.values.tolist(),
        }).head(top_n)
    return {"managed_unlabeled_flow_count": gap_count, "label_conflicts": conflicts}


def label_hygiene(df: pd.DataFrame, workloads: list | None, top_n: int = 20) -> dict:
    out = _workload_metrics(workloads, top_n)
    out.update(_flow_metrics(df, top_n))
    return out
