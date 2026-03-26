import sys
import os
import signal
import logging
import argparse
from src.utils import setup_logger, Colors, safe_input, draw_panel
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

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    cm = ConfigManager()
    logger.info(f"Starting daemon loop (interval={interval_minutes}m)")
    print(f"Illumio PCE Monitor — daemon mode (interval={interval_minutes}m)")
    print("Press Ctrl+C or send SIGTERM to stop.")

    from src.report_scheduler import ReportScheduler

    last_analysis_time = None
    interval_seconds = interval_minutes * 60

    while not _shutdown_event.is_set():
        try:
            import datetime as _dt
            now = _dt.datetime.utcnow()

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

        except Exception as e:
            logger.error(f"Error in monitoring cycle: {e}", exc_info=True)

        # Always sleep 60 seconds between ticks (scheduler needs minute-level resolution)
        _shutdown_event.wait(timeout=60)

    logger.info("Daemon loop stopped.")
    print("\nDaemon stopped.")


def view_logs(log_file):
    """Simple log viewer for the CLI."""
    os.system("cls" if os.name == "nt" else "clear")
    draw_panel(t("menu_view_logs_title"), [], width=80)
    print("")
    try:
        if not os.path.exists(log_file):
            print(f"Log file not found: {log_file}")
        else:
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
                # Print last 20 lines
                for line in lines[-20:]:
                    print(line.strip())
    except Exception as e:
        print(f"Error reading logs: {e}")
    input(
        f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('press_enter_to_continue')} {Colors.GREEN}❯{Colors.ENDC} "
    )


# ─── Interactive CLI Menu ─────────────────────────────────────────────────────


def main_menu():
    # Setup Logging
    global LOG_FILE
    PKG_DIR = os.path.dirname(os.path.abspath(__file__))
    ROOT_DIR = os.path.dirname(PKG_DIR)
    LOG_DIR = os.path.join(ROOT_DIR, "logs")
    LOG_FILE = os.path.join(LOG_DIR, "illumio_monitor.log")

    setup_logger("src", LOG_FILE)
    logger.info("Starting Illumio PCE Monitor")

    cm = ConfigManager()

    while True:
        os.system("cls" if os.name == "nt" else "clear")
        cm.load()

        settings = cm.config.get("settings", {})
        health_status = "ON" if settings.get("enable_health_check", True) else "OFF"
        current_lang = (settings.get("language", "en") or "en").upper()
        current_theme = (settings.get("theme", "dark") or "dark").capitalize()
        shortcuts_line = (
            "快捷: Enter預設 | 0返回 | -1取消 | h/?說明"
            if get_language() == "zh_TW"
            else t(
                "cli_shortcuts_compact",
                default="Shortcuts: Enter=default | 0=back | -1=cancel | h/?=help",
            )
        )

        lines = [
            f"API: {cm.config['api']['url']} | Rules: {len(cm.config['rules'])}",
            f"Health Check: {health_status} | Language: {current_lang} | Theme: {current_theme}",
            f"{Colors.DARK_GRAY}{shortcuts_line}{Colors.ENDC}",
            "-",
            t("main_menu_1"),
            t("main_menu_2")
            .replace("{Colors.WARNING}", Colors.WARNING)
            .replace("{Colors.ENDC}", Colors.ENDC),
            t("main_menu_3")
            .replace("{Colors.CYAN}", Colors.CYAN)
            .replace("{Colors.ENDC}", Colors.ENDC),
            t("main_menu_4"),
            t("main_menu_5"),
            t("main_menu_6")
            .replace("{Colors.CYAN}", Colors.CYAN)
            .replace("{Colors.ENDC}", Colors.ENDC),
            t("main_menu_7"),
            t("main_menu_8"),
            t("main_menu_9"),
            t("main_menu_10")
            .replace("{Colors.CYAN}", Colors.CYAN)
            .replace("{Colors.ENDC}", Colors.ENDC),
            t("main_menu_11"),
            t("main_menu_12"),
            t("main_menu_13"),
            t("main_menu_14"),
            t("main_menu_15"),
            t("main_menu_0"),
        ]

        draw_panel("Illumio PCE Monitor", lines, width=65)

        sel = safe_input(f"\n{t('please_select')}", int, range(0, 16))

        if sel == 0:
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
            settings_menu(cm)
        elif sel == 6:
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
        elif sel == 7:
            Reporter(cm).send_alerts(force_test=True)
            input(
                f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('done_msg')} {Colors.GREEN}❯{Colors.ENDC} "
            )
        elif sel == 8:
            api = ApiClient(cm)
            rep = Reporter(cm)
            ana = Analyzer(cm, api, rep)
            ana.run_analysis()
            rep.send_alerts()
            input(
                f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('press_enter_to_continue')} {Colors.GREEN}❯{Colors.ENDC} "
            )
        elif sel == 9:
            api = ApiClient(cm)
            rep = Reporter(cm)
            ana = Analyzer(cm, api, rep)
            ana.run_debug_mode()
            input(
                f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('press_enter_to_continue')} {Colors.GREEN}❯{Colors.ENDC} "
            )
        elif sel == 10:
            # Launch Web GUI from console menu
            from src.gui import launch_gui, HAS_FLASK

            if not HAS_FLASK:
                print(
                    f"{Colors.FAIL}Web GUI not available: Flask is not installed.{Colors.ENDC}"
                )
                print(f"  Install it with: pip install flask")
                input(
                    f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('press_enter_to_continue')} {Colors.GREEN}❯{Colors.ENDC} "
                )
            else:
                port_str = safe_input("Web GUI Port (default 5001): ", str)
                try:
                    port = int(port_str) if port_str and port_str.strip() else 5001
                except (ValueError, TypeError):
                    port = 5001
                launch_gui(cm, port=port)
        elif sel == 11:
            view_logs(LOG_FILE)
        elif sel == 12:
            _run_report_menu(cm)
        elif sel == 13:
            _run_audit_report_menu(cm)
        elif sel == 14:
            _run_ven_status_menu(cm)
        elif sel == 15:
            manage_report_schedules_menu(cm)


