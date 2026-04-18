import sys
import os
from loguru import logger
import argparse
from src.utils import setup_logger, Colors, safe_input, draw_panel, get_terminal_width, Spinner
from src.config import ConfigManager
from src.api_client import ApiClient
from src.analyzer import Analyzer
from src.reporter import Reporter
from src.settings import (
    settings_menu,
    add_event_menu,
    add_system_health_menu,
    add_traffic_menu,
    add_bandwidth_volume_menu,
    manage_rules_menu,
    manage_report_schedules_menu,
)
from src.i18n import t, get_language

LOG_FILE = ""  # To be set in main() or main_menu()

# ─── Daemon / Monitor Loop ───────────────────────────────────────────────────

import threading

_shutdown_event = threading.Event()

def _signal_handler(signum, _frame):
    logger.info(f"Received signal {signum}. Shutting down gracefully...")
    _shutdown_event.set()

def run_daemon_loop(interval_minutes: int):
    """Headless monitoring loop — APScheduler-backed.

    Replaces the previous self-rolled while/wait(60) loop with a
    BackgroundScheduler (3 jobs: monitor_cycle, tick_report_schedules,
    tick_rule_schedules).  Resolves Status.md A3 (single-threaded blocking).
    """
    import signal as _signal

    # C1: Register signal handlers so SIGINT/SIGTERM trigger graceful shutdown
    # (previous self-rolled loop had these; must preserve for systemd/docker)
    _signal.signal(_signal.SIGINT, _signal_handler)
    try:
        _signal.signal(_signal.SIGTERM, _signal_handler)
    except (AttributeError, ValueError):
        # SIGTERM not available on Windows for non-console handlers; skip silently
        pass

    _shutdown_event.clear()

    from src.scheduler import build_scheduler
    from src.scheduler.jobs import run_monitor_cycle

    cm = ConfigManager()
    print(t("daemon_start", interval=interval_minutes))
    print(t("daemon_stop_hint"))
    logger.info("Starting scheduler-backed daemon (interval={}m)", interval_minutes)

    sched = build_scheduler(cm, interval_minutes=interval_minutes)

    try:
        # C2: start() inside try so a startup failure doesn't trigger shutdown
        # of a never-started scheduler (would raise SchedulerNotRunningError).
        sched.start()

        # Fire the first monitor cycle immediately rather than waiting a full interval
        run_monitor_cycle(cm)

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

def run_daemon_with_gui(interval_minutes: int, port: int):
    """Headless monitoring loop running in background thread + Flask GUI in main thread."""
    cm = ConfigManager()
    logger.info(f"Starting daemon loop with Web GUI (interval={interval_minutes}m, port={port})")
    
    # Start daemon in background thread
    t_daemon = threading.Thread(target=run_daemon_loop, args=(interval_minutes,), daemon=True)
    t_daemon.start()

    # Start Flask blocking in main thread
    from src.gui import launch_gui, HAS_FLASK
    if not HAS_FLASK:
        print(t("report_requires_flask"))
        print(t("cli_pip_install_hint", pkg="flask"))
        sys.exit(1)
        
    launch_gui(cm, port=port, persistent_mode=True)

def view_logs(log_file):
    """Simple log viewer for the CLI."""
    os.system("cls" if os.name == "nt" else "clear")
    draw_panel(t("menu_view_logs_title"), [])
    print("")
    try:
        if not os.path.exists(log_file):
            print(t("log_not_found", path=log_file))
        else:
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
                # Print last 20 lines
                for line in lines[-20:]:
                    print(line.strip())
    except Exception as e:
        print(t("log_read_error", error=str(e)))
    input(
        f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('press_enter_to_continue')} {Colors.GREEN}❯{Colors.ENDC} "
    )

# ─── Interactive CLI Menu ─────────────────────────────────────────────────────

