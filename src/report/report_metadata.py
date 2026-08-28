"""Shared deterministic metadata helpers for report artifacts."""
from __future__ import annotations

import json
import os
from typing import Any

from loguru import logger

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
        "Attack posture "
        f"boundary {counts.get('boundary_breaches', 0)} | "
        f"pivot {counts.get('suspicious_pivot_behavior', 0)} | "
        f"blast {counts.get('blast_radius', 0)} | "
        f"blind {counts.get('blind_spots', 0)} | "
        f"actions {counts.get('action_matrix', 0)}"
    )


def write_metadata_sidecar(report_path: str, payload: dict[str, Any]) -> None:
    """Merge ``payload`` into ``<report_path>.metadata.json``.

    Two independent producers own keys in this file: the generator/exporter
    (report_type / summary / execution stats, read by ``/api/reports``) and
    ``report_scheduler._stamp_schedule_id`` (``schedule_id``, which the
    per-schedule retention sweep prunes by). A wholesale write by either would
    drop the other's keys, so both merge.

    Best-effort by design: the sidecar is written AFTER the report artifact is
    already committed to disk (outside the reserve/discard cleanup), so raising
    here would leave a real report on disk while the caller sees a failed
    export. Same contract as ``_stamp_schedule_id``. Note this deviates from
    ReportGenerator._write_report_metadata, which is unguarded — the existing
    writers are left alone.
    """
    side = report_path + ".metadata.json"
    data: dict[str, Any] = {}
    try:
        if os.path.isfile(side):
            with open(side, encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                data = loaded
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[ReportMetadata] unreadable sidecar {side}, rewriting: {exc}")
        data = {}
    data.update(payload)
    try:
        with open(side, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[ReportMetadata] could not write sidecar {side}: {exc}")
