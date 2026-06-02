"""Enrichment + cache for open service ports (opt-in, per-workload fetches)."""
from __future__ import annotations

import json
import os
import time

from src.pce_cache.rate_limiter import GlobalRateLimiter


def load_open_ports_cache(cache_path: str = "data/open_ports_cache.json") -> dict:
    """Return the raw cache dict, or {} if the file doesn't exist or is invalid."""
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


def refresh_open_ports(
    api,
    workloads: list[dict],
    *,
    rate_per_minute: int = 400,
    max_workloads: int = 500,
    cache_path: str = "data/open_ports_cache.json",
    ttl_hours: int = 24,
    now: float | None = None,
) -> list[dict]:
    """Return a new list of workload dicts, each enriched with
    ``services.open_service_ports``.

    For up to *max_workloads* workloads a cache-then-fetch strategy is used:
    - Cache HIT (fresh): use cached ports, no API call.
    - Cache MISS or stale: call ``api.get_workload(href)``, rate-limited.

    The updated cache is persisted to *cache_path* at the end.
    API errors for individual workloads are caught; those workloads get ``[]``.
    """
    if now is None:
        now = time.time()

    ttl_seconds = ttl_hours * 3600
    cache = load_open_ports_cache(cache_path)
    limiter = GlobalRateLimiter(rate_per_minute)

    target = workloads[:max_workloads]
    enriched: list[dict] = []

    for wl in target:
        href = wl.get("href", "")
        cached = cache.get(href)

        if cached and isinstance(cached, dict):
            age = now - cached.get("fetched_at", 0)
            if age < ttl_seconds:
                # Fresh cache hit — no API call
                ports = cached.get("open_service_ports", [])
                enriched.append(_merge(wl, ports))
                continue

        # Cache miss or stale → fetch
        limiter.acquire(timeout=60.0)
        try:
            resp = api.get_workload(href)
            ports = (resp.get("services") or {}).get("open_service_ports") or [] if resp else []
        except Exception:
            ports = []

        cache[href] = {"open_service_ports": list(ports), "fetched_at": now}
        enriched.append(_merge(wl, ports))

    _save_cache(cache, cache_path)
    return enriched


def _merge(wl: dict, ports: list) -> dict:
    """Return a shallow copy of *wl* with services.open_service_ports set."""
    result = dict(wl)
    result["services"] = {"open_service_ports": list(ports)}
    return result
