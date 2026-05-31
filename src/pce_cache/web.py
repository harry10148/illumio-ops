"""Flask Blueprint for PCE cache management endpoints."""
from __future__ import annotations

import threading

from flask import Blueprint, current_app, jsonify, request
from flask_login import login_required
from loguru import logger

from src.i18n import t

bp = Blueprint("pce_cache", __name__, url_prefix="/api/cache")

_SF_KEY = "_cache_Session"
_LOCK_KEY = "_cache_sf_lock"


def _get_sf():
    sf = current_app.config.get(_SF_KEY)
    if sf is not None:
        return sf
    lock = current_app.config.setdefault(_LOCK_KEY, threading.Lock())
    with lock:
        sf = current_app.config.get(_SF_KEY)
        if sf is not None:
            return sf
        import os
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from src.pce_cache.schema import init_schema
        cm = current_app.config["CM"]
        cfg = cm.models.pce_cache
        os.makedirs(os.path.dirname(os.path.abspath(cfg.db_path)), exist_ok=True)
        engine = create_engine(f"sqlite:///{cfg.db_path}")
        init_schema(engine)
        current_app.config[_SF_KEY] = sessionmaker(engine)
    return current_app.config[_SF_KEY]


def _get_api():
    from src.config import ConfigManager
    from src.api_client import ApiClient
    cm = ConfigManager()
    cm.load()
    return ApiClient(cm)


