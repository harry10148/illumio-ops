"""BackgroundScheduler factory for illumio_ops daemon."""
from __future__ import annotations

from loguru import logger

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.executors.pool import ThreadPoolExecutor

from src.scheduler.jobs import (
    run_monitor_cycle,
    tick_report_schedules,
    tick_rule_schedules,
    run_ven_summary,
    run_posture_summary,
)
from src.siem.preview import emit_preview_warning
from src.i18n import t, get_language

def build_scheduler(cm, interval_minutes: int = 10) -> BackgroundScheduler:
    """Factory for a BackgroundScheduler wired with illumio_ops jobs.

    Does NOT call sched.start() — caller owns lifecycle.
    config.scheduler.persist is deprecated and no longer honored (see
    SchedulerSettings docstring): jobs always use the default in-memory
    job store; persist=true only logs a warning.
    """
    rule_interval = cm.config.get("rule_scheduler", {}).get("check_interval_seconds", 300)
    sched_cfg = cm.config.get("scheduler", {}) or {}

    if sched_cfg.get("persist"):
        logger.warning(
            "scheduler.persist=true is deprecated and no longer honored "
            "(SQLAlchemy job store removed — see SchedulerSettings docstring); "
            "ignoring, using in-memory job store"
        )

    executors = {
        "default": ThreadPoolExecutor(max_workers=5),
        # 單一 writer：SQLite 本就序列化寫者，強制這些 cache 批次 job 共用一個
        # worker → 消除 traffic/events ingest vs aggregate/retention/archive 的
        # 破壞性寫鎖競爭。慢 I/O 的 monitor_cycle/siem_dispatch 留在 default，
        # 避免反向阻塞 ingest。
        "cache_writer": ThreadPoolExecutor(max_workers=1),
    }
    job_defaults = {
        "coalesce": True,          # if we miss ticks during suspension, run just once
        "max_instances": 1,        # prevent concurrent re-entry
        "misfire_grace_time": 60,  # allow up to 60s late fire
    }

    kwargs: dict = {"executors": executors, "job_defaults": job_defaults}

    sched = BackgroundScheduler(**kwargs)

    # 長間隔 interval job 一律給近期首跑 kick（IntervalTrigger 預設首跑在啟動後
    # 一整個間隔；部署頻繁重啟會把首跑無限推遲——2026-07-14 archive 事故的通則化，
    # 秒級 tick job 不需要）。各 job 錯開偏移，避免啟動瞬間同時打 PCE/搶 executor。
    import datetime as _dt0
    _kick0 = _dt0.datetime.now(_dt0.timezone.utc) + _dt0.timedelta(seconds=10)

    # 每個 job 都包 instrument wrapper：執行後寫 logs/job_health.json 的
    # last_run/status（「應跑未跑」可觀測化，archive 事故根治配套）。
    # 註冊當下先種 registered 記錄，讓從未跑過的 job 立即可見。
    import functools as _ft
    from src.job_health import record_job_registered, record_job_run

    def _instrument(job_id, fn, interval_seconds):
        record_job_registered(job_id, interval_seconds)

        @_ft.wraps(fn)
        def _run(*args, **kwargs):
            try:
                result = fn(*args, **kwargs)
            except Exception as exc:
                record_job_run(job_id, "error", str(exc),
                               interval_seconds=interval_seconds)
                raise
            record_job_run(job_id, "ok", interval_seconds=interval_seconds)
            return result
        return _run

    try:
        _cache_enabled = cm.models.pce_cache.enabled
    except Exception as e:
        logger.warning("Cache config unavailable, defaulting to API interval: {}", e)
        _cache_enabled = False

    if _cache_enabled:
        monitor_trigger = IntervalTrigger(seconds=30)
        logger.info(t("monitor_cache_enabled_hint", lang=get_language()))
    else:
        monitor_trigger = IntervalTrigger(minutes=interval_minutes)

    sched.add_job(
        _instrument("monitor_cycle", run_monitor_cycle, 30 if _cache_enabled else interval_minutes * 60),
        trigger=monitor_trigger,
        args=[cm],
        id="monitor_cycle",
        name="Monitor analysis cycle",
        replace_existing=True,
        next_run_time=_kick0 + _dt0.timedelta(seconds=20),
    )
    sched.add_job(
        _instrument("tick_report_schedules", tick_report_schedules, 60),
        trigger=IntervalTrigger(seconds=60),
        args=[cm],
        id="tick_report_schedules",
        name="Report schedule tick",
        replace_existing=True,
    )
    sched.add_job(
        _instrument("tick_rule_schedules", tick_rule_schedules, rule_interval),
        trigger=IntervalTrigger(seconds=rule_interval),
        args=[cm],
        id="tick_rule_schedules",
        name="Rule schedule tick",
        replace_existing=True,
        next_run_time=_kick0 + _dt0.timedelta(seconds=40),
    )
    ven_summary_interval = int(
        cm.config.get("dashboard", {}).get("ven_summary_interval_seconds", 300)
    )
    sched.add_job(
        _instrument("ven_summary", run_ven_summary, ven_summary_interval),
        trigger=IntervalTrigger(seconds=ven_summary_interval),
        args=[cm],
        id="ven_summary",
        name="VEN status summary",
        replace_existing=True,
        next_run_time=_kick0 + _dt0.timedelta(seconds=60),
    )
    posture_summary_interval = int(
        cm.config.get("dashboard", {}).get("posture_summary_interval_seconds", 600)
    )
    sched.add_job(
        _instrument("posture_summary", run_posture_summary, posture_summary_interval),
        trigger=IntervalTrigger(seconds=posture_summary_interval),
        args=[cm],
        id="posture_summary",
        name="Posture score summary",
        replace_existing=True,
        next_run_time=_kick0 + _dt0.timedelta(seconds=80),
    )

    try:
        cache_cfg = cm.models.pce_cache
        if cache_cfg.enabled:
            import datetime as _dt
            from apscheduler.triggers.interval import IntervalTrigger as _IT
            from src.scheduler.jobs import (
                run_events_ingest, run_traffic_ingest,
                run_traffic_aggregate, run_cache_retention,
                run_cache_archive,
            )
            from src.pce_cache.lag_monitor import run_cache_lag_monitor
            # Fire ingest jobs ~10s after scheduler start so daemon restarts
            # don't keep resetting the timer to (now + full interval), which
            # previously kept periodic ingest from ever firing across many
            # restarts within one interval window.
            _kick = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(seconds=10)
            sched.add_job(_instrument("pce_cache_ingest_events", run_events_ingest, cache_cfg.events_poll_interval_seconds),
                          _IT(seconds=cache_cfg.events_poll_interval_seconds),
                          args=[cm], id="pce_cache_ingest_events", replace_existing=True,
                          next_run_time=_kick, executor="cache_writer")
            sched.add_job(_instrument("pce_cache_ingest_traffic", run_traffic_ingest, cache_cfg.traffic_poll_interval_seconds),
                          _IT(seconds=cache_cfg.traffic_poll_interval_seconds),
                          args=[cm], id="pce_cache_ingest_traffic", replace_existing=True,
                          next_run_time=_kick, executor="cache_writer")
            # aggregate/retention/archive 同樣需要首跑 kick（2026-07-14 真機事故：
            # 未帶 next_run_time 時 IntervalTrigger 首跑排在啟動後一整個間隔，
            # 部署頻繁重啟下 24h 間隔的 archive/retention 一次都沒跑過——
            # data/archive 恆空、retention 停刪、DB 無上限成長）。
            # kick 時間錯開，避免同刻搶 cache_writer 單 worker。
            sched.add_job(_instrument("pce_cache_aggregate", run_traffic_aggregate, 3600), _IT(hours=1),
                          args=[cm], id="pce_cache_aggregate", replace_existing=True,
                          next_run_time=_kick + _dt.timedelta(seconds=60),
                          executor="cache_writer")
            sched.add_job(_instrument("pce_cache_retention", run_cache_retention, 86400), _IT(hours=24),
                          args=[cm], id="pce_cache_retention", replace_existing=True,
                          next_run_time=_kick + _dt.timedelta(seconds=180),
                          executor="cache_writer")
            sched.add_job(_instrument("cache_lag_monitor", run_cache_lag_monitor, 60), _IT(seconds=60),
                          args=[cm], id="cache_lag_monitor", replace_existing=True)
            from src.scheduler.jobs import run_capacity_monitor
            # capacity monitor 是「應跑未跑」告警的看門狗，自己更不能被重啟餓死
            sched.add_job(_instrument("pce_cache_capacity_monitor", run_capacity_monitor, 1800), _IT(minutes=30),
                          args=[cm], id="pce_cache_capacity_monitor",
                          replace_existing=True,
                          next_run_time=_kick + _dt.timedelta(seconds=240))
            if cache_cfg.archive_enabled:
                sched.add_job(_instrument("pce_cache_archive", run_cache_archive, cache_cfg.archive_interval_hours * 3600),
                              _IT(hours=cache_cfg.archive_interval_hours),
                              args=[cm], id="pce_cache_archive", replace_existing=True,
                              next_run_time=_kick + _dt.timedelta(seconds=120),
                              executor="cache_writer")
    except Exception as exc:
        logger.exception("Failed to register pce_cache scheduler jobs: {}", exc)

    try:
        siem_cfg = cm.models.siem
        if siem_cfg.enabled:
            emit_preview_warning(cm, context="scheduler_startup")
            from apscheduler.triggers.interval import IntervalTrigger as _IT
            from src.scheduler.jobs import run_siem_dispatch
            sched.add_job(_instrument("siem_dispatch", run_siem_dispatch, siem_cfg.dispatch_tick_seconds),
                          _IT(seconds=siem_cfg.dispatch_tick_seconds),
                          args=[cm], id="siem_dispatch", replace_existing=True)
    except Exception as exc:
        logger.exception("Failed to register SIEM scheduler jobs: {}", exc)

    logger.info(
        "Scheduler built: monitor={}m report=60s rule={}s",
        interval_minutes,
        rule_interval,
    )
    return sched
