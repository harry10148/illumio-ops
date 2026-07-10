"""Flask Blueprint for PCE cache management endpoints."""
from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request
from flask_login import login_required
from loguru import logger

from src.i18n import t
from src.gui._helpers import _err_with_log

bp = Blueprint("pce_cache", __name__, url_prefix="/api/cache")


def _get_sf():
    """cache DB 的 sessionmaker。引擎走 _get_cache_engine：per-db_path
    process 快取 + NullPool + schema 只 init 一次——與 lag_monitor、
    scheduler jobs 相同的取用模式，避免 web 路徑用預設 QueuePool 長跑
    累積連線。"""
    from sqlalchemy.orm import sessionmaker
    from src.gui._helpers import _get_cache_engine
    db_path = current_app.config["CM"].models.pce_cache.db_path
    return sessionmaker(_get_cache_engine(db_path))


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
            # backfill 會灌入舊日期資料，落在 aggregator 增量視窗之外，
            # 必須顯式全量重算一次，否則趨勢圖看不到 backfill 的 bucket。
            from src.pce_cache.aggregator import TrafficAggregator
            TrafficAggregator(sf).run_once(full=True)
        return jsonify({
            "total_rows": result.total_rows,
            "inserted": result.inserted,
            "duplicates": result.duplicates,
            "elapsed_seconds": result.elapsed_seconds,
        })
    except Exception as e:
        return _err_with_log("cache_backfill", e, lang=lang)


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
            archive_enabled=cfg.archive_enabled,
        )
        return jsonify(result)
    except Exception as e:
        return _err_with_log("cache_retention_run", e, lang=lang)


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
        return _err_with_log("cache_status", e, lang=lang)


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
        return _err_with_log("cache_lag", e, lang=lang)


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

        try:
            _cfg = current_app.config["CM"].models.pce_cache
            _max_lag = max(_cfg.events_poll_interval_seconds,
                           _cfg.traffic_poll_interval_seconds) * 3
        except AttributeError:
            _max_lag = 300
        lag = check_cache_lag(sf, max_lag_seconds=_max_lag)
        cache_lag = [{"source": r["source"], "lag_s": int(r["lag_seconds"]),
                      "level": r["level"]} for r in lag]
        levels = [c["level"] for c in cache_lag]

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
        try:
            from src.pce_cache.capacity import capacity_snapshot
            capacity = capacity_snapshot(sf, current_app.config["CM"].models.pce_cache)
        except Exception as cap_exc:
            logger.warning("capacity_snapshot failed in /api/cache/health: {}", cap_exc)
            capacity = None
        return jsonify({
            "verdict": verdict,
            "lag_levels": levels,
            "cache_lag": cache_lag,
            "siem_success_1h": success_1h,
            "dlq": totals["dlq"],
            "capacity": capacity,
        })
    except Exception as e:
        return _err_with_log("cache_health", e, lang=lang)


@bp.route("/throughput", methods=["GET"])
@login_required
def api_cache_throughput():
    """Return ingest event and traffic counts for the last 1 hour and 24 hours."""
    import datetime as dt
    from sqlalchemy import func, select
    from src.pce_cache.models import PceEvent, PceTrafficFlowRaw
    lang = current_app.config["CM"].config.get('settings', {}).get('language', 'en')
    try:
        sf = _get_sf()
    except Exception as e:
        return jsonify({"error": t("gui_err_cache_not_configured", e=e, lang=lang)}), 503
    now = dt.datetime.now(dt.timezone.utc)
    hr = now - dt.timedelta(hours=1)
    day = now - dt.timedelta(hours=24)
    with sf() as s:
        ev = s.execute(select(func.count()).select_from(PceEvent)
                       .where(PceEvent.ingested_at >= hr)).scalar() or 0
        tr = s.execute(select(func.count()).select_from(PceTrafficFlowRaw)
                       .where(PceTrafficFlowRaw.ingested_at >= hr)).scalar() or 0
        tr24 = s.execute(select(func.count()).select_from(PceTrafficFlowRaw)
                         .where(PceTrafficFlowRaw.ingested_at >= day)).scalar() or 0
    return jsonify({"events_1h": int(ev), "traffic_raw_1h": int(tr), "traffic_agg_1h": 0,
                    "traffic_raw_24h": int(tr24)})


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


@bp.route("/archive/load", methods=["POST"])
@login_required
def load_archive():
    from datetime import date
    from src.pce_cache.archive_import import ArchiveLoadBusy, start_archive_load
    cm = current_app.config['CM']
    cfg = cm.models.pce_cache
    lang = cm.config.get('settings', {}).get('language', 'en')
    body = request.get_json(silent=True) or {}
    try:
        start = date.fromisoformat(body.get("start_date", ""))
        end = date.fromisoformat(body.get("end_date", ""))
    except (ValueError, TypeError):
        # ValueError=格式錯；TypeError=傳入 null/非字串（fromisoformat(None)）。兩者都回 400。
        return jsonify({"ok": False, "error": "invalid date (YYYY-MM-DD)"}), 400
    if end < start:
        return jsonify({"ok": False, "error": "end before start"}), 400
    span = (end - start).days + 1
    if span > int(cfg.archive_review_max_days):
        return jsonify({"ok": False,
                        "error": f"range {span}d exceeds max {cfg.archive_review_max_days}d"}), 422
    try:
        res = start_archive_load(cfg, start, end)
    except ArchiveLoadBusy:
        # 另一個 load 正在進行中（non-blocking lock 取得失敗）：立即回 409，不排隊。
        return jsonify({"ok": False,
                        "error": t("gui_traffic_archive_load_busy", lang=lang)}), 409
    except Exception as exc:  # noqa: BLE001
        return _err_with_log("cache_archive_load", exc, lang=lang)
    return jsonify({"ok": True, **res}), 202


@bp.route("/archive/status", methods=["GET"])
@login_required
def archive_status():
    from src.pce_cache.archive_import import review_status, load_progress
    cm = current_app.config['CM']
    lang = cm.config.get('settings', {}).get('language', 'en')
    try:
        st = review_status(cm.models.pce_cache)
        st["load"] = load_progress()
        return jsonify(st)
    except Exception as exc:  # noqa: BLE001
        return _err_with_log("cache_archive_status", exc, lang=lang)
