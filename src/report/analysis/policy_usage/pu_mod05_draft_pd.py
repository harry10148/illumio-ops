"""
Policy Usage Module 05: Draft Policy Decision Risk (Comprehensive)

Three lenses:
  visibility_risk  – potentially_blocked_by_boundary / _by_override_deny
                     (enforcement tightening risk on visibility-mode workloads)
  draft_conflicts  – blocked_by_override_deny / allowed_across_boundary
                     (draft introduces Override Deny or anomalous cross-boundary allow)
  draft_coverage   – policy_decision=potentially_blocked AND draft resolves it to
                     allowed or blocked_by_boundary
                     (flows currently unruled that now have a decision in draft)
"""
from __future__ import annotations

from collections import Counter

import pandas as pd

_GROUP_A = frozenset({"potentially_blocked_by_boundary", "potentially_blocked_by_override_deny"})
_GROUP_B = frozenset({"blocked_by_override_deny", "allowed_across_boundary"})
_GROUP_C_DRAFT = frozenset({"allowed", "blocked_by_boundary"})

# 風險類型欄的穩定英文值（渲染層以 value_i18n_maps 轉譯，見 report_i18n.RISK_TYPE_VALUE_I18N）
_RISK_TYPE_LABELS = {
    "visibility_risk": "Visibility Risk",
    "draft_conflicts": "Draft Conflict",
    "draft_coverage": "Draft Coverage",
}


def pu_draft_pd_summary(rows: list[dict]) -> dict:
    if not rows:
        return {"skipped": True, "reason": "no flows returned"}

    group_a = [r for r in rows if r.get("draft_policy_decision") in _GROUP_A]
    group_b = [r for r in rows if r.get("draft_policy_decision") in _GROUP_B]
    group_c = [
        r for r in rows
        if r.get("policy_decision") == "potentially_blocked"
        and r.get("draft_policy_decision") in _GROUP_C_DRAFT
    ]

    groups = {
        "visibility_risk": _build_group(group_a),
        "draft_conflicts": _build_group(group_b),
        "draft_coverage": _build_group(group_c),
    }

    return {
        "total": len(group_a) + len(group_b) + len(group_c),
        "visibility_risk": groups["visibility_risk"],
        "draft_conflicts": groups["draft_conflicts"],
        "draft_coverage": groups["draft_coverage"],
        "merged_top_pairs": _merge_top_pairs(groups),
    }


def _merge_top_pairs(groups: dict) -> pd.DataFrame:
    """各類型各自 Top 20（既有 top_pairs）加上 Risk Type 欄後合併，類型分組、類內 Connections 降序。"""
    tagged = []
    for key, label in _RISK_TYPE_LABELS.items():
        tp = groups[key]["top_pairs"]
        if not tp.empty:
            frame = tp.copy()
            frame.insert(0, "Risk Type", label)
            tagged.append(frame)
    if not tagged:
        return pd.DataFrame()
    return pd.concat(tagged, ignore_index=True)


def _build_group(rows: list[dict]) -> dict:
    if not rows:
        return {"total": 0, "by_subtype": {}, "top_pairs": pd.DataFrame()}

    by_subtype = dict(Counter(r["draft_policy_decision"] for r in rows))

    pair_counter: Counter = Counter()
    for r in rows:
        # Use `or {}` / `or 1`, not dict-get defaults: the PCE can return src /
        # dst / service / num_connections present-but-null, and a null value
        # would crash the whole draft-PD section (AttributeError / int(None)).
        src = r.get("src") or {}
        dst = r.get("dst") or {}
        svc = r.get("service") or {}
        src_wl = src.get("workload") or {}
        dst_wl = dst.get("workload") or {}
        src_name = src_wl.get("name") or src.get("ip") or "?"
        dst_name = dst_wl.get("name") or dst.get("ip") or "?"
        port = svc.get("port", "?")
        dpd = r["draft_policy_decision"]
        pair_counter[(src_name, dst_name, port, dpd)] += int(r.get("num_connections") or 1)

    top_pairs = pd.DataFrame([
        {"Src": src, "Dst": dst, "Port": port, "Draft Decision": dpd, "Connections": cnt}
        for (src, dst, port, dpd), cnt in pair_counter.most_common(20)
    ])
    return {"total": len(rows), "by_subtype": by_subtype, "top_pairs": top_pairs}
