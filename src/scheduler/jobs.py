"""Job callables dispatched by the BackgroundScheduler."""
from __future__ import annotations

import logging
import os
import re

logger = logging.getLogger(__name__)


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
        logger.error("Monitor cycle failed: %s", exc, exc_info=True)
        mlog.error(f"Monitor cycle failed: {exc}")


def tick_report_schedules(cm) -> None:
    """Check and fire any due report schedules."""
    from src.report_scheduler import ReportScheduler
    from src.reporter import Reporter

    try:
        scheduler = ReportScheduler(cm, Reporter(cm))
        scheduler.tick()
    except Exception as exc:
        logger.error("Report schedule tick failed: %s", exc, exc_info=True)


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
            logger.info("[RuleScheduler] %s", clean)
            mlog.info(clean)
        try:
            from src.gui import _append_rs_logs
            _append_rs_logs(logs)
        except Exception:
            pass
    except Exception as exc:
        logger.error("Rule schedule tick failed: %s", exc, exc_info=True)
        mlog.error(f"Rule schedule tick failed: {exc}")