# ─── Report Sub-Menu ─────────────────────────────────────────────────────────


def _run_report_menu(cm):
    """Interactive sub-menu for Traffic Flow Report (item 12)."""
    import datetime as _dt
    try:
        import pandas  # noqa: F401
    except ImportError:
        print(f"{Colors.FAIL}Report feature requires: pip install pandas openpyxl pyyaml{Colors.ENDC}")
        input(f"\n{Colors.CYAN}[?]{Colors.ENDC} Press Enter to continue ")
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
            f"{Colors.CYAN}[Report] Traffic Report Generator{Colors.ENDC}",
            [
                "1. Generate from API (fetch from PCE)",
                "2. Generate from CSV file",
                "3. Report Settings",
                "0. Back",
            ]
        )
        sel = safe_input(f"\n{Colors.CYAN}[?]{Colors.ENDC} Select [0-3]: ", int, range(0, 4))

        if sel == 0:
            break

        if sel in (1, 2):
            fmt = cm.config.get('report', {}).get('format', ['excel'])
            if isinstance(fmt, list):
                fmt = fmt[0] if fmt else 'excel'
            fmt_str = safe_input(f"Output format [excel/html/all] (default: {fmt}): ", str) or fmt
            if fmt_str not in ('excel', 'html', 'all'):
                fmt_str = 'excel'
            send_email = safe_input("Send report by email? [y/N]: ", str).strip().lower() == 'y'

            # Date range for API source
            api_start_date = None
            api_end_date = None
            if sel == 1:
                now = _dt.datetime.utcnow()
                default_end = now.strftime('%Y-%m-%d')
                default_start = (now - _dt.timedelta(days=7)).strftime('%Y-%m-%d')
                print(f"\n{Colors.CYAN}[Report] Date Range (YYYY-MM-DD, UTC){Colors.ENDC}")
                s = safe_input(f"  Start date (default: {default_start}): ", str) or default_start
                e = safe_input(f"  End date   (default: {default_end}): ", str) or default_end
                try:
                    api_start_date = _dt.datetime.strptime(s.strip(), '%Y-%m-%d').strftime('%Y-%m-%dT00:00:00Z')
                    api_end_date   = _dt.datetime.strptime(e.strip(), '%Y-%m-%d').strftime('%Y-%m-%dT23:59:59Z')
                except ValueError:
                    print(f"{Colors.FAIL}Invalid date format. Please use YYYY-MM-DD.{Colors.ENDC}")
                    input(f"\n{Colors.CYAN}[?]{Colors.ENDC} Press Enter to continue ")
                    continue

            try:
                api = ApiClient(cm)
                reporter = Reporter(cm)
                gen = ReportGenerator(cm, api_client=api, config_dir=config_dir)

                if sel == 1:
                    result = gen.generate_from_api(start_date=api_start_date, end_date=api_end_date)
                else:
                    csv_path = safe_input("CSV file path: ", str).strip()
                    if not csv_path or not os.path.exists(csv_path):
                        print(f"{Colors.FAIL}File not found: {csv_path}{Colors.ENDC}")
                        continue
                    result = gen.generate_from_csv(csv_path)

                if result.record_count == 0:
                    print(f"{Colors.WARNING}No data returned — cannot generate report.{Colors.ENDC}")
                else:
                    paths = gen.export(result, fmt=fmt_str, output_dir=output_dir,
                                       send_email=send_email, reporter=reporter if send_email else None)
                    print(f"\n{Colors.GREEN}Report files saved:{Colors.ENDC}")
                    for p in paths:
                        print(f"  {p}")

            except Exception as e:
                print(f"{Colors.FAIL}Report generation failed: {e}{Colors.ENDC}")
                logger.exception("Report generation error")

            input(f"\n{Colors.CYAN}[?]{Colors.ENDC} Press Enter to continue ")

        elif sel == 3:
            report_cfg = cm.config.get('report', {})
            print(f"\nCurrent report config:")
            for k, v in report_cfg.items():
                print(f"  {k}: {v}")
            print(f"\nEdit report settings in config/config.json under the 'report' key.")
            input(f"\n{Colors.CYAN}[?]{Colors.ENDC} Press Enter to continue ")


