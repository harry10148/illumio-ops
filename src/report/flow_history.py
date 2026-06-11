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
) -> str:
    """Persist a signature set and prune to the newest 12 files."""
    ts = generated_at or datetime.datetime.now().isoformat(timespec="seconds")
    safe_ts = ts.replace(":", "").replace("-", "").replace("T", "_")[:15]
    hdir = _history_dir(output_dir, report_type)
    hdir.mkdir(parents=True, exist_ok=True)
    path = hdir / f"flows_{safe_ts}.json.gz"
    payload = {"_generated_at": ts, "signatures": sorted(signatures)}
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    for old in sorted(hdir.glob("flows_*.json.gz"))[:-_KEEP]:
        old.unlink(missing_ok=True)
    logger.info("[FlowHistory] Saved {} signatures → {}", len(signatures), path)
    return str(path)


def load_previous_signatures(
    output_dir: str,
    report_type: str,
) -> tuple[set[str] | None, str | None]:
    """Load the most recent signature set, or (None, None) when absent."""
    hdir = _history_dir(output_dir, report_type)
    if not hdir.is_dir():
        return None, None
    files = sorted(hdir.glob("flows_*.json.gz"))
    if not files:
        return None, None
    try:
        with gzip.open(files[-1], "rt", encoding="utf-8") as fh:
            payload = json.load(fh)
        return set(payload.get("signatures", [])), payload.get("_generated_at")
    except Exception as exc:  # noqa: BLE001 — corrupt history must not kill reports
        logger.warning("[FlowHistory] Failed to load {}: {}", files[-1], exc)
        return None, None
