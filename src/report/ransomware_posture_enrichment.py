"""Enrichment + cache for ransomware posture (per-workload fetches).

For each computed, non-fully-protected workload (up to ``max_workloads``):
- Cache HIT (fresh) -> reuse, no API call.
- Cache MISS / stale -> ``api.get_workload`` (open_service_ports) +
  ``api.get_workload_risk_details`` (ransomware.details), rate-limited.

Per-workload API errors are swallowed (that workload gets empty lists).
"""
from __future__ import annotations

import json
import os
import time

from loguru import logger

from src.pce_cache.rate_limiter import GlobalRateLimiter


def load_cache(cache_path: str = "data/ransomware_posture_cache.json") -> dict:
    try:
        with open(cache_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save_cache(cache: dict, cache_path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(cache_path)), exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as fh:
        json.dump(cache, fh)


def _wants_enrichment(wl: dict) -> bool:
    rs = wl.get("risk_summary")
    rw = rs.get("ransomware") if isinstance(rs, dict) else None
    if not isinstance(rw, dict):
        return False
    return rw.get("workload_exposure_severity") != "fully_protected"


def refresh_ransomware_posture(
    api,
    workloads: list[dict],
    *,
    rate_per_minute: int = 400,
    max_workloads: int = 500,
    cache_path: str = "data/ransomware_posture_cache.json",
    ttl_hours: int = 24,
    now: "float | None" = None,
) -> dict:
    """Return ``{href: {"open_service_ports": [...], "details": [...]}}``."""
    if now is None:
        now = time.time()
    ttl_seconds = ttl_hours * 3600
    cache = load_cache(cache_path)
    limiter = GlobalRateLimiter(rate_per_minute)

    targets = [w for w in workloads if _wants_enrichment(w)]
    if len(targets) > max_workloads:
        logger.warning(
            "[ransomware_posture] {} eligible workloads exceed cap {}; truncating",
            len(targets), max_workloads,
        )
        targets = targets[:max_workloads]

    out: dict = {}
    for wl in targets:
        href = wl.get("href", "")
        cached = cache.get(href)
        if (isinstance(cached, dict)
                and (now - cached.get("fetched_at", 0)) < ttl_seconds):
            out[href] = {"open_service_ports": cached.get("open_service_ports", []),
                         "details": cached.get("details", [])}
            continue

        limiter.acquire(timeout=60.0)
        try:
            full = api.get_workload(href)
            osp = (full.get("services") or {}).get("open_service_ports") or [] if full else []
        except Exception:
            osp = []

        limiter.acquire(timeout=60.0)
        try:
            rd = api.get_workload_risk_details(href)
            rw = (rd.get("risk_details") or {}).get("ransomware") if rd else None
            details = (rw.get("details") or []) if isinstance(rw, dict) else []
        except Exception:
            details = []

        cache[href] = {"open_service_ports": list(osp), "details": list(details),
                       "fetched_at": now}
        out[href] = {"open_service_ports": list(osp), "details": list(details)}

    _save_cache(cache, cache_path)
    return out