def rule_management_menu(cm):
    while True:
        os.system("cls" if os.name == "nt" else "clear")
        cm.load()
        lines = [
            f"{Colors.BOLD}{Colors.CYAN}{t('main_menu_root_1')}{Colors.ENDC}",
            "-",
            t("main_menu_1"),
            t("main_menu_2"),
            t("main_menu_3"),
            t("main_menu_4"),
            t("main_menu_5"),
            t("main_menu_6"),
            t("main_menu_7"),
            t("main_menu_8"),
            t("main_menu_13"),
            t("main_menu_0")
        ]
        draw_panel("Illumio PCE Ops", lines)
        sel = safe_input(f"\n{t('please_select')}", int, range(0, 10))

        if sel is None or sel == 0:
            break
        elif sel == 1:
            add_event_menu(cm)
        elif sel == 2:
            add_traffic_menu(cm)
        elif sel == 3:
            add_bandwidth_volume_menu(cm)
        elif sel == 4:
            manage_rules_menu(cm)
        elif sel == 5:
            print(f"\n{Colors.WARNING}{t('warning_best_practices')}{Colors.ENDC}")
            confirm = safe_input(f"{t('confirm_continue')} (Y/N)", str)
            if confirm and confirm.strip().upper() == "Y":
                print(f"{Colors.BLUE}{t('loading_best_practices')}{Colors.ENDC}")
                cm.load_best_practices()
                input(
                    f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('best_practice_loaded', default='Best practices loaded successfully! Press Enter to continue...')} {Colors.GREEN}❯{Colors.ENDC} "
                )
            else:
                input(
                    f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('operation_cancelled', default='Operation cancelled. Press Enter to continue...')} {Colors.GREEN}❯{Colors.ENDC} "
                )
        elif sel == 6:
            Reporter(cm).send_alerts(force_test=True)
            input(
                f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('done_msg')} {Colors.GREEN}❯{Colors.ENDC} "
            )
        elif sel == 7:
            api = ApiClient(cm)
            rep = Reporter(cm)
            ana = Analyzer(cm, api, rep)
            ana.run_analysis()
            rep.send_alerts()
            input(
                f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('press_enter_to_continue')} {Colors.GREEN}❯{Colors.ENDC} "
            )
        elif sel == 8:
            api = ApiClient(cm)
            rep = Reporter(cm)
            ana = Analyzer(cm, api, rep)
            ana.run_debug_mode()
            input(
                f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('press_enter_to_continue')} {Colors.GREEN}❯{Colors.ENDC} "
            )
        elif sel == 9:
            add_system_health_menu(cm)

def report_generation_menu(cm):
    while True:
        os.system("cls" if os.name == "nt" else "clear")
        cm.load()
        lines = [
            f"{Colors.BOLD}{Colors.CYAN}{t('main_menu_root_2')}{Colors.ENDC}",
            "-",
            t("main_menu_9"),
            t("main_menu_10"),
            t("main_menu_11"),
            t("main_menu_pu"),
            t("main_menu_12"),
            t("main_menu_0")
        ]
        draw_panel("Illumio PCE Ops", lines)
        sel = safe_input(f"\n{t('please_select')}", int, range(0, 6))

        if sel is None or sel == 0:
            break
        elif sel == 1:
            _run_report_menu(cm)
        elif sel == 2:
            _run_audit_report_menu(cm)
        elif sel == 3:
            _run_ven_status_menu(cm)
        elif sel == 4:
            _run_policy_usage_menu(cm)
        elif sel == 5:
            manage_report_schedules_menu(cm)

