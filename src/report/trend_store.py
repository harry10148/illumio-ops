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
    *,
    meta: dict[str, Any] | None = None,
) -> str:
    """Persist a KPI snapshot and return the file path.

    ``meta`` (window/data_source/profile) is stored under the single
    ``_meta`` key — the leading underscore means compute_deltas already
    skips it as a KPI. Snapshots saved without ``meta`` (or by older code)
    simply omit the key, which snapshot_mismatch() treats as "no previous
    metadata to compare" and silently returns no warnings for.
    """
    ts = generated_at or datetime.datetime.now().isoformat(timespec="seconds")
    safe_ts = ts.replace(":", "").replace("-", "").replace("T", "_")[:15]
    hdir = _history_dir(output_dir, report_type)
    hdir.mkdir(parents=True, exist_ok=True)

    payload = {"_generated_at": ts, **kpi_dict}
    if meta:
        payload["_meta"] = meta
    path = hdir / f"{safe_ts}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
    logger.info("[TrendStore] Saved {} snapshot → {}", report_type, path)
    return str(path)

def load_previous(output_dir: str, report_type: str) -> dict[str, Any] | None:
    """Load the most recent previous snapshot.

    呼叫序永遠是「先 load 後 save」——每個 generator 都在寫入本次快照之前
    呼叫這個函式，所以呼叫當下磁碟上最新的檔案就是「上一次 run」，不是
    「上上次 run」。第一次 run 時目錄裡還沒有任何快照，回傳 None。
    """
    hdir = _history_dir(output_dir, report_type)
    if not hdir.is_dir():
        return None
    files = sorted(hdir.glob("*.json"))
    if not files:
        return None  # 第一次 run，尚無任何快照可比較
    prev = files[-1]
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

def _window_span_days(window: dict[str, Any]) -> int | None:
    """Span in days between a ``{"start", "end"}`` window's two dates."""
    start, end = window.get("start"), window.get("end")
    if not start or not end:
        return None
    try:
        d1 = datetime.date.fromisoformat(str(start)[:10])
        d2 = datetime.date.fromisoformat(str(end)[:10])
    except ValueError:
        return None
    return (d2 - d1).days

def snapshot_mismatch(
    current_meta: dict[str, Any] | None,
    previous_payload: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """回傳不一致欄位清單 [{"field", "previous", "current"}]。

    只比對兩邊都存在的欄位（舊快照無 _meta → 空清單，靜默相容）。
    window 以天數比較（差 >1 天視為不一致）；data_source/profile 字串不等即不一致。
    """
    if not current_meta or not previous_payload:
        return []
    previous_meta = previous_payload.get("_meta")
    if not previous_meta:
        return []

    mismatches: list[dict[str, Any]] = []

    cur_window = current_meta.get("window")
    prev_window = previous_meta.get("window")
    if cur_window and prev_window:
        cur_span = _window_span_days(cur_window)
        prev_span = _window_span_days(prev_window)
        if cur_span is not None and prev_span is not None and abs(cur_span - prev_span) > 1:
            mismatches.append({"field": "window", "previous": prev_window, "current": cur_window})

    for field in ("data_source", "profile"):
        cur_val = current_meta.get(field)
        prev_val = previous_meta.get(field)
        if cur_val is not None and prev_val is not None and cur_val != prev_val:
            mismatches.append({"field": field, "previous": prev_val, "current": cur_val})

    return mismatches

def build_kpi_dict_from_metadata(kpis: list[dict]) -> dict[str, Any]:
    """Convert the KPI list from metadata.json format to a flat dict.

    Keys prefer the stable i18n key (``label_key`` / ``i18n_key``) so that
    snapshots written under different report languages stay comparable.
    Falls back to the localized ``label`` for KPIs that carry no key.
    """
    out: dict[str, Any] = {}
    for kpi in kpis:
        if "value" not in kpi:
            continue
        key = kpi.get("label_key") or kpi.get("i18n_key") or kpi.get("label")
        if key:
            out[key] = kpi["value"]
    return out


def canonicalize_legacy_keys(
    snapshot: dict[str, Any] | None,
    candidate_keys: list[str],
) -> dict[str, Any] | None:
    """Migrate a legacy snapshot whose keys are localized labels.

    Pre-fix snapshots used t(label_key, lang) display text as dict keys.
    For each canonical candidate key, look up its en / zh_TW rendering and,
    if the legacy snapshot used that text, rename it to the canonical key.
    Canonical keys already present pass through untouched.
    """
    if not snapshot:
        return snapshot
    from src.i18n import t

    label_to_key: dict[str, str] = {}
    for key in candidate_keys:
        if key.startswith("_"):
            continue
        for lang in ("en", "zh_TW"):
            label = t(key, lang=lang, default="")
            if label and label != key:
                label_to_key[label] = key
                if key.startswith("mod12_kpi_enforce_mode_"):
                    prefix = t("mod12_kpi_enforcement_prefix", lang=lang, default="Enforcement:")
                    label_to_key[f"{prefix} {label}"] = key
    return {label_to_key.get(k, k): v for k, v in snapshot.items()}
