"""Shared runtime entry points for argparse and click CLIs.

Both src.main and src.cli.* delegate here so daemon startup logic
isn't duplicated between the legacy argparse path and click subcommands.
"""
from __future__ import annotations

import sys
import threading
import time

from loguru import logger

from src.i18n import t

# _gui_stopper 等 cheroot server 物件出現的上限（秒）。systemd 的
# TimeoutStopSec=30，留足夠餘裕但不超過它。
_GUI_STOPPER_DEADLINE_S = 20.0


# ─── Shutdown signaling (shared by daemon entry points) ──────────────────────

_shutdown_event = threading.Event()

# 目前存活的 BackgroundScheduler。run_daemon_loop 建好就登記在這裡，GUI 的
# 「重啟 daemon」(_restart) 必須先關掉它——否則第一次重啟會讓同一個行程同時
# 跑兩個 scheduler、同一組 job id 各跑一次（SIEM 事件重送、排程報表重寄、
# pce_cache 單一 writer 不變式被破壞），而且舊的那個從此無法再被關閉。
# 原本只看 src.gui._DAEMON_SCHEDULER，但那個變數只有「重啟之後」才會被指派，
# 第一次重啟時必為 None，守門形同虛設。
_active_scheduler = None
_active_scheduler_lock = threading.Lock()


def _publish_scheduler(sched) -> None:
    global _active_scheduler
    with _active_scheduler_lock:
        _active_scheduler = sched


def _current_scheduler():
    with _active_scheduler_lock:
        return _active_scheduler


def _shutdown_scheduler(sched, wait: bool) -> None:
    """關閉一個 scheduler；已停止/未啟動者直接略過。"""
    if sched is None:
        return
    if not getattr(sched, "running", False):
        return
    try:
        sched.shutdown(wait=wait)
    except Exception as exc:  # SchedulerNotRunningError 等競態
        logger.warning("scheduler shutdown raised: {}", exc)


def _signal_handler(signum, _frame):
    logger.info(f"Received signal {signum}. Shutting down gracefully...")
    _shutdown_event.set()


def _register_signals():
    """Register SIGINT/SIGTERM handlers. Must only be called from the main thread."""
    import signal as _signal
    _signal.signal(_signal.SIGINT, _signal_handler)
    try:
        _signal.signal(_signal.SIGTERM, _signal_handler)
    except (AttributeError, ValueError):
        # signal.signal() raises ValueError when called outside the main thread;
        # skip silently in that case rather than crashing the caller.
        # AttributeError is defensive only: it used to cover Windows, which has
        # no SIGTERM. Every platform we still support defines it, but signal
        # registration is best-effort here, so keep swallowing it.
        pass


# ─── Daemon entry points ─────────────────────────────────────────────────────

