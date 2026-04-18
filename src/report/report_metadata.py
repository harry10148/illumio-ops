"""Shared deterministic metadata helpers for report artifacts."""
from __future__ import annotations

from typing import Any

ATTACK_SECTION_KEYS = (
    "boundary_breaches",
    "suspicious_pivot_behavior",
    "blast_radius",
    "blind_spots",
    "action_matrix",
)

def _empty_attack_summary() -> dict[str, list[dict[str, Any]]]:
    return {key: [] for key in ATTACK_SECTION_KEYS}

def _normalize_items(items: Any, top_n: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not isinstance(items, list):
        return rows
    for item in items[:top_n]:
        if isinstance(item, dict):
            rows.append(dict(item))
    return rows

def extract_attack_summary(module_results: dict[str, Any], top_n: int = 5) -> dict[str, list[dict[str, Any]]]:
    """Extract deterministic attack sections from mod12/mod00 summary outputs."""
    if not isinstance(module_results, dict):
        return _empty_attack_summary()

    candidates = []
    for mod_id in ("mod12", "mod00"):
        mod = module_results.get(mod_id)
        if isinstance(mod, dict):
            candidates.append(mod)

    for mod in candidates:
        summary = _empty_attack_summary()
        found = False
        for key in ATTACK_SECTION_KEYS:
            rows = _normalize_items(mod.get(key), top_n=top_n)
            if rows:
                found = True
            summary[key] = rows
        if found:
            return summary

    return _empty_attack_summary()

def attack_summary_counts(attack_summary: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for key in ATTACK_SECTION_KEYS:
        values = attack_summary.get(key) if isinstance(attack_summary, dict) else []
        counts[key] = len(values) if isinstance(values, list) else 0
    return counts

def build_attack_summary_brief(counts: dict[str, int]) -> str:
    total = sum(int(counts.get(k, 0) or 0) for k in ATTACK_SECTION_KEYS)
    if total <= 0:
        return ""
    return (
        "Attack/攻擊 posture "
        f"boundary {counts.get('boundary_breaches', 0)} | "
        f"pivot {counts.get('suspicious_pivot_behavior', 0)} | "
        f"blast {counts.get('blast_radius', 0)} | "
        f"blind {counts.get('blind_spots', 0)} | "
        f"actions {counts.get('action_matrix', 0)}"
    )

