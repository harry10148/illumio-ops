# src/report/flow_history.py
"""Per-run flow-signature snapshots for baseline drift detection.

Stores the set of observed (src_app, dst_app, port, proto) signatures per
report run, alongside trend_store's KPI history:

    {output_dir}/history/{report_type}/flows_{ts}.json.gz

Schema: {"_generated_at": iso_ts, "signatures": [sorted str, ...]}
App-level (not IP-level) signatures keep files bounded and align with how
microsegmentation policy is expressed. Retention: newest 12 files.
"""
from __future__ import annotations

import datetime
import gzip
import json
from pathlib import Path

import pandas as pd
from loguru import logger

UNLABELED = "(unlabeled)"
_KEEP = 12


def _history_dir(output_dir: str, report_type: str) -> Path:
    return Path(output_dir) / "history" / report_type


def build_signatures(df: pd.DataFrame | None) -> set[str]:
    """Distinct 'src_app|dst_app|port|proto' signatures; blank labels → (unlabeled)."""
    if df is None or df.empty:
        return set()
    src = df["src_app"].fillna("").astype(str).replace("", UNLABELED)
    dst = df["dst_app"].fillna("").astype(str).replace("", UNLABELED)
    port = df["port"].fillna(0).astype(int).astype(str)
    proto = df["proto"].fillna("").astype(str)
    return set(src + "|" + dst + "|" + port + "|" + proto)


def save_signatures(
    output_dir: str,
    report_type: str,
    signatures: set[str],
    generated_at: str | None = None,
    *,
    meta: dict | None = None,
) -> str:
    """Persist a signature set and prune to the newest 12 files.

    ``meta``（window/data_source/profile，形狀同 trend_store）存於單一 ``_meta``
    鍵；未帶 meta（或升級前的舊寫入）則省略該鍵，load 端回 None → drift 不觸發
    任何視窗/來源一致性檢查（靜默相容）。
    """
    ts = generated_at or datetime.datetime.now().isoformat(timespec="seconds")
    safe_ts = ts.replace(":", "").replace("-", "").replace("T", "_")[:15]
    hdir = _history_dir(output_dir, report_type)
    hdir.mkdir(parents=True, exist_ok=True)
    path = hdir / f"flows_{safe_ts}.json.gz"
    payload = {"_generated_at": ts, "signatures": sorted(signatures)}
    if meta:
        payload["_meta"] = meta
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    for old in sorted(hdir.glob("flows_*.json.gz"))[:-_KEEP]:
        old.unlink(missing_ok=True)
    logger.info("[FlowHistory] Saved {} signatures → {}", len(signatures), path)
    return str(path)


def load_previous_baseline(
    output_dir: str,
    report_type: str,
) -> tuple[set[str] | None, str | None, dict | None]:
    """Load the most recent baseline, or (None, None, None) when absent.

    回 (signatures, generated_at, meta)；舊檔（無 _meta）meta 為 None，drift 端
    據此走完全現行路徑。
    """
    hdir = _history_dir(output_dir, report_type)
    if not hdir.is_dir():
        return None, None, None
    files = sorted(hdir.glob("flows_*.json.gz"))
    if not files:
        return None, None, None
    try:
        with gzip.open(files[-1], "rt", encoding="utf-8") as fh:
            payload = json.load(fh)
        return (
            set(payload.get("signatures", [])),
            payload.get("_generated_at"),
            payload.get("_meta"),
        )
    except Exception as exc:  # noqa: BLE001 — corrupt history must not kill reports
        logger.warning("[FlowHistory] Failed to load {}: {}", files[-1], exc)
        return None, None, None


def load_previous_signatures(
    output_dir: str,
    report_type: str,
) -> tuple[set[str] | None, str | None]:
    """Back-compat two-tuple view over load_previous_baseline (drops meta)."""
    sigs, ts, _meta = load_previous_baseline(output_dir, report_type)
    return sigs, ts