def run_daemon_loop(cm, interval: int = 10) -> None:
    """Headless monitoring loop — APScheduler-backed.

    Replaces the previous self-rolled while/wait(60) loop with a
    BackgroundScheduler (3 jobs: monitor_cycle, tick_report_schedules,
    tick_rule_schedules).  Resolves Status.md A3 (single-threaded blocking).
    """
    # Signal handlers can only be registered from the main thread.
    # When called as a background thread (run_daemon_with_gui), the caller
    # registers signals before spawning; skip here to avoid ValueError.
    if threading.current_thread() is threading.main_thread():
        # 只有「自己就是主執行緒」這條路徑才在這裡清事件。被 run_daemon_with_gui
        # 當成背景 thread 起動時，主執行緒已在 spawn 前清過；在這裡再清一次會把
        # 「_register_signals() 之後、thread 起來之前」收到的 SIGTERM 抹掉，
        # 讓整個行程忽略該訊號直到 systemd TimeoutStopSec 逾時 SIGKILL。
        _shutdown_event.clear()
        _register_signals()

    from src.scheduler import build_scheduler
    from src.scheduler.jobs import run_monitor_cycle

    print(t("daemon_start", interval=interval))
    print(t("daemon_stop_hint"))
    logger.info("Starting scheduler-backed daemon (interval={}m)", interval)

    sched = build_scheduler(cm, interval_minutes=interval)
    # 登記為「目前存活的 scheduler」，讓 GUI 的重啟按鈕找得到它並先關閉。
    _publish_scheduler(sched)

    try:
        # C2: start() inside try so a startup failure doesn't trigger shutdown
        # of a never-started scheduler (would raise SchedulerNotRunningError).
        sched.start()

        # Fire the first monitor cycle immediately without blocking signal-driven
        # shutdown of the daemon entrypoint.
        threading.Thread(target=run_monitor_cycle, args=(cm,), daemon=True).start()

        # Block until shutdown signal (1-second poll keeps signal responsive)
        while not _shutdown_event.is_set():
            _shutdown_event.wait(timeout=1)
    finally:
        logger.info("Shutting down scheduler...")
        # 關掉自己建的那個，以及「目前存活的」那個（GUI 重啟後兩者不同——
        # 只關 sched 會把重啟後的 scheduler 留著跑，行程收到 SIGTERM 也不停）。
        current = _current_scheduler()
        _shutdown_scheduler(sched, wait=True)
        if current is not sched:
            _shutdown_scheduler(current, wait=True)
        if _current_scheduler() is current:
            _publish_scheduler(None)
        logger.info("Scheduler stopped")
        print(f"\n{t('daemon_stopped')}")


def run_gui_only(cm, port: int = 5001, host: str = "0.0.0.0") -> None:
    """Standalone Web GUI (no background daemon)."""
    from src.gui import launch_gui, HAS_FLASK, FLASK_IMPORT_ERROR

    if not HAS_FLASK:
        print(t("report_requires_flask"))
        if FLASK_IMPORT_ERROR:
            print(f"{t('cli_import_error', default='Import error')}: {FLASK_IMPORT_ERROR}")
        print(t("cli_pip_install_hint", pkg="flask"))
        sys.exit(1)

    # GUI-only mode runs no scheduler, so PCE cache ingestion/aggregation/retention
    # never fire automatically — the cache only fills via manual Backfill. Warn loudly
    # so a cache-enabled deployment isn't silently left without live ingestion.
    try:
        if cm.models.pce_cache.enabled:
            logger.warning(
                "GUI-only mode: PCE cache is enabled but no scheduler runs here — "
                "automatic ingestion/aggregation/retention will NOT fire (manual Backfill "
                "only). Use 'monitor-gui' for live cache ingestion."
            )
    except Exception as e:
        logger.debug("cache-enabled check skipped in gui-only mode: {}", e)

    launch_gui(cm, host=host, port=port)


def _report_cache_provenance(cm) -> None:
    """Say once, at start, which PCE the cache belongs to.

    Advisory only — it never blocks the daemon. Refusing belongs to the ingest
    path (scheduler/jobs.py's `_guard_cache_target`), where there is a write to
    refuse; exiting here would take the GUI down too, over a condition the
    operator fixes in that very GUI.

    What this adds is timing: it is the only place that speaks *before* the first
    ingest binds an unbound cache, which is the one window where an appliance
    re-pointed prior to this check existing can still be noticed.

    Never fatal. A cache that cannot be opened is the ingest path's problem to
    report; a startup advisory that could crash the daemon would be a worse bug
    than the one it warns about.
    """
    try:
        cfg = cm.models.pce_cache
        if not cfg.enabled:
            return
        from sqlalchemy.orm import sessionmaker
        from src.gui._helpers import _get_cache_engine
        from src.pce_cache.provenance import verify_at_startup
        verify_at_startup(sessionmaker(_get_cache_engine(cfg.db_path)),
                          cm.models.api.model_dump())
    except Exception as exc:  # noqa: BLE001 - advisory only, see docstring
        logger.warning("Could not check PCE cache provenance at startup: {}", exc)


