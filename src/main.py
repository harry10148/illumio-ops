import sys
import os
import signal
import logging
import argparse
from src.utils import setup_logger, Colors, safe_input, draw_panel, get_terminal_width, Spinner
from src.config import ConfigManager
from src.api_client import ApiClient
from src.analyzer import Analyzer
from src.reporter import Reporter
from src.settings import (
    settings_menu,
    add_event_menu,
    add_traffic_menu,
    add_bandwidth_volume_menu,
    manage_rules_menu,
    manage_report_schedules_menu,
)
from src.i18n import t, get_language

logger = logging.getLogger(__name__)
LOG_FILE = ""  # To be set in main() or main_menu()

# ─── Daemon / Monitor Loop ───────────────────────────────────────────────────

import threading

_shutdown_event = threading.Event()


def _signal_handler(signum, _frame):
    logger.info(f"Received signal {signum}. Shutting down gracefully...")
    _shutdown_event.set()


def run_daemon_loop(interval_minutes: int):
    """Headless monitoring loop. Runs analysis at fixed intervals until stopped.
    Also ticks the report scheduler every 60 seconds to check due schedules."""
    _shutdown_event.clear()

    cm = ConfigManager()
    logger.info(f"Starting daemon loop (interval={interval_minutes}m)")
    print(t("daemon_start", interval=interval_minutes))
    print(t("daemon_stop_hint"))

    from src.report_scheduler import ReportScheduler

    last_analysis_time = None
    last_rule_check_time = None
    interval_seconds = interval_minutes * 60

    while not _shutdown_event.is_set():
        try:
            import datetime as _dt
            now = _dt.datetime.now(_dt.timezone.utc)

            # Run monitoring analysis at the configured interval
            if last_analysis_time is None or (now - last_analysis_time).total_seconds() >= interval_seconds:
                logger.info("=== Starting monitoring cycle ===")
                api = ApiClient(cm)
                rep = Reporter(cm)
                ana = Analyzer(cm, api, rep)
                ana.run_analysis()
                rep.send_alerts()
                last_analysis_time = now
                logger.info("=== Monitoring cycle completed ===")

            # Tick the report scheduler every loop iteration (60-second base)
            rep = Reporter(cm)
            scheduler = ReportScheduler(cm, rep)
            scheduler.tick()

            # Rule Scheduler check (at configured interval)
            if cm.config.get("rule_scheduler", {}).get("enabled", False):
                rule_check_interval = cm.config.get("rule_scheduler", {}).get("check_interval_seconds", 300)
                if last_rule_check_time is None or (now - last_rule_check_time).total_seconds() >= rule_check_interval:
                    from src.rule_scheduler import ScheduleDB, ScheduleEngine
                    import os as _os
                    _pkg_dir = _os.path.dirname(_os.path.abspath(__file__))
                    _root_dir = _os.path.dirname(_pkg_dir)
                    _db_path = _os.path.join(_root_dir, "config", "rule_schedules.json")
                    rs_db = ScheduleDB(_db_path)
                    rs_db.load()
                    rs_api = ApiClient(cm)
                    rs_engine = ScheduleEngine(rs_db, rs_api)
                    rs_engine.check(silent=True)
                    last_rule_check_time = now
                    logger.info("Rule scheduler check completed.")

        except Exception as e:
            logger.error(f"Error in monitoring cycle: {e}", exc_info=True)

        # Always sleep 60 seconds between ticks (scheduler needs minute-level resolution)
        _shutdown_event.wait(timeout=60)

    logger.info("Daemon loop stopped.")
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
            t("main_menu_0")
        ]
        draw_panel("Illumio PCE Ops", lines)
        sel = safe_input(f"\n{t('please_select')}", int, range(0, 9))

        if sel is None or sel == 0:
            break
        elif sel == 1:
            add_event_menu(cm)
        elif sel == 2:
            from src.settings import add_traffic_menu
            # We'll update add_traffic_menu to have its own start screen in settings.py later.
            add_traffic_menu(cm)
        elif sel == 3:
            from src.settings import add_bandwidth_volume_menu
            # We'll update add_bandwidth_volume_menu to have its own start screen in settings.py later.
            add_bandwidth_volume_menu(cm)
        elif sel == 4:
            manage_rules_menu(cm)
        elif sel == 5:
            print(f"\n{Colors.WARNING}{t('warning_best_practices')}{Colors.ENDC}")
            confirm = safe_input(f"{t('confirm_continue')} (Y/N)", str)
            if confirm and confirm.strip().upper() == "Y":
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
            t("main_menu_12"),
            t("main_menu_0")
        ]
        draw_panel("Illumio PCE Ops", lines)
        sel = safe_input(f"\n{t('please_select')}", int, range(0, 5))

        if sel is None or sel == 0:
            break
        elif sel == 1:
            _run_report_menu(cm)
        elif sel == 2:
            _run_audit_report_menu(cm)
        elif sel == 3:
            _run_ven_status_menu(cm)
        elif sel == 4:
            manage_report_schedules_menu(cm)

def main_menu():
    # Setup Logging
    global LOG_FILE
    PKG_DIR = os.path.dirname(os.path.abspath(__file__))
    ROOT_DIR = os.path.dirname(PKG_DIR)
    LOG_DIR = os.path.join(ROOT_DIR, "logs")
    LOG_FILE = os.path.join(LOG_DIR, "illumio_ops.log")

    setup_logger("src", LOG_FILE)
    logger.info("Starting Illumio PCE Ops")

    cm = ConfigManager()

    while True:
        os.system("cls" if os.name == "nt" else "clear")
        cm.load()

        settings = cm.config.get("settings", {})
        health_status = "ON" if settings.get("enable_health_check", True) else "OFF"
        current_lang = (settings.get("language", "en") or "en").upper()
        current_theme = (settings.get("theme", "dark") or "dark").capitalize()
        shortcuts_line = t("cli_shortcuts_compact")

        lines = [
            f"API: {cm.config['api']['url']} | Rules: {len(cm.config['rules'])}",
            f"Health Check: {health_status} | Language: {current_lang} | Theme: {current_theme}",
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
            from src.gui import launch_gui, HAS_FLASK
            if not HAS_FLASK:
                print(f"{Colors.FAIL}{t('flask_not_available')}{Colors.ENDC}")
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

        if sel == 0:
            break

        if sel in (1, 2):
            fmt = cm.config.get('report', {}).get('format', ['html'])
            if isinstance(fmt, list):
                fmt = fmt[0] if fmt else 'html'
            fmt_str = safe_input(t("report_format_prompt", fmt=fmt), str) or fmt
            if fmt_str not in ('html', 'csv', 'all'):
                fmt_str = 'html'
            send_email = safe_input(t("report_email_prompt"), str).strip().lower() == 'y'

            # Date range for API source
            api_start_date = None
            api_end_date = None
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

            try:
                api = ApiClient(cm)
                reporter = Reporter(cm)
                gen = ReportGenerator(cm, api_client=api, config_dir=config_dir)

                if sel == 1:
                    result = gen.generate_from_api(start_date=api_start_date, end_date=api_end_date)
                else:
                    csv_path = safe_input(t("csv_path_prompt"), str).strip()
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
        choices=["html", "csv", "all"],
        default="html",
        help="Report output format: html (default), csv (raw data ZIP), or all",
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
    setup_logger("src", LOG_FILE)

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
        from src.gui import launch_gui, HAS_FLASK

        if not HAS_FLASK:
            print(t("report_requires_flask"))
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


if __name__ == "__main__":
    main()