# ─── Entry Point ──────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Illumio PCE Monitor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python illumio_monitor.py                       # Interactive CLI menu\n"
            "  python illumio_monitor.py --monitor             # Headless daemon mode\n"
            "  python illumio_monitor.py --monitor -i 5        # Daemon with 5-min interval\n"
            "  python illumio_monitor.py --gui                 # Launch Web GUI (port 5001)\n"
            "  python illumio_monitor.py --gui --port 8080     # Web GUI on custom port\n"
        ),
    )
    parser.add_argument(
        "--monitor",
        action="store_true",
        help="Run in headless daemon mode (no interactive menu)",
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
        help="Generate a Traffic Flow Report (requires: pip install pandas openpyxl pyyaml)",
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
        choices=["excel", "html", "all"],
        default="excel",
        help="Report output format: excel (default), html, or all",
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
    LOG_FILE = os.path.join(LOG_DIR, "illumio_monitor.log")
    setup_logger("src", LOG_FILE)

    if args.report:
        try:
            import pandas  # noqa: F401
        except ImportError:
            print("Report feature requires additional packages. Install with:")
            print("  pip install pandas openpyxl pyyaml")
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
                print("--source csv requires --file <path>")
                sys.exit(1)
            result = gen.generate_from_csv(args.file)
        else:
            result = gen.generate_from_api()
        if result.record_count == 0:
            print("No data returned — report not generated.")
            sys.exit(1)
        paths = gen.export(result, fmt=args.format, output_dir=output_dir,
                           send_email=args.email, reporter=reporter if args.email else None)
        print("Generated:")
        for p in paths:
            print(f"  {p}")
        sys.exit(0)
    elif args.monitor:
        run_daemon_loop(args.interval)
    elif args.gui:
        from src.gui import launch_gui, HAS_FLASK

        if not HAS_FLASK:
            print("Web GUI requires Flask. Install it with:")
            print("  pip install flask")
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
        print(f"{Colors.FAIL}Report feature requires: pip install pandas openpyxl pyyaml{Colors.ENDC}")
        input(f"\n{Colors.CYAN}[?]{Colors.ENDC} Press Enter to continue ")
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
    now = _dt.datetime.utcnow()
    default_end = now.strftime('%Y-%m-%d')
    default_start = (now - _dt.timedelta(days=7)).strftime('%Y-%m-%d')
    print(f"\n{Colors.CYAN}[Audit] Date Range (YYYY-MM-DD, UTC){Colors.ENDC}")
    start_str = safe_input(f"  Start date (default: {default_start}): ", str) or default_start
    end_str   = safe_input(f"  End date   (default: {default_end}): ", str) or default_end
    try:
        start_date = _dt.datetime.strptime(start_str.strip(), '%Y-%m-%d').strftime('%Y-%m-%dT00:00:00Z')
        end_date   = _dt.datetime.strptime(end_str.strip(),   '%Y-%m-%d').strftime('%Y-%m-%dT23:59:59Z')
    except ValueError:
        print(f"{Colors.FAIL}Invalid date format. Please use YYYY-MM-DD.{Colors.ENDC}")
        input(f"\n{Colors.CYAN}[?]{Colors.ENDC} Press Enter to continue ")
        return

    fmt_str = safe_input("Output format [excel/html/all] (default: all): ", str) or 'all'
    if fmt_str not in ('excel', 'html', 'all'):
        fmt_str = 'all'

    print(f"\n{Colors.CYAN}[Audit] Generating System Health & Event Report...{Colors.ENDC}")
    try:
        api = ApiClient(cm)
        gen = AuditGenerator(cm, api_client=api, config_dir=config_dir)

        result = gen.generate_from_api(start_date=start_date, end_date=end_date)
        if result.record_count > 0:
            print(f"[Audit] Analysis finished. Saving to {output_dir}...")
            paths = gen.export(result, fmt=fmt_str, output_dir=output_dir)
            if paths:
                print(f"\n{Colors.GREEN}Report saved:{Colors.ENDC}")
                for p in paths:
                    print(f"  {p}")
            else:
                print(f"{Colors.FAIL}Export failed. Please check permissions.{Colors.ENDC}")
        else:
            print("[Audit] No data to export.")
    except Exception as e:
        print(f"{Colors.FAIL}Error: {e}{Colors.ENDC}")

    input(f"\n{Colors.CYAN}[?]{Colors.ENDC} Press Enter to continue ")


def _run_ven_status_menu(cm):
    """Interactive sub-menu for VEN Status Inventory Report (item 14)."""
    try:
        import pandas  # noqa: F401
    except ImportError:
        print(f"{Colors.FAIL}Report feature requires: pip install pandas openpyxl{Colors.ENDC}")
        input(f"\n{Colors.CYAN}[?]{Colors.ENDC} Press Enter to continue ")
        return

    from src.report.ven_status_generator import VenStatusGenerator
    from src.api_client import ApiClient

    PKG_DIR = os.path.dirname(os.path.abspath(__file__))
    ROOT_DIR = os.path.dirname(PKG_DIR)
    output_dir = cm.config.get('report', {}).get('output_dir', 'reports')
    if not os.path.isabs(output_dir):
        output_dir = os.path.join(ROOT_DIR, output_dir)

    print(f"\n{Colors.CYAN}[VEN Report] Generating VEN Status Inventory Report...{Colors.ENDC}")
    try:
        api = ApiClient(cm)
        gen = VenStatusGenerator(cm, api_client=api)
        result = gen.generate()
        if result.record_count > 0:
            kpis = result.module_results.get('kpis', [])
            for kpi in kpis:
                print(f"  {kpi['label']}: {Colors.GREEN}{kpi['value']}{Colors.ENDC}")
            print(f"\n[VEN Report] Saving to {output_dir}...")
            paths = gen.export(result, output_dir=output_dir)
            if paths:
                print(f"\n{Colors.GREEN}Report saved:{Colors.ENDC}")
                for p in paths:
                    print(f"  {p}")
            else:
                print(f"{Colors.FAIL}Export failed. Please check permissions.{Colors.ENDC}")
        else:
            print("[VEN Report] No managed workloads found.")
    except Exception as e:
        print(f"{Colors.FAIL}Error: {e}{Colors.ENDC}")
        logger.exception("VEN status report error")

    input(f"\n{Colors.CYAN}[?]{Colors.ENDC} Press Enter to continue ")


if __name__ == "__main__":
    main()
