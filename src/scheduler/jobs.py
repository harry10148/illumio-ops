"""Job callables dispatched by the BackgroundScheduler."""
from __future__ import annotations

from loguru import logger
import os
import re

# Module-level imports required for test patching (patch targets must be attributes of this module)
from src.api_client import ApiClient
from src.gui._helpers import _resolve_state_file, _get_cache_engine
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
        logger.exception("Monitor cycle failed: {}", exc)
        mlog.error(f"Monitor cycle failed: {exc}")
        # Re-raise so the _instrument wrapper records job_health status=error
        # (swallowing here made the job-health panel report perpetual 'ok').
        raise

def tick_report_schedules(cm) -> None:
    """Check and fire any due report schedules."""
    from src.report_scheduler import ReportScheduler
    from src.reporter import Reporter

    try:
        scheduler = ReportScheduler(cm, Reporter(cm))
        scheduler.tick()
    except Exception as exc:
        logger.exception("Report schedule tick failed: {}", exc)
        raise  # surface to _instrument → job_health status=error

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
        logger.exception("Rule schedule tick failed: {}", exc)
        mlog.error(f"Rule schedule tick failed: {exc}")
        raise  # surface to _instrument → job_health status=error


def _record_ingest_pce_result(source: str, wm=None, fallback_error: str | None = None) -> None:
    """Mirror Analyzer's pce_stats.consecutive_failures bookkeeping for the
    cache-ingest scheduler path.

    Background: when pce_cache.enabled=true, Analyzer.run_analysis() reads
    events/traffic from the local cache and never calls the live PCE itself,
    so record_pce_error()/record_pce_success() (src/events/stats.py) were
    never invoked from that deployment shape and AL-6's watchdog
    (Analyzer._check_watchdog) was dead code — see
    .superpowers/sdd/live-verification-report.md finding #5.
    run_events_ingest/run_traffic_ingest are the only code that actually
    talks to the live PCE under pce_cache, so they now write into the SAME
    state.json pce_stats field (via StatsTracker, unchanged shape) that
    Analyzer reads back on its next load_state() call.

    Counting semantic: ONE shared counter across both ingest jobs, matching
    the legacy Analyzer path where health-check and event-poll failures
    already share the same consecutive_failures field. Any successful PCE
    pull resets it to 0; a failed pull increments it by 1 — evaluated
    per-invocation, not batched into an artificial "tick" across the two
    independently-scheduled jobs (events_poll_interval_seconds and
    traffic_poll_interval_seconds need not match). Effect: a full PCE outage
    (both jobs failing every invocation) climbs the counter monotonically
    and crosses WATCHDOG_FAILURE_THRESHOLD within a few cycles; a single
    chronically-broken ingestor with the other still healthy self-heals on
    every success from its sibling, so it never falsely trips the "PCE is
    unreachable" watchdog (that job's own log line / lag_monitor bookkeeping
    covers its own failures separately).

    wm: the WatermarkStore used by the ingestor this cycle. Its
    last_status/last_error (set by TrafficIngestor/EventsIngestor even when
    they swallow the underlying exception and return 0) is the ground truth
    for whether this ingest actually reached the PCE. When wm is None or has
    no row yet (e.g. the failure happened before the ingestor ran at all),
    fallback_error forces a failure record instead.
    """
    from src.events import StatsTracker
    from src.state_store import update_state_file

    success = True
    error = ""
    if wm is not None:
        row = wm.get(source)
        if row is not None:
            success = row.last_status != "error"
            if not success:
                error = row.last_error or ""
    if fallback_error is not None:
        success = False
        error = fallback_error

    def _update(existing: dict) -> dict:
        tracker = StatsTracker(existing)
        if success:
            tracker.record_pce_success(source, message="cache ingest ok")
        else:
            tracker.record_pce_error(source, error or "ingest failed")
        return tracker.state

    try:
        update_state_file(_resolve_state_file(), _update)
    except Exception as exc:
        logger.exception("Failed to persist ingest PCE stats for {}: {}", source, exc)