def main_menu():
    # Setup Logging
    global LOG_FILE
    PKG_DIR = os.path.dirname(os.path.abspath(__file__))
    ROOT_DIR = os.path.dirname(PKG_DIR)
    LOG_DIR = os.path.join(ROOT_DIR, "logs")
    LOG_FILE = os.path.join(LOG_DIR, "illumio_ops.log")

    _pre_cm = ConfigManager()
    _log_cfg = _pre_cm.config.get("logging", {})
    setup_logger("src", LOG_FILE,
                 level=_log_cfg.get("level", "INFO"),
                 json_sink=_log_cfg.get("json_sink", False))
    logger.info("Starting Illumio PCE Ops")

    from src.module_log import ModuleLog as _ML_menu
    _ML_menu.init(LOG_DIR)

    cm = _pre_cm

    while True:
        os.system("cls" if os.name == "nt" else "clear")
        cm.load()

        settings = cm.config.get("settings", {})
        current_lang = (settings.get("language", "en") or "en").upper()
        current_theme = (settings.get("theme", "dark") or "dark").capitalize()
        shortcuts_line = t("cli_shortcuts_compact")

        import datetime as _dt
        from src.humanize_ext import human_time_ago
        _last_activity_label = t("gui_last_activity", default="Last activity")
        _last_activity_val = t("gui_no_log_activity", default="(no log activity)")
        if os.path.exists(LOG_FILE):
            try:
                _mtime = _dt.datetime.fromtimestamp(os.path.getmtime(LOG_FILE))
                _last_activity_val = human_time_ago(_mtime)
            except Exception:
                _last_activity_val = t("gui_no_log_activity", default="(no log activity)")

        lines = [
            f"API: {cm.config['api']['url']} | Rules: {len(cm.config['rules'])}",
            f"Language: {current_lang} | Theme: {current_theme} | {_last_activity_label}: {_last_activity_val}",
            f"{Colors.DARK_GRAY}{shortcuts_line}{Colors.ENDC}",
            "-",
            t("main_menu_root_1"),
            t("main_menu_root_2"),
            t("main_menu_root_3"),
            t("main_menu_root_4"),
            t("main_menu_root_5"),
            t("main_menu_root_6"),
            t("main_menu_0"),
        ]

        draw_panel("Illumio PCE Ops", lines)

        sel = safe_input(f"\n{t('please_select')}", int, range(0, 7))

        if sel is None or sel == 0:
            break
        elif sel == 1:
            rule_management_menu(cm)
        elif sel == 2:
            report_generation_menu(cm)
        elif sel == 3:
            from src.rule_scheduler_cli import rule_scheduler_menu
            rule_scheduler_menu(cm)
        elif sel == 4:
            settings_menu(cm)
        elif sel == 5:
            from src.gui import launch_gui, HAS_FLASK, FLASK_IMPORT_ERROR
            if not HAS_FLASK:
                print(f"{Colors.FAIL}{t('flask_not_available')}{Colors.ENDC}")
                if FLASK_IMPORT_ERROR:
                    print(f"Import error: {FLASK_IMPORT_ERROR}")
                print(t("flask_install_hint"))
                input(
                    f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('press_enter_to_continue')} {Colors.GREEN}❯{Colors.ENDC} "
                )
            else:
                port_str = safe_input(t("gui_port_prompt"), str)
                try:
                    port = int(port_str) if port_str and port_str.strip() else 5001
                except (ValueError, TypeError):
                    port = 5001
                launch_gui(cm, port=port)
        elif sel == 6:
            view_logs(LOG_FILE)

# ─── Report Sub-Menu ─────────────────────────────────────────────────────────

