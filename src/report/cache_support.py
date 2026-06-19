"""Single source of truth for the report data-source choice.

The traffic/app-summary backend is driven by two booleans (use_cache,
clip_to_cache). The UI exposes ONE 3-mode choice; this module maps between them
and enforces the cache-unavailable safeguard, so CLI/GUI/shell stay consistent.
"""
from __future__ import annotations

_ALIASES = {"cache": "hybrid", "no-cache": "live", "api": "live"}
_VALID = ("hybrid", "live", "cache-only")


def resolve_data_source(value: str | None, cache_ok: bool) -> tuple[bool, bool, str | None]:
    """Map a data_source choice to (use_cache, clip_to_cache, warning).

    value: 'hybrid' | 'live' | 'cache-only' (None/'' -> 'hybrid'); aliases
    'cache'->hybrid, 'no-cache'/'api'->live are accepted for back-compat.
    cache_ok: whether the PCE cache is available (see cache_available()).
    When a cache mode is requested while cache_ok is False, returns the live
    mapping plus a human-readable warning so the caller can warn + fall back.
    """
    mode = (value or "hybrid").strip().lower()
    mode = _ALIASES.get(mode, mode)
    if mode not in _VALID:
        mode = "hybrid"
    if mode == "live":
        return (False, False, None)
    if not cache_ok:
        if mode == "cache-only":
            return (False, False,
                    "'cache-only' requested but the PCE cache is unavailable; "
                    "falling back to a FULL live PCE query (slower).")
        return (False, False,
                f"'{mode}' requested but the PCE cache is unavailable; "
                "generating from live PCE instead.")
    if mode == "hybrid":
        return (True, False, None)
    return (True, True, None)  # cache-only


def cache_available(cm) -> bool:
    """True iff pce_cache is enabled, reachable, and holds traffic data.

    Lazy-imports _make_cache_reader to avoid a circular import with src.main.
    Any failure (disabled, unreachable db, empty cache) returns False.
    """
    try:
        if not cm.models.pce_cache.enabled:
            return False
        from src.main import _make_cache_reader
        reader = _make_cache_reader(cm)
        if reader is None:
            return False
        return reader.earliest_data_timestamp("traffic") is not None
    except Exception:
        return False
