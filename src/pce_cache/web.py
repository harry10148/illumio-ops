"""Flask Blueprint for PCE cache management endpoints."""
from __future__ import annotations

import threading

from flask import Blueprint, current_app, jsonify, request
from flask_login import login_required
from loguru import logger

from src.i18n import t
from src.gui._helpers import _err_with_log

bp = Blueprint("pce_cache", __name__, url_prefix="/api/cache")

# 同時只允許一個 backfill 在跑（non-blocking lock）：backfill + 全量
# aggregator 重算是長跑寫入，兩個併發 POST 會互搶 SQLite 寫鎖並重複灌
# 同一批列。第二個請求立即回 409，不排隊。
_BACKFILL_LOCK = threading.Lock()

# 同時只允許一個手動 retention purge（同 _BACKFILL_LOCK 模式）：purge 是一連串
# 不設上限的 10k 列 DELETE 交易，端點又是同步執行在 cheroot 請求執行緒上，看起來
# 像卡住。操作者重按或瀏覽器重送就會有兩個請求同時跑重疊的刪除迴圈，與排程的
# pce_cache_retention（cache_writer 單工執行緒）互搶 SQLite 寫鎖。第二個請求直接
# 回 409，不排隊。
_RETENTION_LOCK = threading.Lock()


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
    from datetime import datetime, timedelta, timezone
    data = request.get_json(silent=True) or {}
    lang = data.get('lang') or current_app.config["CM"].config.get('settings', {}).get('language', 'en')
    source = data.get("source", "events")
    since_str = data.get("since")
    until_str = data.get("until")
    if not since_str:
        return jsonify({"error": t("gui_err_cache_missing_since", lang=lang)}), 400
    try:
        since_dt = datetime.strptime(since_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        # until 為含端點語意（GUI 標示 End date；/archive/load 的 [start, end]
        # 亦含端點）：解析出的午夜 +1 天成為排他上界，讓 until 當天整天入窗，
        # 而非靜默丟掉最後一天。
        until_dt = (
            datetime.strptime(until_str, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1)
            if until_str else datetime.now(timezone.utc)
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    try:
        sf = _get_sf()
    except Exception as e:
        return _err_with_log("cache_backfill", e, status=503, lang=lang)
    if not _BACKFILL_LOCK.acquire(blocking=False):
        return jsonify({"error": "backfill already in progress"}), 409
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
            # （aggregator 現另有游標式 backfill 偵測，此處全量重算是雙保險。）
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
    finally:
        _BACKFILL_LOCK.release()


@bp.route("/retention/run", methods=["POST"])
@login_required
def api_cache_retention_run():
    """Run retention purge immediately using configured retention days."""
    lang = current_app.config["CM"].config.get('settings', {}).get('language', 'en')
    try:
        sf = _get_sf()
    except Exception as e:
        # 不把原始例外（可含 SQL/engine/路徑細節）回給 client——經 _err_with_log
        # 記 server-side traceback、回通用訊息 + request_id（H3 慣例）。
        return _err_with_log("cache_retention_run", e, status=503, lang=lang)
    cfg = current_app.config["CM"].models.pce_cache
    if not _RETENTION_LOCK.acquire(blocking=False):
        return jsonify({"error": "retention already in progress"}), 409
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
    finally:
        _RETENTION_LOCK.release()


@bp.route("/status", methods=["GET"])
@login_required
def api_cache_status():
    """Return cache row counts."""
    lang = current_app.config["CM"].config.get('settings', {}).get('language', 'en')
    try:
        sf = _get_sf()
    except Exception as e:
        return _err_with_log("cache_status", e, status=503, lang=lang)
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
        return _err_with_log("cache_lag", e, status=503, lang=lang)
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
    except Exception:
        # 保留 {"verdict": ...} 形狀（health widget 依賴），但不外洩原始例外：
        # traceback 記 server-side，client 只拿通用訊息。
        logger.exception("[GUI:cache_health] _get_sf failed")
        return jsonify({"verdict": "unknown",
                        "note": t("gui_err_internal", default="Internal server error", lang=lang)}), 503
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
                      "level": r["level"], "last_status": r.get("last_status")}
                     for r in lag]
        levels = [c["level"] for c in cache_lag]
        source_statuses = [c["last_status"] for c in cache_lag]

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
            source_statuses=source_statuses,
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
        return _err_with_log("cache_throughput", e, status=503, lang=lang)
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


@bp.route("/archive/status", methods=["GET"])
@login_required
def archive_status():
    """archive 檔案本身的概況（目錄是否存在、檔案數、涵蓋的最早/最晚日期）
    ——不是某次匯入的結果。封存查閱（POST /api/quarantine/search 的
    source=archive 分支）自 Task 4 起直接串流封存日檔，不再有 review DB
    可回報「已載入」；這裡改回報 archive_dir 底下真的有什麼。"""
    from src.pce_cache.archive_query import archive_file_range
    cm = current_app.config['CM']
    lang = cm.config.get('settings', {}).get('language', 'en')
    try:
        return jsonify(archive_file_range(cm.models.pce_cache.archive_dir))
    except Exception as exc:  # noqa: BLE001
        return _err_with_log("cache_archive_status", exc, lang=lang)
