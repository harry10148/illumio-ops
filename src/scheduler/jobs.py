"""Job callables dispatched by the BackgroundScheduler."""
from __future__ import annotations

from loguru import logger
import os
import re

def run_monitor_cycle(cm) -> None:
    """Execute one monitoring analysis + alert dispatch."""
    from src.api_client import ApiClient
    from src.analyzer import Analyzer
    from src.reporter import Reporter
    from src.module_log import ModuleLog

    mlog = ModuleLog.get("monitor")
    try:
        mlog.info("Starting monitor cycle")
        api = ApiClient(cm)
        rep = Reporter(cm)
        ana = Analyzer(cm, api, rep)
        ana.run_analysis()
        rep.send_alerts()
        mlog.info("Monitor cycle complete")
    except Exception as exc:
        logger.error("Monitor cycle failed: {}", exc, exc_info=True)
        mlog.error(f"Monitor cycle failed: {exc}")

def tick_report_schedules(cm) -> None:
    """Check and fire any due report schedules."""
    from src.report_scheduler import ReportScheduler
    from src.reporter import Reporter

    try:
        scheduler = ReportScheduler(cm, Reporter(cm))
        scheduler.tick()
    except Exception as exc:
        logger.error("Report schedule tick failed: {}", exc, exc_info=True)

def tick_rule_schedules(cm) -> None:
    """Check and fire any due rule schedules."""
    from src.rule_scheduler import ScheduleDB, ScheduleEngine
    from src.module_log import ModuleLog

    mlog = ModuleLog.get("rule_scheduler")
    try:
        pkg_dir = os.path.dirname(os.path.abspath(__file__))
        root_dir = os.path.dirname(os.path.dirname(pkg_dir))
        db_path = os.path.join(root_dir, "config", "rule_schedules.json")
        db = ScheduleDB(db_path)
        db.load()
        tz = cm.config.get("settings", {}).get("timezone", "local")
        from src.api_client import ApiClient
        api = ApiClient(cm)
        engine = ScheduleEngine(db, api)
        logs = engine.check(silent=True, tz_str=tz)
        for msg in logs:
            clean = re.sub(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])", "", msg)
            logger.info("[RuleScheduler] {}", clean)
            mlog.info(clean)
        try:
            from src.gui import _append_rs_logs
            _append_rs_logs(logs)
        except Exception:
            pass  # intentional fallback: GUI log append is optional; schedule tick must not fail if GUI is unavailable
    except Exception as exc:
        logger.error("Rule schedule tick failed: {}", exc, exc_info=True)
        mlog.error(f"Rule schedule tick failed: {exc}")


def run_events_ingest(cm) -> None:
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from src.pce_cache.schema import init_schema
        from src.pce_cache.watermark import WatermarkStore
        from src.pce_cache.ingestor_events import EventsIngestor
        from src.api_client import ApiClient
        cfg = cm.models.pce_cache
        engine = create_engine(f"sqlite:///{cfg.db_path}")
        init_schema(engine)
        sf = sessionmaker(engine)
        api = ApiClient(cm)
        ing = EventsIngestor(api=api, session_factory=sf,
                              watermark=WatermarkStore(sf),
                              async_threshold=cfg.async_threshold_events)
        count = ing.run_once()
        logger.info("Events ingest: {} rows inserted", count)
    except Exception as exc:
        logger.exception("run_events_ingest failed: {}", exc)


def run_traffic_ingest(cm) -> None:
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from src.pce_cache.schema import init_schema
        from src.pce_cache.watermark import WatermarkStore
        from src.pce_cache.ingestor_traffic import TrafficIngestor
        from src.api_client import ApiClient
        cfg = cm.models.pce_cache
        engine = create_engine(f"sqlite:///{cfg.db_path}")
        init_schema(engine)
        sf = sessionmaker(engine)
        api = ApiClient(cm)
        ing = TrafficIngestor(api=api, session_factory=sf,
                               watermark=WatermarkStore(sf),
                               max_results=cfg.traffic_sampling.max_rows_per_batch)
        count = ing.run_once()
        logger.info("Traffic ingest: {} rows inserted", count)
    except Exception as exc:
        logger.exception("run_traffic_ingest failed: {}", exc)


def run_traffic_aggregate(cm) -> None:
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from src.pce_cache.schema import init_schema
        from src.pce_cache.aggregator import TrafficAggregator
        cfg = cm.models.pce_cache
        engine = create_engine(f"sqlite:///{cfg.db_path}")
        init_schema(engine)
        sf = sessionmaker(engine)
        agg = TrafficAggregator(sf)
        count = agg.run_once()
        logger.info("Traffic aggregate: {} buckets updated", count)
    except Exception as exc:
        logger.exception("run_traffic_aggregate failed: {}", exc)


def run_cache_retention(cm) -> None:
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from src.pce_cache.schema import init_schema
        from src.pce_cache.retention import RetentionWorker
        cfg = cm.models.pce_cache
        engine = create_engine(f"sqlite:///{cfg.db_path}")
        init_schema(engine)
        sf = sessionmaker(engine)
        worker = RetentionWorker(sf)
        result = worker.run_once(
            events_days=cfg.events_retention_days,
            traffic_raw_days=cfg.traffic_raw_retention_days,
            traffic_agg_days=cfg.traffic_agg_retention_days,
        )
        logger.info("Cache retention purged: {}", result)
    except Exception as exc:
        logger.exception("run_cache_retention failed: {}", exc)


def run_siem_dispatch(cm) -> None:
    try:
        logger.debug("SIEM dispatch tick (destinations configured via siem.destinations)")
    except Exception as exc:
        logger.exception("run_siem_dispatch failed: {}", exc)