@bp.route("/backfill", methods=["POST"])
@login_required
def api_cache_backfill():
    """Synchronous backfill endpoint. POST body: {source, since, until}."""
    from datetime import datetime, timezone
    data = request.get_json(silent=True) or {}
    lang = data.get('lang') or current_app.config["CM"].config.get('settings', {}).get('language', 'en')
    source = data.get("source", "events")
    since_str = data.get("since")
    until_str = data.get("until")
    if not since_str:
        return jsonify({"error": t("gui_err_cache_missing_since", lang=lang)}), 400
    try:
        since_dt = datetime.strptime(since_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        until_dt = datetime.strptime(until_str, "%Y-%m-%d").replace(tzinfo=timezone.utc) if until_str else datetime.now(timezone.utc)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    try:
        sf = _get_sf()
    except Exception as e:
        return jsonify({"error": t("gui_err_cache_not_configured", e=e, lang=lang)}), 503
    try:
        from src.pce_cache.backfill import BackfillRunner
        api = _get_api()
        runner = BackfillRunner(api, sf)
        if source == "events":
            result = runner.run_events(since_dt, until_dt)
        else:
            result = runner.run_traffic(since_dt, until_dt)
        return jsonify({
            "total_rows": result.total_rows,
            "inserted": result.inserted,
            "duplicates": result.duplicates,
            "elapsed_seconds": result.elapsed_seconds,
        })
    except Exception as e:
        logger.exception("cache backfill error: {}", e)
        return jsonify({"error": str(e)}), 500


@bp.route("/retention/run", methods=["POST"])
@login_required
def api_cache_retention_run():
    """Run retention purge immediately using configured retention days."""
    lang = current_app.config["CM"].config.get('settings', {}).get('language', 'en')
    try:
        sf = _get_sf()
    except Exception as e:
        return jsonify({"error": t("gui_err_cache_not_configured", e=e, lang=lang)}), 503
    cfg = current_app.config["CM"].models.pce_cache
    try:
        from src.pce_cache.retention import RetentionWorker
        result = RetentionWorker(sf).run_once(
            events_days=int(cfg.events_retention_days),
            traffic_raw_days=int(cfg.traffic_raw_retention_days),
            traffic_agg_days=int(cfg.traffic_agg_retention_days),
        )
        return jsonify(result)
    except Exception as e:
        logger.exception("cache retention error: {}", e)
        return jsonify({"error": str(e)}), 500


@bp.route("/status", methods=["GET"])
@login_required
def api_cache_status():
    """Return cache row counts."""
    lang = current_app.config["CM"].config.get('settings', {}).get('language', 'en')
    try:
        sf = _get_sf()
    except Exception as e:
        return jsonify({"error": t("gui_err_cache_not_configured", e=e, lang=lang)}), 503
    try:
        from sqlalchemy import func, select
        from src.pce_cache.models import PceEvent, PceTrafficFlowRaw, PceTrafficFlowAgg
        result = {}
        with sf() as s:
            for model, key in [
                (PceEvent, "events"),
                (PceTrafficFlowRaw, "traffic_raw"),
                (PceTrafficFlowAgg, "traffic_agg"),
            ]:
                result[key] = s.execute(select(func.count()).select_from(model)).scalar() or 0
        return jsonify(result)
    except Exception as e:
        logger.exception("cache status error: {}", e)
        return jsonify({"error": str(e)}), 500


@bp.route("/lag", methods=["GET"])
@login_required
def api_cache_lag():
    """Return ingestor lag per watermark source (level ok/warning/error)."""
    lang = current_app.config["CM"].config.get('settings', {}).get('language', 'en')
    try:
        sf = _get_sf()
    except Exception as e:
        return jsonify({"error": t("gui_err_cache_not_configured", e=e, lang=lang)}), 503
    try:
        from src.pce_cache.lag_monitor import check_cache_lag
        cfg = current_app.config["CM"].models.pce_cache
        try:
            max_lag = max(
                int(cfg.events_poll_interval_seconds),
                int(cfg.traffic_poll_interval_seconds),
            ) * 3
        except (AttributeError, TypeError, ValueError):
            max_lag = 300
        sources = [
            {
                "source": r["source"],
                "last_sync_at": r["last_sync_at"].isoformat() if r["last_sync_at"] else None,
                "lag_seconds": int(r["lag_seconds"]),
                "level": r["level"],
                "last_status": r.get("last_status"),
                "last_error": r.get("last_error"),
            }
            for r in check_cache_lag(sf, max_lag_seconds=max_lag)
        ]
        return jsonify({"sources": sources})
    except Exception as e:
        logger.exception("cache lag error: {}", e)
        return jsonify({"error": str(e)}), 500


@bp.route("/health", methods=["GET"])
@login_required
def api_cache_health():
    """Return a single pipeline-health verdict (ok/warn/error/unknown)."""
    lang = current_app.config["CM"].config.get('settings', {}).get('language', 'en')
    try:
        sf = _get_sf()
    except Exception as e:
        return jsonify({"verdict": "unknown", "note": t("gui_err_cache_not_configured", e=e, lang=lang)}), 503
    try:
        from src.pce_cache.health import pipeline_verdict
        from src.pce_cache.lag_monitor import check_cache_lag
        from src.siem.web import _siem_window_totals

        lag = check_cache_lag(sf)
        levels = [r["level"] for r in lag]

        with sf() as s:
            totals = _siem_window_totals(s)

        success_1h = (
            round(totals["sent_1h"] / totals["denom"] * 100, 1)
            if totals["denom"] else 100.0
        )
        verdict = pipeline_verdict(
            lag_levels=levels,
            siem_success_1h=success_1h,
            denom=totals["denom"],
            dlq=totals["dlq"],
        )
        return jsonify({
            "verdict": verdict,
            "lag_levels": levels,
            "siem_success_1h": success_1h,
            "dlq": totals["dlq"],
        })
    except Exception as e:
        logger.exception("cache health error: {}", e)
        return jsonify({"error": str(e)}), 500


@bp.route("/throughput", methods=["GET"])
@login_required
def api_cache_throughput():
    """Return ingest event and traffic counts for the last 1 hour."""
    import datetime as dt
    from sqlalchemy import func, select
    from src.pce_cache.models import PceEvent, PceTrafficFlowRaw
    lang = current_app.config["CM"].config.get('settings', {}).get('language', 'en')
    try:
        sf = _get_sf()
    except Exception as e:
        return jsonify({"error": t("gui_err_cache_not_configured", e=e, lang=lang)}), 503
    hr = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
    with sf() as s:
        ev = s.execute(select(func.count()).select_from(PceEvent)
                       .where(PceEvent.ingested_at >= hr)).scalar() or 0
        tr = s.execute(select(func.count()).select_from(PceTrafficFlowRaw)
                       .where(PceTrafficFlowRaw.ingested_at >= hr)).scalar() or 0
    return jsonify({"events_1h": int(ev), "traffic_1h": int(tr)})


@bp.route("/settings", methods=["GET"])
@login_required
def get_cache_settings():
    cm = current_app.config['CM']
    return jsonify(cm.models.pce_cache.model_dump(mode="json"))


@bp.route("/settings", methods=["PUT"])
@login_required
def put_cache_settings():
    from src.config_models import PceCacheSettings
    from src.gui.settings_helpers import save_section
    cm = current_app.config['CM']
    incoming = request.get_json(silent=True) or {}
    current = cm.models.pce_cache.model_dump(mode="json")
    current.update(incoming)
    result = save_section(cm, "pce_cache", current, PceCacheSettings)
    if result["ok"]:
        cm.load()
    return jsonify(result), (200 if result["ok"] else 422)
