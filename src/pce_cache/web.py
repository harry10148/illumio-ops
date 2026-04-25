"""Flask Blueprint for PCE cache management endpoints."""
from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request
from flask_login import login_required
from loguru import logger

bp = Blueprint("pce_cache", __name__, url_prefix="/api/cache")


def _get_sf():
    import os
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src.config import ConfigManager
    from src.pce_cache.schema import init_schema
    cm = ConfigManager()
    cfg = cm.models.pce_cache
    os.makedirs(os.path.dirname(os.path.abspath(cfg.db_path)), exist_ok=True)
    engine = create_engine(f"sqlite:///{cfg.db_path}")
    init_schema(engine)
    return sessionmaker(engine)


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