def _run_report_menu(cm):
    """Interactive sub-menu for Traffic Flow Report (item 12)."""
    import datetime as _dt
    try:
        import pandas  # noqa: F401
    except ImportError:
        print(f"{Colors.FAIL}{t('report_requires_pandas')}{Colors.ENDC}")
        input(f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('press_enter_to_continue')} ")
        return

    from src.report.report_generator import ReportGenerator
    from src.api_client import ApiClient
    from src.reporter import Reporter

    PKG_DIR = os.path.dirname(os.path.abspath(__file__))
    ROOT_DIR = os.path.dirname(PKG_DIR)
    config_dir = os.path.join(ROOT_DIR, 'config')
    output_dir = cm.config.get('report', {}).get('output_dir', 'reports')
    if not os.path.isabs(output_dir):
        output_dir = os.path.join(ROOT_DIR, output_dir)

    while True:
        draw_panel(
            f"{Colors.CYAN}{t('report_panel_title')}{Colors.ENDC}",
            [
                t("report_menu_1"),
                t("report_menu_2"),
                t("report_menu_3"),
                t("nav_back"),
            ]
        )
        sel = safe_input(f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('report_select_prompt')}", int, range(0, 4))

        if sel is None or sel == 0:
            break

        if sel in (1, 2):
            fmt = cm.config.get('report', {}).get('format', ['html'])
            if isinstance(fmt, list):
                fmt = fmt[0] if fmt else 'html'
            fmt_str = safe_input(t("report_format_prompt", fmt=fmt), str) or fmt
            if not fmt_str or fmt_str not in ('html', 'csv', 'all'):
                fmt_str = 'html'
            _send_raw = safe_input(t("report_email_prompt"), str)
            send_email = bool(_send_raw) and _send_raw.strip().lower() == 'y'

            # Date range for API source
            api_start_date = None
            api_end_date = None
            api_filters = None
            if sel == 1:
                now = _dt.datetime.now(_dt.timezone.utc)
                default_end = now.strftime('%Y-%m-%d')
                default_start = (now - _dt.timedelta(days=7)).strftime('%Y-%m-%d')
                print(f"\n{Colors.CYAN}{t('report_date_range_title')}{Colors.ENDC}")
                s = safe_input(f"  {t('report_start_date', date=default_start)}", str)
                if s is None:
                    continue
                s = s or default_start
                e = safe_input(f"  {t('report_end_date', date=default_end)}", str)
                if e is None:
                    continue
                e = e or default_end
                try:
                    api_start_date = _dt.datetime.strptime(s.strip(), '%Y-%m-%d').strftime('%Y-%m-%dT00:00:00Z')
                    api_end_date   = _dt.datetime.strptime(e.strip(), '%Y-%m-%d').strftime('%Y-%m-%dT23:59:59Z')
                except ValueError:
                    print(f"{Colors.FAIL}{t('report_invalid_date')}{Colors.ENDC}")
                    input(f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('press_enter_to_continue')} ")
                    continue

                # Optional traffic filters
                print(f"\n{Colors.CYAN}{t('rpt_filter_toggle')}{Colors.ENDC}")
                _apply_filters = safe_input(t("rpt_apply_filters"), str)
                if _apply_filters and _apply_filters.strip().lower() == 'y':
                    _src_raw = (safe_input(f"  {t('rpt_filter_src')}", str) or '').strip()
                    _dst_raw = (safe_input(f"  {t('rpt_filter_dst')}", str) or '').strip()
                    _port_raw = (safe_input(f"  {t('rpt_filter_port')}", str) or '').strip()
                    # Protocol: 0=All, 1=TCP(6), 2=UDP(17)
                    _proto_sel = safe_input(f"  {t('proto_select')}", int, range(0, 3))
                    _proto = {1: 6, 2: 17}.get(_proto_sel) if _proto_sel else None
                    # Policy Decision: 0=All, 1=Blocked, 2=PotentiallyBlocked, 3=Allowed
                    _pd_prompt = f"  {t('policy_decision')} (0=All, 1={t('rpt_pd_blocked')}, 2={t('rpt_pd_potential')}, 3={t('rpt_pd_allowed')})"
                    _pd_sel = safe_input(_pd_prompt, int, range(0, 4))
                    _pd_map = {1: ['blocked'], 2: ['potentially_blocked'], 3: ['allowed']}
                    _pd = _pd_map.get(_pd_sel) if _pd_sel else None
                    # Excludes
                    print(f"\n  {Colors.CYAN}{t('excludes_optional')}{Colors.ENDC}")
                    _ex_src_raw = (safe_input(f"  {t('rpt_filter_ex_src')}", str) or '').strip()
                    _ex_dst_raw = (safe_input(f"  {t('rpt_filter_ex_dst')}", str) or '').strip()
                    _ex_port_raw = (safe_input(f"  {t('rpt_filter_ex_port')}", str) or '').strip()

                    def _split_label_ip(val):
                        if val and '=' in val:
                            return [val], None
                        return [], val or None

                    src_labels, src_ip = _split_label_ip(_src_raw)
                    dst_labels, dst_ip = _split_label_ip(_dst_raw)
                    ex_src_labels, ex_src_ip = _split_label_ip(_ex_src_raw)
                    ex_dst_labels, ex_dst_ip = _split_label_ip(_ex_dst_raw)

                    api_filters = {
                        'src_labels': src_labels,
                        'dst_labels': dst_labels,
                        'src_ip': src_ip,
                        'dst_ip': dst_ip,
                        'port': _port_raw,
                        'proto': _proto,
                        'policy_decisions': _pd,
                        'ex_src_labels': ex_src_labels,
                        'ex_dst_labels': ex_dst_labels,
                        'ex_src_ip': ex_src_ip,
                        'ex_dst_ip': ex_dst_ip,
                        'ex_port': _ex_port_raw,
                    }
                    if not any(v for v in api_filters.values() if v):
                        api_filters = None

            try:
                api = ApiClient(cm)
                reporter = Reporter(cm)
                gen = ReportGenerator(cm, api_client=api, config_dir=config_dir)

                if sel == 1:
                    result = gen.generate_from_api(start_date=api_start_date, end_date=api_end_date, filters=api_filters)
                else:
                    _csv_raw = safe_input(t("csv_path_prompt"), str)
                    csv_path = _csv_raw.strip() if _csv_raw else ''
                    if not csv_path or not os.path.exists(csv_path):
                        print(f"{Colors.FAIL}{t('csv_not_found', path=csv_path)}{Colors.ENDC}")
                        continue
                    result = gen.generate_from_csv(csv_path)

                if result.record_count == 0:
                    print(f"{Colors.WARNING}{t('report_no_data')}{Colors.ENDC}")
                else:
                    paths = gen.export(result, fmt=fmt_str, output_dir=output_dir,
                                       send_email=send_email, reporter=reporter if send_email else None)
                    print(f"\n{Colors.GREEN}{t('report_files_saved')}{Colors.ENDC}")
                    for p in paths:
                        print(f"  {p}")

            except Exception as e:
                print(f"{Colors.FAIL}{t('report_gen_failed', error=str(e))}{Colors.ENDC}")
                logger.exception("Report generation error")

            input(f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('press_enter_to_continue')} ")

        elif sel == 3:
            report_cfg = cm.config.get('report', {})
            print(f"\n{t('report_current_config')}")
            for k, v in report_cfg.items():
                print(f"  {k}: {v}")
            print(f"\n{t('report_edit_hint')}")
            input(f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('press_enter_to_continue')} ")

