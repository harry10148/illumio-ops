"""Cache lag monitor — detects stalled PCE ingestor and emits alerts."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from loguru import logger
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import IngestionWatermark
from src.i18n import t

# AL-Task 11: throttle repeated lag-monitor alerts. run_cache_lag_monitor ticks
# every 60s; without throttling a sustained outage re-logs one error per
# minute (capacity-case review flagged this as a systemic alerting-storm gap
# and handed it to the Alert case). lag_monitor has no reporter/STATE_FILE
# lifecycle like the analyzer watchdog (AL-Task 6), so a lightweight
# module-level dict is enough — the scheduler runs as a single long-lived
# process; a restart re-sending one alert is acceptable. Keyed by alert
# identity (kind, source[, level]) so different sources/levels don't block
# each other, and cleared once the triggering condition clears so the next
# occurrence alerts immediately (unlike the watchdog's fixed-cooldown,
# no-reset behavior — that precedent is out of scope here; this is a new
# mechanism with no compatibility burden).
LAG_ALERT_COOLDOWN_MINUTES = 60

_last_alert_at: dict[tuple, datetime] = {}
# 值班可觀測性（本 sweep）：壓制起點記一條 debug——只在「進入壓制的第一個 tick」
# 記一次，避免壓制期間每 60s 一條把 debug log 洗版。不改節流語意（AL-11 沿用）。
_suppression_logged: set[tuple] = set()


def _should_alert(key: tuple) -> bool:
    """True (and records now()) if key is outside its cooldown window."""
    now = datetime.now(timezone.utc)
    last = _last_alert_at.get(key)
    if last and (now - last).total_seconds() < LAG_ALERT_COOLDOWN_MINUTES * 60:
        if key not in _suppression_logged:
            _suppression_logged.add(key)
            cooldown_until = last + timedelta(minutes=LAG_ALERT_COOLDOWN_MINUTES)
            logger.debug(
                "lag_monitor: alert suppressed for key={} (cooldown {} -> {})",
                key, last.isoformat(), cooldown_until.isoformat(),
            )
        return False
    _last_alert_at[key] = now
    _suppression_logged.discard(key)
    return True


def _clear_alert(key: tuple) -> None:
    """Drop a key's cooldown so recovery lets the next alert fire immediately."""
    _last_alert_at.pop(key, None)
    _suppression_logged.discard(key)


def check_cache_lag(session_factory: sessionmaker, max_lag_seconds: int = 300) -> list[dict]:
    """Return lag info for all watermark sources.

    Each entry is a dict with keys: source, last_sync_at, lag_seconds, level,
    last_status, last_error. level is 'ok', 'warning', or 'error' (time-based).
    last_status/last_error carry the most recent ingest outcome — note that a
    failed ingest still bumps last_sync_at, so callers should treat
    last_status == 'error' as unhealthy regardless of a small lag.
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
            "last_status": wm.last_status,
            "last_error": wm.last_error,
        })
    return results


def status_alerts(results: list[dict]) -> list[str]:
    """last_status=='error' 的來源 → 告警訊息。

    時間基準的 level 看不出「持續失敗」：失敗的 ingest 仍會 bump
    last_sync_at（見 check_cache_lag docstring），所以 PCE 長期不可達時
    lag 永遠正常。此函式補上以結果狀態為準的第二道判斷。"""
    msgs = []
    for r in results:
        if r.get("last_status") == "error":
            msgs.append(t(
                "alert_cache_ingest_failing",
                source=r.get("source", "?"),
                err=(r.get("last_error") or "")[:200],
            ))
    return msgs


def run_cache_lag_monitor(cm) -> None:
    """APScheduler job: check ingestor lag, log if stalled."""
    from sqlalchemy.orm import sessionmaker as _SM
    from src.gui._helpers import _get_cache_engine

    cfg = cm.models.pce_cache
    sf = _SM(_get_cache_engine(cfg.db_path))

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
        source = r["source"]
        error_key = ("level", source, "error")
        warning_key = ("level", source, "warning")
        if r["level"] == "error":
            _clear_alert(warning_key)
            if _should_alert(error_key):
                logger.error(
                    t("alert_cache_lag_error", source=source, lag=int(r["lag_seconds"]))
                )
        elif r["level"] == "warning":
            _clear_alert(error_key)
            if _should_alert(warning_key):
                logger.warning(
                    t("alert_cache_lag_warning", source=source, lag=int(r["lag_seconds"]))
                )
        else:
            _clear_alert(error_key)
            _clear_alert(warning_key)

        status_key = ("status", source)
        if r.get("last_status") == "error":
            if _should_alert(status_key):
                for msg in status_alerts([r]):
                    logger.error(msg)
        else:
            _clear_alert(status_key)
