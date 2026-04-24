"""Cache lag monitor — detects stalled PCE ingestor and emits alerts."""
from __future__ import annotations

from datetime import datetime, timezone

from loguru import logger
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import IngestionWatermark
from src.i18n import t


def check_cache_lag(session_factory: sessionmaker, max_lag_seconds: int = 300) -> list[dict]:
    """Return lag info for all watermark sources.

    Each entry is a dict with keys: source, last_sync_at, lag_seconds, level.
    level is 'ok', 'warning', or 'error'.
    """
    now = datetime.now(timezone.utc)
    results = []
    with session_factory() as s:
        watermarks = s.query(IngestionWatermark).all()
    for wm in watermarks:
        if wm.last_sync_at is None:
            continue
        last_sync = wm.last_sync_at
        if last_sync.tzinfo is None:
            last_sync = last_sync.replace(tzinfo=timezone.utc)
        lag = (now - last_sync).total_seconds()
        if lag > max_lag_seconds * 2:
            level = "error"
        elif lag > max_lag_seconds:
            level = "warning"
        else:
            level = "ok"
        results.append({
            "source": wm.source,
            "last_sync_at": wm.last_sync_at,
            "lag_seconds": lag,
            "level": level,
        })
    return results


def run_cache_lag_monitor(cm) -> None:
    """APScheduler job: check ingestor lag, log if stalled."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker as _SM
    from src.pce_cache.schema import init_schema

    cfg = cm.models.pce_cache
    engine = create_engine(f"sqlite:///{cfg.db_path}")
    init_schema(engine)
    sf = _SM(engine)

    max_lag = 300
    try:
        max_lag = max(
            cfg.events_poll_interval_seconds,
            cfg.traffic_poll_interval_seconds,
        ) * 3
    except AttributeError as e:
        logger.debug("Cache poll intervals unavailable, using default lag threshold: {}", e)

    results = check_cache_lag(sf, max_lag_seconds=max_lag)
    for r in results:
        if r["level"] == "error":
            logger.error(
                t("alert_cache_lag_error", source=r["source"], lag=int(r["lag_seconds"]))
            )
        elif r["level"] == "warning":
            logger.warning(
                t("alert_cache_lag_warning", source=r["source"], lag=int(r["lag_seconds"]))
            )