# ─── Entry Point ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Illumio PCE Ops",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python illumio_ops.py                       # Interactive CLI menu\n"
            "  python illumio_ops.py --monitor             # Headless daemon mode\n"
            "  python illumio_ops.py --monitor -i 5        # Daemon with 5-min interval\n"
            "  python illumio_ops.py --gui                 # Launch Web GUI (port 5001)\n"
            "  python illumio_ops.py --gui --port 8080     # Web GUI on custom port\n"
        ),
    )
    parser.add_argument(
        "--monitor",
        action="store_true",
        help="Run in headless daemon mode (no interactive menu)",
    )
    parser.add_argument(
        "--monitor-gui",
        action="store_true",
        help="Run daemon + Web GUI (persistent mode, requires auth)",
    )
    parser.add_argument(
        "-i",
        "--interval",
        type=int,
        default=10,
        help="Monitoring interval in minutes (default: 10)",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Launch the Web GUI (requires: pip install flask)",
    )
    parser.add_argument(
        "-p", "--port", type=int, default=5001, help="Web GUI port (default: 5001)"
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Generate a Traffic Flow Report (requires: pip install pandas pyyaml)",
    )
    parser.add_argument(
        "--source",
        choices=["api", "csv"],
        default="api",
        help="Report data source: 'api' (default) or 'csv'",
    )
    parser.add_argument(
        "--file",
        type=str,
        default=None,
        help="CSV file path (used with --source csv)",
    )
    parser.add_argument(
        "--format",
        choices=["html", "csv", "pdf", "xlsx", "all"],
        default="html",
        help="Report output format: html (default), csv, pdf, xlsx, or all",
    )

    parser.add_argument(
        "--email",
        action="store_true",
        help="Send report by email after generation (uses SMTP config)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Output directory for report files (default: reports/)",
    )

    args = parser.parse_args()

    # Setup logging early for all modes
    PKG_DIR = os.path.dirname(os.path.abspath(__file__))
    ROOT_DIR = os.path.dirname(PKG_DIR)
    LOG_DIR = os.path.join(ROOT_DIR, "logs")
    LOG_FILE = os.path.join(LOG_DIR, "illumio_ops.log")
    _early_cm = ConfigManager()
    _log_cfg = _early_cm.config.get("logging", {})
    setup_logger("src", LOG_FILE,
                 level=_log_cfg.get("level", "INFO"),
                 json_sink=_log_cfg.get("json_sink", False))

    from src.module_log import ModuleLog
    _logs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'logs')
    ModuleLog.init(os.path.normpath(_logs_dir))

    if args.monitor_gui and not args.monitor:
        run_daemon_with_gui(args.interval, args.port)
        sys.exit(0)

    if args.report:
        try:
            import pandas  # noqa: F401
        except ImportError:
            print(t("report_requires_pandas"))
            print(t("cli_pip_install_hint", pkg="pandas pyyaml"))
            sys.exit(1)
        from src.report.report_generator import ReportGenerator
        from src.api_client import ApiClient
        from src.reporter import Reporter
        cm = ConfigManager()
        api = ApiClient(cm)
        reporter = Reporter(cm)
        PKG_DIR = os.path.dirname(os.path.abspath(__file__))
        ROOT_DIR = os.path.dirname(PKG_DIR)
        config_dir = os.path.join(ROOT_DIR, 'config')
        output_dir = args.output_dir or cm.config.get('report', {}).get('output_dir', 'reports')
        if not os.path.isabs(output_dir):
            output_dir = os.path.join(ROOT_DIR, output_dir)
        gen = ReportGenerator(cm, api_client=api, config_dir=config_dir)
        if args.source == 'csv':
            if not args.file:
                print(t("cli_source_csv_requires_file"))
                sys.exit(1)
            result = gen.generate_from_csv(args.file)
        else:
            result = gen.generate_from_api()
        if result.record_count == 0:
            print(t("no_data_report"))
            sys.exit(1)
        paths = gen.export(result, fmt=args.format, output_dir=output_dir,
                           send_email=args.email, reporter=reporter if args.email else None)
        print(t("cli_generated"))
        for p in paths:
            print(f"  {p}")
        sys.exit(0)
    elif args.monitor:
        run_daemon_loop(args.interval)
    elif args.gui:
        from src.gui import launch_gui, HAS_FLASK, FLASK_IMPORT_ERROR

        if not HAS_FLASK:
            print(t("report_requires_flask"))
            if FLASK_IMPORT_ERROR:
                print(f"Import error: {FLASK_IMPORT_ERROR}")
            print(t("cli_pip_install_hint", pkg="flask"))
            sys.exit(1)
        cm = ConfigManager()
        launch_gui(cm, port=args.port)
    else:
        try:
            main_menu()
        except KeyboardInterrupt:
            print(f"\n{t('bye_msg')}")

