"""KPI-only JSON snapshot store for report Change Impact analysis.

Path: reports/snapshots/<report_type>/<YYYY-MM-DD>_<profile>.json
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from loguru import logger

SCHEMA_VERSION = 1
_BASE_DIR = "reports/snapshots"


def _dir_for(report_type: str) -> Path:
    p = Path(_BASE_DIR) / report_type
    p.mkdir(parents=True, exist_ok=True)
    return p


def _filename(snap: dict) -> str:
    date = snap["generated_at"][:10]
    profile = snap.get("profile", "default")
    return f"{date}_{profile}.json"


def write_snapshot(report_type: str, snap: dict) -> Path:
    """Atomic write. Same date+profile overwrites."""
    if snap.get("schema_version") != SCHEMA_VERSION:
        snap["schema_version"] = SCHEMA_VERSION
    target = _dir_for(report_type) / _filename(snap)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(snap, indent=2, sort_keys=True))
    tmp.replace(target)
    return target


def list_snapshots(report_type: str, *, profile: Optional[str] = None) -> list[dict]:
    """Return snapshots sorted by generated_at descending. Filtered by profile if given."""
    items = []
    for f in _dir_for(report_type).glob("*.json"):
        try:
            data = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            # 靜默跳過會讓 read_latest 回較舊快照、過期資料被當成當前資料
            logger.warning("skipping corrupt snapshot {}: {}", f, exc)
            continue
        if profile is not None and data.get("profile") != profile:
            continue
        items.append(data)
    items.sort(key=lambda d: d.get("generated_at", ""), reverse=True)
    return items


def read_latest(report_type: str, *, profile: Optional[str] = None) -> Optional[dict]:
    items = list_snapshots(report_type, profile=profile)
    return items[0] if items else None


def cleanup_old(report_type: str, *, retention_days: int, today: Optional[datetime] = None) -> int:
    """Delete snapshots older than retention_days. Returns number removed."""
    cutoff = (today or datetime.now(timezone.utc)).date()
    removed = 0
    for f in _dir_for(report_type).glob("*.json"):
        try:
            data = json.loads(f.read_text())
            snap_date = datetime.fromisoformat(data["generated_at"].replace("Z", "+00:00")).date()
        except (KeyError, ValueError, json.JSONDecodeError, OSError) as exc:
            logger.warning("skipping corrupt snapshot {}: {}", f, exc)
            continue
        age_days = (cutoff - snap_date).days
        if age_days > retention_days:
            f.unlink(missing_ok=True)
            removed += 1
    return removed