def _record_traffic_overflow(overflow: dict | None) -> None:
    """Mirror Analyzer's event_overflow bookkeeping for the traffic cache-
    ingest path.

    Background: TrafficIngestor's 1-min bisection floor (capacity-hardening
    Task 1, ingestor_traffic._fetch_window) can still hit max_results with no
    further bisection possible — that minute's flow data may be incomplete —
    but it only ever logged a WARNING; no reporter alert existed for it (see
    live-verification-report.md finding #7). Written into state.json under
    traffic_overflow (same shape as the legacy event_overflow key) so
    Analyzer._maybe_alert_overflow, now generalized to check both keys, can
    fire a distinct meta-alert for it.

    Always overwrites traffic_overflow with `overflow or {}` — mirrors
    Analyzer._fetch_event_batch, which clears event_overflow to {} on every
    poll that did NOT hit the cap, so a resolved overflow episode stops
    alerting on the next cycle. Callers must only invoke this after a
    successful fetch (see run_traffic_ingest) — a fetch failure tells us
    nothing about overflow and must not clobber a real unresolved episode.
    """
    from src.state_store import update_state_file

    def _update(existing: dict) -> dict:
        existing = dict(existing)
        existing["traffic_overflow"] = overflow or {}
        return existing

    try:
        update_state_file(_resolve_state_file(), _update)
    except Exception as exc:
        logger.exception("Failed to persist traffic_overflow state: {}", exc)


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
    wm = None
    try:
        from sqlalchemy.orm import sessionmaker
        from src.pce_cache.watermark import WatermarkStore
        from src.pce_cache.ingestor_events import EventsIngestor
        from src.api_client import ApiClient
        cfg = cm.models.pce_cache
        sf = sessionmaker(_get_cache_engine(cfg.db_path))
        wm = WatermarkStore(sf)
        with ApiClient(cm) as api:
            ing = EventsIngestor(api=api, session_factory=sf,
                                  watermark=wm,
                                  async_threshold=cfg.async_threshold_events,
                                  siem_destinations=_enabled_siem_destinations(cm, "audit"))
            count = ing.run_once()
        logger.info("Events ingest: {} rows inserted", count)
        _record_ingest_pce_result("events", wm)
    except Exception as exc:
        logger.exception("run_events_ingest failed: {}", exc)
        _record_ingest_pce_result("events", wm, fallback_error=str(exc))
        raise  # surface to _instrument → job_health status=error


def run_traffic_ingest(cm) -> None:
    wm = None
    try:
        from sqlalchemy.orm import sessionmaker
        from src.pce_cache.watermark import WatermarkStore
        from src.pce_cache.ingestor_traffic import TrafficIngestor
        from src.api_client import ApiClient
        cfg = cm.models.pce_cache
        sf = sessionmaker(_get_cache_engine(cfg.db_path))
        wm = WatermarkStore(sf)
        with ApiClient(cm) as api:
            ing = TrafficIngestor(api=api, session_factory=sf,
                                   watermark=wm,
                                   max_results=cfg.traffic_sampling.max_rows_per_batch,
                                   siem_destinations=_enabled_siem_destinations(cm, "traffic"))
            count = ing.run_once()
        logger.info("Traffic ingest: {} rows inserted", count)
        _record_ingest_pce_result("traffic", wm)
        row = wm.get(TrafficIngestor.SOURCE)
        if row is None or row.last_status != "error":
            _record_traffic_overflow(ing.last_run_overflow)
    except Exception as exc:
        logger.exception("run_traffic_ingest failed: {}", exc)
        _record_ingest_pce_result("traffic", wm, fallback_error=str(exc))
        raise  # surface to _instrument → job_health status=error


def run_traffic_aggregate(cm) -> None:
    try:
        from sqlalchemy.orm import sessionmaker
        from src.pce_cache.aggregator import TrafficAggregator
        cfg = cm.models.pce_cache
        sf = sessionmaker(_get_cache_engine(cfg.db_path))
        agg = TrafficAggregator(sf)
        count = agg.run_once()
        logger.info("Traffic aggregate: {} buckets updated", count)
    except Exception as exc:
        logger.exception("run_traffic_aggregate failed: {}", exc)
        raise  # surface to _instrument → job_health status=error


def run_cache_retention(cm) -> None:
    try:
        from sqlalchemy.orm import sessionmaker
        from src.pce_cache.retention import RetentionWorker
        cfg = cm.models.pce_cache
        sf = sessionmaker(_get_cache_engine(cfg.db_path))
        worker = RetentionWorker(sf)
        result = worker.run_once(
            events_days=cfg.events_retention_days,
            traffic_raw_days=cfg.traffic_raw_retention_days,
            traffic_agg_days=cfg.traffic_agg_retention_days,
            archive_enabled=cfg.archive_enabled,
        )
        logger.info("Cache retention purged: {}", result)
    except Exception as exc:
        logger.exception("run_cache_retention failed: {}", exc)
        raise  # surface to _instrument → job_health status=error


def run_cache_archive(cm) -> None:
    try:
        from sqlalchemy.orm import sessionmaker
        from src.pce_cache.archive import ArchiveExporter
        cfg = cm.models.pce_cache
        sf = sessionmaker(_get_cache_engine(cfg.db_path))
        exporter = ArchiveExporter(sf, archive_dir=cfg.archive_dir,
                                   gzip_after_days=cfg.archive_gzip_after_days,
                                   retention_days=cfg.archive_retention_days)
        result = exporter.run_once()
        logger.info("Cache archive exported: {}", result)
    except Exception as exc:
        logger.exception("run_cache_archive failed: {}", exc)
        raise  # surface to _instrument → job_health status=error


