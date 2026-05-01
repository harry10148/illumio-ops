"""Flask Blueprint for PCE cache management endpoints."""
from __future__ import annotations

import threading

from flask import Blueprint, current_app, jsonify, request
from flask_login import login_required
from loguru import logger

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
    source = data.get("source", "events")
    since_str = data.get("since")
    until_str = data.get("until")
    if not since_str:
        return jsonify({"error": "missing since"}), 400
    try:
        since_dt = datetime.strptime(since_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        until_dt = datetime.strptime(until_str, "%Y-%m-%d").replace(tzinfo=timezone.utc) if until_str else datetime.now(timezone.utc)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    try:
        sf = _get_sf()
    except Exception as e:
        return jsonify({"error": f"cache not configured: {e}"}), 503
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
    try:
        sf = _get_sf()
    except Exception as e:
        return jsonify({"error": f"cache not configured: {e}"}), 503
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
    try:
        sf = _get_sf()
    except Exception as e:
        return jsonify({"error": f"cache not configured: {e}"}), 503
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