def _run_audit_report_menu(cm):
    """Interactive sub-menu for Audit & System Events Report (item 13)."""
    import datetime as _dt
    try:
        import pandas  # noqa: F401
    except ImportError:
        print(f"{Colors.FAIL}{t('report_requires_pandas')}{Colors.ENDC}")
        input(f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('press_enter_to_continue')} ")
        return

    from src.report.audit_generator import AuditGenerator
    from src.api_client import ApiClient

    PKG_DIR = os.path.dirname(os.path.abspath(__file__))
    ROOT_DIR = os.path.dirname(PKG_DIR)
    config_dir = os.path.join(ROOT_DIR, 'config')
    output_dir = cm.config.get('report', {}).get('output_dir', 'reports')
    if not os.path.isabs(output_dir):
        output_dir = os.path.join(ROOT_DIR, output_dir)

    # --- Date range input ---
    now = _dt.datetime.now(_dt.timezone.utc)
    default_end = now.strftime('%Y-%m-%d')
    default_start = (now - _dt.timedelta(days=7)).strftime('%Y-%m-%d')
    print(f"\n{Colors.CYAN}{t('audit_date_range_title')}{Colors.ENDC}")
    start_str = safe_input(f"  {t('report_start_date', date=default_start)}", str)
    if start_str is None:
        return
    start_str = start_str or default_start
    end_str = safe_input(f"  {t('report_end_date', date=default_end)}", str)
    if end_str is None:
        return
    end_str = end_str or default_end
    try:
        start_date = _dt.datetime.strptime(start_str.strip(), '%Y-%m-%d').strftime('%Y-%m-%dT00:00:00Z')
        end_date   = _dt.datetime.strptime(end_str.strip(),   '%Y-%m-%d').strftime('%Y-%m-%dT23:59:59Z')
    except ValueError:
        print(f"{Colors.FAIL}{t('report_invalid_date')}{Colors.ENDC}")
        input(f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('press_enter_to_continue')} ")
        return

    fmt_str = safe_input(t("report_format_prompt", fmt="html"), str) or 'html'
    if fmt_str not in ('html', 'csv', 'all'):
        fmt_str = 'html'

    print(f"\n{Colors.CYAN}{t('audit_generating')}{Colors.ENDC}")
    try:
        api = ApiClient(cm)
        gen = AuditGenerator(cm, api_client=api, config_dir=config_dir)

        result = gen.generate_from_api(start_date=start_date, end_date=end_date)
        if result.record_count > 0:
            print(t("audit_analysis_done", path=output_dir))
            paths = gen.export(result, fmt=fmt_str, output_dir=output_dir)
            if paths:
                print(f"\n{Colors.GREEN}{t('report_saved')}{Colors.ENDC}")
                for p in paths:
                    print(f"  {p}")
            else:
                print(f"{Colors.FAIL}{t('export_failed')}{Colors.ENDC}")
        else:
            print(t("audit_no_data"))
    except Exception as e:
        print(f"{Colors.FAIL}{t('error_generic', error=str(e))}{Colors.ENDC}")

    input(f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('press_enter_to_continue')} ")

