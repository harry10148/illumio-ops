"""Lightweight trend-analysis store for report KPI snapshots.

Saves a timestamped snapshot after each report run and computes deltas
against the most recent previous snapshot of the same report type.

Storage layout:
    {output_dir}/history/{report_type}/
        2026-04-10T163449.json
        2026-04-11T091012.json
        ...

Each snapshot is a flat dict of scalar KPI values (numbers or strings).
Only numeric values participate in delta computation.
"""
from __future__ import annotations

import datetime
import json
from loguru import logger
import os
import re
from pathlib import Path
from typing import Any

_NUMERIC_RE = re.compile(r"^-?[\d,]+\.?\d*%?$")

def _to_numeric(val: Any) -> float | None:
    """Best-effort conversion of a KPI value to a float."""
    if isinstance(val, (int, float)):
        return float(val)
    if not isinstance(val, str):
        return None
    s = val.strip().replace(",", "")
    if s.endswith("%"):
        try:
            return float(s[:-1])
        except ValueError:
            return None
    try:
        return float(s)
    except ValueError:
        return None

def _history_dir(output_dir: str, report_type: str) -> Path:
    return Path(output_dir) / "history" / report_type

def save_snapshot(
    output_dir: str,
    report_type: str,
    kpi_dict: dict[str, Any],
    generated_at: str | None = None,
) -> str:
    """Persist a KPI snapshot and return the file path."""
    ts = generated_at or datetime.datetime.now().isoformat(timespec="seconds")
    safe_ts = ts.replace(":", "").replace("-", "").replace("T", "_")[:15]
    hdir = _history_dir(output_dir, report_type)
    hdir.mkdir(parents=True, exist_ok=True)

    payload = {"_generated_at": ts, **kpi_dict}
    path = hdir / f"{safe_ts}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
    logger.info("[TrendStore] Saved {} snapshot → {}", report_type, path)
    return str(path)

def load_previous(output_dir: str, report_type: str) -> dict[str, Any] | None:
    """Load the most recent previous snapshot (excluding the newest)."""
    hdir = _history_dir(output_dir, report_type)
    if not hdir.is_dir():
        return None
    files = sorted(hdir.glob("*.json"))
    if len(files) < 2:
        return None  # Need at least 2 snapshots for a delta
    prev = files[-2]
    try:
        with open(prev, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("[TrendStore] Failed to load {}: {}", prev, e)
        return None

def compute_deltas(
    current: dict[str, Any],
    previous: dict[str, Any],
) -> list[dict[str, Any]]:
    """Compute per-KPI deltas between two snapshots.

    Returns a list of dicts with keys:
        metric, current, previous, delta, delta_pct, direction (up/down/flat)
    Only includes metrics present in both snapshots with numeric values.
    """
    deltas = []
    for key in current:
        if key.startswith("_"):
            continue
        cur_num = _to_numeric(current[key])
        prev_num = _to_numeric(previous.get(key))
        if cur_num is None or prev_num is None:
            continue
        delta = cur_num - prev_num
        if prev_num != 0:
            delta_pct = round(delta / abs(prev_num) * 100, 1)
        else:
            delta_pct = 0.0 if delta == 0 else None
        if abs(delta) < 0.001:
            direction = "flat"
        elif delta > 0:
            direction = "up"
        else:
            direction = "down"
        deltas.append({
            "metric": key,
            "current": cur_num,
            "previous": prev_num,
            "delta": round(delta, 2),
            "delta_pct": delta_pct,
            "direction": direction,
        })
    return deltas

def build_kpi_dict_from_metadata(kpis: list[dict]) -> dict[str, Any]:
    """Convert the KPI list from metadata.json format to a flat dict.

    Metadata KPIs look like: [{"label": "Total Flows", "value": "20,282"}, ...]
    """
    return {kpi["label"]: kpi["value"] for kpi in kpis if "label" in kpi and "value" in kpi}