def run_ven_summary(cm) -> None:
    """Fetch managed workloads, compute a VEN health summary, write to dedicated store.

    Independent of pce_cache. Stored in logs/dashboard_summary.json["ven_summary"]
    so the dashboard overview reads it instantly without hitting the PCE per refresh,
    and the analyzer's monitor-cycle state writes never stomp it.
    On failure, last-good counts are preserved and last_error is recorded.
    """
    import datetime
    from src.dashboard_store import write_dashboard_summary
    from src.i18n import t

    _ONLINE = {"active", "online"}
    _THRESH_H = 1.0
    lang = cm.config.get("settings", {}).get("language", "en")
    now = datetime.datetime.now(datetime.timezone.utc)
    try:
        with ApiClient(cm) as api:
            # raise_on_error：PCE 失敗走下方 last_error 路徑，不得寫出 0/0
            workloads = api.fetch_managed_workloads(raise_on_error=True)
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
                if hslh is not None:
                    reason = t("ven_attention_no_heartbeat", lang=lang, hours=int(hslh))
                else:
                    status_label = status or t("ven_attention_status_unknown", lang=lang)
                    reason = t("ven_attention_status", lang=lang, status=status_label)
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
            "computed_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
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
        raise  # surface to _instrument → job_health status=error


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
        raise  # surface to _instrument → job_health status=error


def run_capacity_monitor(cm) -> None:
    """容量監控：唯讀，走 default executor（不佔 cache_writer）。"""
    from sqlalchemy.orm import sessionmaker as _SM
    from src.gui._helpers import _get_cache_engine
    from src.pce_cache.capacity import capacity_snapshot, capacity_warnings
    try:
        cfg = cm.models.pce_cache
        sf = _SM(_get_cache_engine(cfg.db_path))
        snap = capacity_snapshot(sf, cfg)
        logger.info(
            "Capacity: db={}MB free={}GB siem_pending={} archiver_lag={}",
            round(snap["db_bytes"] / (1 << 20), 1),
            (round(snap["disk_free_bytes"] / (1 << 30), 1)
             if snap["disk_free_bytes"] is not None else "n/a"),
            snap["siem_pending"], snap["archiver_lag_seconds"],
        )
        for msg in capacity_warnings(snap, cfg):
            logger.warning(msg)
    except Exception:
        logger.exception("Capacity monitor failed")
        raise  # surface to _instrument → job_health status=error


def run_siem_dispatch(cm) -> None:
    from sqlalchemy.orm import sessionmaker
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
        sf = sessionmaker(_get_cache_engine(cache_cfg.db_path))
        # 按 source_type 過濾補登目的地，比照 ingest 端 _enabled_siem_destinations
        # （見上方 run_events_ingest/run_traffic_ingest），避免 audit-only
        # destination 被補登 traffic rows（反之亦然）。
        dests_by_source_table = {
            "pce_events": _enabled_siem_destinations(cm, "audit"),
            "pce_traffic_flows_raw": _enabled_siem_destinations(cm, "traffic"),
        }
        new_count = enqueue_new_records(sf, dests_by_source_table)
        if new_count:
            logger.info("run_siem_dispatch: enqueued {} new records", new_count)
        for dest_cfg in enabled_dests:
            try:
                with build_dispatcher(dest_cfg, sf, dlq_max_per_dest=siem_cfg.dlq_max_per_dest) as dispatcher:
                    dispatcher.tick()
            except Exception as exc:
                logger.exception("run_siem_dispatch destination {!r} failed: {}", dest_cfg.name, exc)
    except Exception as exc:
        logger.exception("run_siem_dispatch failed: {}", exc)
        raise  # surface to _instrument → job_health status=error


def run_tls_renew_check(cm) -> None:
    """每日檢查 self-signed 憑證天數，低於門檻時就地重簽。

    限制：只落地憑證檔，執行中的 GUI listener 不會熱換——續期後記
    warning 提示重啟套用。到期天數的常態可視性由 overview 的 tls 卡涵蓋。
    """
    try:
        from src.gui._helpers import _maybe_auto_renew_self_signed, _ROOT_DIR
        tls_cfg = (cm.config.get("web_gui") or {}).get("tls") or {}
        cert_file = tls_cfg.get("cert_file")
        key_file = tls_cfg.get("key_file")
        if not (bool(tls_cfg.get("enabled")) and not (cert_file and key_file)
                and tls_cfg.get("self_signed", True) and tls_cfg.get("auto_renew", True)):
            return
        cert_dir = os.path.join(_ROOT_DIR, "config", "tls")
        threshold = int(tls_cfg.get("auto_renew_days", 30))
        renewed, days = _maybe_auto_renew_self_signed(cert_dir,
                                                      threshold_days=threshold)
        if renewed:
            logger.warning(
                "TLS self-signed cert renewed on disk ({} days remaining); "
                "restart the service to apply", days)
        else:
            logger.info("TLS cert check: {} days remaining", days)
    except Exception as exc:
        logger.exception("run_tls_renew_check failed: {}", exc)
        raise  # surface to _instrument → job_health status=error
