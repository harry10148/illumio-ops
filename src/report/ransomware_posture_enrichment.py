"""Enrichment + cache for ransomware posture (per-workload fetches).

For each computed, non-fully-protected workload (up to ``max_workloads``):
- Cache HIT (fresh) -> reuse, no API call.
- Cache MISS / stale -> ``api.get_workload`` (open_service_ports) +
  ``api.get_workload_risk_details`` (ransomware.details), rate-limited.

Per-workload API errors are logged (warning), the entry carries an
``enrichment_error`` marker so reports can render "data unavailable"
instead of a falsely-clean zero, and the failed entry is NOT cached —
otherwise the false-clean result would survive the whole TTL.
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

        fetch_error: str | None = None

        limiter.acquire(timeout=60.0)
        try:
            full = api.get_workload(href)
            osp = (full.get("services") or {}).get("open_service_ports") or [] if full else []
        except Exception as exc:
            logger.warning("[ransomware_posture] enrichment failed for {}: {}", href, exc)
            osp = []
            fetch_error = str(exc)[:200]

        limiter.acquire(timeout=60.0)
        try:
            rd = api.get_workload_risk_details(href)
            rw = (rd.get("risk_details") or {}).get("ransomware") if rd else None
            details = (rw.get("details") or []) if isinstance(rw, dict) else []
        except Exception as exc:
            logger.warning("[ransomware_posture] enrichment failed for {}: {}", href, exc)
            details = []
            fetch_error = str(exc)[:200]

        out[href] = {"open_service_ports": list(osp), "details": list(details)}
        if fetch_error is not None:
            # 失敗不入 cache：讓下一輪重抓，避免假性乾淨存活整個 TTL
            out[href]["enrichment_error"] = fetch_error
            continue
        cache[href] = {"open_service_ports": list(osp), "details": list(details),
                       "fetched_at": now}

    _save_cache(cache, cache_path)
    return out
