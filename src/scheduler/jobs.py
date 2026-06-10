"""Job callables dispatched by the BackgroundScheduler."""
from __future__ import annotations

from loguru import logger
import os
import re

# Module-level imports required for test patching (patch targets must be attributes of this module)
from src.api_client import ApiClient
from src.gui._helpers import _resolve_state_file
from src.report.snapshot_store import read_latest


def run_monitor_cycle(cm) -> None:
    """Execute one monitoring analysis + alert dispatch."""
    from src.api_client import ApiClient
    from src.analyzer import Analyzer
    from src.reporter import Reporter
    from src.module_log import ModuleLog
    from src.main import _make_subscribers, _make_cache_reader

    mlog = ModuleLog.get("monitor")
    try:
        mlog.info("Starting monitor cycle")
        with ApiClient(cm) as api:
            rep = Reporter(cm)
            sub_events, sub_flows = _make_subscribers(cm)
            ana = Analyzer(cm, api, rep,
                           subscriber_events=sub_events, subscriber_flows=sub_flows,
                           cache_reader=_make_cache_reader(cm))
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
        with ApiClient(cm) as api:
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


def _enabled_siem_destinations(cm, source_type: str) -> list[str]:
    """Return enabled destination names that subscribe to the given source_type."""
    siem_cfg = cm.models.siem
    if not siem_cfg.enabled:
        return []
    return [
        d.name for d in (siem_cfg.destinations or [])
        if d.enabled and source_type in (d.source_types or [])
    ]


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
        with ApiClient(cm) as api:
            ing = EventsIngestor(api=api, session_factory=sf,
                                  watermark=WatermarkStore(sf),
                                  async_threshold=cfg.async_threshold_events,
                                  siem_destinations=_enabled_siem_destinations(cm, "audit"))
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
        with ApiClient(cm) as api:
            ing = TrafficIngestor(api=api, session_factory=sf,
                                   watermark=WatermarkStore(sf),
                                   max_results=cfg.traffic_sampling.max_rows_per_batch,
                                   siem_destinations=_enabled_siem_destinations(cm, "traffic"))
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


def run_ven_summary(cm) -> None:
    """Fetch managed workloads, compute a VEN health summary, write to dedicated store.

    Independent of pce_cache. Stored in logs/dashboard_summary.json["ven_summary"]
    so the dashboard overview reads it instantly without hitting the PCE per refresh,
    and the analyzer's monitor-cycle state writes never stomp it.
    On failure, last-good counts are preserved and last_error is recorded.
    """
    import datetime
    from src.dashboard_store import write_dashboard_summary

    _ONLINE = {"active", "online"}
    _THRESH_H = 1.0
    now = datetime.datetime.now(datetime.timezone.utc)
    try:
        with ApiClient(cm) as api:
            workloads = api.fetch_managed_workloads()
        total = online = 0
        attention = []
        oldest_age = 0.0
        for w in workloads or []:
            st = (w.get("agent") or {}).get("status") or {}
            total += 1
            status = str(st.get("status", "")).lower()
            # Try PCE-computed field first; fall back to computing from timestamp
            hslh = st.get("hours_since_last_heartbeat")
            try:
                hslh = float(hslh) if hslh is not None else None
            except (TypeError, ValueError):
                hslh = None
            if hslh is None:
                hb_str = st.get("last_heartbeat_on")
                if hb_str:
                    try:
                        hb_dt = datetime.datetime.fromisoformat(
                            hb_str.replace("Z", "+00:00"))
                        hslh = (now - hb_dt).total_seconds() / 3600
                    except Exception:
                        pass
            is_online = status in _ONLINE and hslh is not None and hslh <= _THRESH_H
            if is_online:
                online += 1
            else:
                host = w.get("hostname") or w.get("name") or "?"
                reason = (f"{int(hslh)}h no heartbeat" if hslh is not None
                          else f"status={status or 'unknown'}")
                attention.append({"host": host, "reason": reason})
            if hslh is not None:
                oldest_age = max(oldest_age, hslh * 3600.0)
        from src.report.analysis import estate_inventory
        summary = {
            "total": total, "online": online, "offline": total - online,
            "degraded": 0,
            "oldest_heartbeat_age_s": int(oldest_age),
            "attention": attention[:20],
            "updated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "os_distribution": estate_inventory.os_distribution(workloads or []),
            "enforcement_distribution": estate_inventory.enforcement_distribution(workloads or []),
        }
        write_dashboard_summary(lambda d: {**d, "ven_summary": summary})
        logger.info("VEN summary: {}/{} online", online, total)
    except Exception as exc:
        logger.exception("run_ven_summary failed: {}", exc)
        def _mark_err(d):
            vs = dict((d.get("ven_summary") or {}))
            vs["last_error"] = str(exc)[:300]
            vs["updated_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
            return {**d, "ven_summary": vs}
        try:
            write_dashboard_summary(_mark_err)
        except Exception:
            pass


def run_posture_summary(cm) -> None:
    """Read latest traffic snapshot, compute posture score, write to state.

    Reads snapshot only — no heavy analysis.  Written to state["posture_summary"]
    so /api/dashboard/overview can return it instantly without any computation.
    On failure or missing snapshot, writes {"available": False}.
    """
    import datetime
    from src.state_store import update_state_file
    from src.report.posture import compute_posture

    now = datetime.datetime.now(datetime.timezone.utc)
    try:
        snap = read_latest("traffic")
        if snap is None:
            update_state_file(_resolve_state_file(),
                              lambda s: {**s, "posture_summary": {"available": False}})
            return
        from src.report.posture_advisor import build_remediation
        posture = compute_posture(snap.get("kpis") or snap)
        posture["remediation"] = build_remediation(posture)
        posture["generated_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        posture["source_date"] = snap.get("generated_at", "")
        update_state_file(_resolve_state_file(),
                          lambda s: {**s, "posture_summary": posture})
        logger.info("Posture summary: score={}", posture.get("score"))
    except Exception as exc:
        logger.warning("run_posture_summary failed: {}", exc)
        try:
            update_state_file(_resolve_state_file(),
                              lambda s: {**s, "posture_summary": {"available": False}})
        except Exception:
            pass


def run_siem_dispatch(cm) -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src.pce_cache.schema import init_schema
    from src.siem.dispatcher import enqueue_new_records, build_dispatcher
    try:
        siem_cfg = cm.models.siem
        if not siem_cfg.enabled:
            return
        enabled_dests = [d for d in (siem_cfg.destinations or []) if d.enabled]
        if not enabled_dests:
            logger.debug("run_siem_dispatch: no enabled destinations configured")
            return
        cache_cfg = cm.models.pce_cache
        engine = create_engine(f"sqlite:///{cache_cfg.db_path}")
        init_schema(engine)
        sf = sessionmaker(engine)
        dest_names = [d.name for d in enabled_dests]
        new_count = enqueue_new_records(sf, dest_names)
        if new_count:
            logger.info("run_siem_dispatch: enqueued {} new records", new_count)
        for dest_cfg in enabled_dests:
            try:
                with build_dispatcher(dest_cfg, sf) as dispatcher:
                    dispatcher.tick()
            except Exception as exc:
                logger.exception("run_siem_dispatch destination {!r} failed: {}", dest_cfg.name, exc)
    except Exception as exc:
        logger.exception("run_siem_dispatch failed: {}", exc)