def run_daemon_with_gui(cm, interval: int = 10, port: int = 5001, host: str = "0.0.0.0") -> None:
    """Headless monitoring loop running in background thread + Flask GUI in main thread."""
    logger.info(f"Starting daemon loop with Web GUI (interval={interval}m, port={port})")

    # Import the GUI + scheduler module graphs in the MAIN thread BEFORE spawning
    # the daemon thread. The daemon thread pulls in src.scheduler.jobs (→
    # src.gui._helpers) while this thread pulls in src.gui (→ src.gui._helpers);
    # importing the shared graph concurrently from two threads makes CPython's
    # import lock raise _DeadlockError on the cross-thread import cycle. Doing the
    # imports single-threaded here populates sys.modules so the daemon thread only
    # ever finds already-imported modules.
    from src.gui import launch_gui, HAS_FLASK
    import src.gui as _gui
    from src.scheduler import build_scheduler  # noqa: F401  (also imports src.scheduler.jobs)

    if not HAS_FLASK:
        print(t("report_requires_flask"))
        print(t("cli_pip_install_hint", pkg="flask"))
        sys.exit(1)

    _report_cache_provenance(cm)

    # Clear BEFORE registering signals: run_daemon_loop no longer clears when it
    # runs as a background thread, so a SIGTERM arriving right after registration
    # can no longer be swallowed by the daemon thread's late clear().
    _shutdown_event.clear()

    # Register signals here (main thread) — run_daemon_loop skips them when threaded
    _register_signals()

    # Start daemon in background thread (module graph already imported above)
    t_daemon = threading.Thread(target=run_daemon_loop, args=(cm, interval), daemon=True)
    t_daemon.start()

    def _restart():
        # 先關掉「目前存活的」scheduler。舊版只看 _gui._DAEMON_SCHEDULER，而那個
        # 變數要等第一次重啟完成才會被指派，導致第一次重啟不會關掉 daemon thread
        # 建的那個——兩個 scheduler 同時跑，每個 job 都跑兩次。
        for old in (_current_scheduler(), _gui._DAEMON_SCHEDULER):
            _shutdown_scheduler(old, wait=False)
        cm.load()
        new_sched = build_scheduler(cm, interval_minutes=interval)
        new_sched.start()
        _publish_scheduler(new_sched)
        return new_sched

    _gui._GUI_OWNS_DAEMON = True
    _gui._DAEMON_RESTART_FN = _restart

    # Stop the cheroot server when SIGTERM fires so the main thread unblocks
    # instead of waiting for systemd's 90-second TimeoutStopSec to expire.
    def _gui_stopper():
        _shutdown_event.wait()
        # _active_server 只在 launch_gui 完成 cm.load()/build_app()/（自簽）憑證
        # 產生之後、server.start() 之前才被指派。啟動期間收到 SIGTERM 時它還是
        # None——只看一次就結束會讓 cheroot 永遠不被停掉，主執行緒接著開始服務，
        # 但 daemon thread 已經關掉 scheduler（GUI 活著、零背景工作）。改成有上限
        # 的輪詢等它出現。
        deadline = time.monotonic() + _GUI_STOPPER_DEADLINE_S
        while time.monotonic() < deadline:
            server = _gui._active_server
            if server is not None:
                try:
                    server.stop()
                except Exception:
                    pass
                break
            time.sleep(0.1)
        else:
            logger.warning(
                "shutdown requested before the Web GUI server came up; "
                "cheroot was never started within {}s", _GUI_STOPPER_DEADLINE_S)
        # Propagate shutdown to gui's _rs_background_scheduler if running
        _gui._shutdown_event.set()

    threading.Thread(target=_gui_stopper, daemon=True).start()

    launch_gui(cm, host=host, port=port, persistent_mode=True)

    # After launch_gui returns (server stopped), join the daemon thread so the
    # background scheduler exits cooperatively before the process terminates.
    if t_daemon is not None:
        t_daemon.join(timeout=10)
        if t_daemon.is_alive():
            logger.warning("background scheduler thread did not exit within 10s — proceeding with hard shutdown")