def _run_ven_status_menu(cm):
    """Interactive sub-menu for VEN Status Inventory Report (item 14)."""
    try:
        import pandas  # noqa: F401
    except ImportError:
        print(f"{Colors.FAIL}{t('report_requires_pandas')}{Colors.ENDC}")
        input(f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('press_enter_to_continue')} ")
        return

    from src.report.ven_status_generator import VenStatusGenerator
    from src.api_client import ApiClient

    PKG_DIR = os.path.dirname(os.path.abspath(__file__))
    ROOT_DIR = os.path.dirname(PKG_DIR)
    output_dir = cm.config.get('report', {}).get('output_dir', 'reports')
    if not os.path.isabs(output_dir):
        output_dir = os.path.join(ROOT_DIR, output_dir)

    print(f"\n{Colors.CYAN}{t('ven_generating')}{Colors.ENDC}")
    try:
        api = ApiClient(cm)
        gen = VenStatusGenerator(cm, api_client=api)
        result = gen.generate()
        if result.record_count > 0:
            kpis = result.module_results.get('kpis', [])
            for kpi in kpis:
                print(f"  {kpi['label']}: {Colors.GREEN}{kpi['value']}{Colors.ENDC}")
            print(f"\n{t('ven_saving', path=output_dir)}")
            paths = gen.export(result, output_dir=output_dir)
            if paths:
                print(f"\n{Colors.GREEN}{t('report_saved')}{Colors.ENDC}")
                for p in paths:
                    print(f"  {p}")
            else:
                print(f"{Colors.FAIL}{t('export_failed')}{Colors.ENDC}")
        else:
            print(t("ven_no_workloads"))
    except Exception as e:
        print(f"{Colors.FAIL}{t('error_generic', error=str(e))}{Colors.ENDC}")
        logger.exception("VEN status report error")

    input(f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('press_enter_to_continue')} ")

