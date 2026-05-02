"""Shared runtime entry points for argparse and click CLIs.

Both src.main and src.cli.* delegate here so daemon startup logic
isn't duplicated between the legacy argparse path and click subcommands.
"""
from __future__ import annotations

import sys
import threading

from loguru import logger

from src.i18n import t


# ─── Shutdown signaling (shared by daemon entry points) ──────────────────────

_shutdown_event = threading.Event()


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
        # SIGTERM not available on Windows for non-console handlers; skip silently
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
        _register_signals()

    _shutdown_event.clear()

    from src.scheduler import build_scheduler
    from src.scheduler.jobs import run_monitor_cycle
    from src.siem.preview import emit_preview_warning

    emit_preview_warning(cm, context="daemon_startup")
    print(t("daemon_start", interval=interval))
    print(t("daemon_stop_hint"))
    logger.info("Starting scheduler-backed daemon (interval={}m)", interval)

    sched = build_scheduler(cm, interval_minutes=interval)

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
        # Guard against never-started scheduler raising SchedulerNotRunningError
        if getattr(sched, "running", False):
            sched.shutdown(wait=True)
        logger.info("Scheduler stopped")
        print(f"\n{t('daemon_stopped')}")


def run_gui_only(cm, port: int = 5001, host: str = "0.0.0.0") -> None:
    """Standalone Web GUI (no background daemon)."""
    from src.gui import launch_gui, HAS_FLASK, FLASK_IMPORT_ERROR

    if not HAS_FLASK:
        print(t("report_requires_flask"))
        if FLASK_IMPORT_ERROR:
            print(f"Import error: {FLASK_IMPORT_ERROR}")
        print(t("cli_pip_install_hint", pkg="flask"))
        sys.exit(1)
    launch_gui(cm, port=port)


def run_daemon_with_gui(cm, interval: int = 10, port: int = 5001, host: str = "0.0.0.0") -> None:
    """Headless monitoring loop running in background thread + Flask GUI in main thread."""
    logger.info(f"Starting daemon loop with Web GUI (interval={interval}m, port={port})")

    # Register signals here (main thread) — run_daemon_loop skips them when threaded
    _register_signals()

    # Start daemon in background thread
    t_daemon = threading.Thread(target=run_daemon_loop, args=(cm, interval), daemon=True)
    t_daemon.start()

    # Start Flask blocking in main thread
    from src.gui import launch_gui, HAS_FLASK
    if not HAS_FLASK:
        print(t("report_requires_flask"))
        print(t("cli_pip_install_hint", pkg="flask"))
        sys.exit(1)

    # Install restart hook so the GUI can restart the daemon scheduler.
    import src.gui as _gui
    from src.scheduler import build_scheduler

    def _restart():
        if _gui._DAEMON_SCHEDULER is not None and getattr(_gui._DAEMON_SCHEDULER, "running", False):
            _gui._DAEMON_SCHEDULER.shutdown(wait=False)
        cm.load()
        new_sched = build_scheduler(cm, interval_minutes=interval)
        new_sched.start()
        return new_sched

    _gui._GUI_OWNS_DAEMON = True
    _gui._DAEMON_RESTART_FN = _restart

    launch_gui(cm, port=port, persistent_mode=True)