def _run_policy_usage_menu(cm):
    """Interactive sub-menu for Policy Usage Report."""
    import datetime as _dt
    try:
        import pandas  # noqa: F401
    except ImportError:
        print(f"{Colors.FAIL}{t('report_requires_pandas')}{Colors.ENDC}")
        input(f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('press_enter_to_continue')} ")
        return

    from src.report.policy_usage_generator import PolicyUsageGenerator
    from src.api_client import ApiClient

    PKG_DIR = os.path.dirname(os.path.abspath(__file__))
    ROOT_DIR = os.path.dirname(PKG_DIR)
    config_dir = os.path.join(ROOT_DIR, 'config')
    output_dir = cm.config.get('report', {}).get('output_dir', 'reports')
    if not os.path.isabs(output_dir):
        output_dir = os.path.join(ROOT_DIR, output_dir)

    # --- Data source selection ---
    print(f"\n{Colors.CYAN}{t('gui_gen_pu_title')}{Colors.ENDC}")
    print(t("pu_cli_source_prompt"))
    source_sel = safe_input(f"\n{t('please_select')}", int, range(1, 3))
    if source_sel is None:
        return

    if source_sel == 1:
        # API mode: per-rule traffic query
        now = _dt.datetime.now(_dt.timezone.utc)
        default_end = now.strftime('%Y-%m-%d')
        default_start = (now - _dt.timedelta(days=30)).strftime('%Y-%m-%d')
        start_str = safe_input(f"  {t('report_start_date', date=default_start)}", str)
        if start_str is None:
            return
        start_str = start_str or default_start
        end_str = safe_input(f"  {t('report_end_date', date=default_end)}", str)
        if end_str is None:
            return
        end_str = end_str or default_end
        try:
            start_date = _dt.datetime.strptime(start_str.strip(), '%Y-%m-%d').strftime('%Y-%m-%dT00:00:00Z')
            end_date   = _dt.datetime.strptime(end_str.strip(),   '%Y-%m-%d').strftime('%Y-%m-%dT23:59:59Z')
        except ValueError:
            print(f"{Colors.FAIL}{t('report_invalid_date')}{Colors.ENDC}")
            input(f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('press_enter_to_continue')} ")
            return

        fmt_str = safe_input(t("report_format_prompt", fmt="html"), str) or 'html'
        if fmt_str not in ('html', 'csv', 'all'):
            fmt_str = 'html'

        print(f"\n{Colors.CYAN}{t('rpt_pu_fetching_rulesets')}{Colors.ENDC}")
        try:
            api = ApiClient(cm)
            gen = PolicyUsageGenerator(cm, api_client=api, config_dir=config_dir)
            result = gen.generate_from_api(start_date=start_date, end_date=end_date)
            if result.record_count > 0:
                paths = gen.export(result, fmt=fmt_str, output_dir=output_dir)
                if paths:
                    print(f"\n{Colors.GREEN}{t('report_saved')}{Colors.ENDC}")
                    for p in paths:
                        print(f"  {p}")
                else:
                    print(f"{Colors.FAIL}{t('export_failed')}{Colors.ENDC}")
            else:
                print(t("gui_no_pu_data"))
        except Exception as e:
            print(f"{Colors.FAIL}{t('error_generic', error=str(e))}{Colors.ENDC}")
            logger.exception("Policy usage report error")

    elif source_sel == 2:
        # CSV mode: import workloader output
        csv_path = safe_input(f"  {t('pu_cli_csv_path')}", str)
        if not csv_path:
            return
        csv_path = csv_path.strip().strip('"').strip("'")
        if not os.path.isfile(csv_path):
            print(f"{Colors.FAIL}{t('pu_cli_csv_not_found', path=csv_path)}{Colors.ENDC}")
            input(f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('press_enter_to_continue')} ")
            return

        fmt_str = safe_input(t("report_format_prompt", fmt="html"), str) or 'html'
        if fmt_str not in ('html', 'csv', 'all'):
            fmt_str = 'html'

        try:
            gen = PolicyUsageGenerator(cm, config_dir=config_dir)
            result = gen.generate_from_csv(csv_path)
            if result.record_count > 0:
                paths = gen.export(result, fmt=fmt_str, output_dir=output_dir)
                if paths:
                    print(f"\n{Colors.GREEN}{t('report_saved')}{Colors.ENDC}")
                    for p in paths:
                        print(f"  {p}")
                else:
                    print(f"{Colors.FAIL}{t('export_failed')}{Colors.ENDC}")
            else:
                print(t("gui_no_pu_data"))
        except Exception as e:
            print(f"{Colors.FAIL}{t('error_generic', error=str(e))}{Colors.ENDC}")
            logger.exception("Policy usage CSV import error")

    input(f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('press_enter_to_continue')} ")

if __name__ == "__main__":
    main()
