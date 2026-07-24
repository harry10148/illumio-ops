"""Top-level settings wizard (entry point for all settings navigation)."""
from __future__ import annotations
import os

from src import __version__
from src.config import ConfigManager
from src.i18n import t
from src.utils import Colors, safe_input, draw_panel
from src.cli.menus._helpers import _menu_hints, _wizard_step
from src.cli.menus.alert import alert_settings_menu
from src.cli.menus.web_gui import web_gui_security_menu


def settings_menu(cm: ConfigManager) -> None:
    while True:
        os.system("cls" if os.name == "nt" else "clear")
        draw_panel(
            t("menu_settings_title", version=__version__),
            _menu_hints("Settings"),
        )
        _wizard_step(
            1,
            1,
            t("wiz_choose_settings"),
        )
        print("")
        masked_key = (
            cm.config["api"]["key"][:5] + "..."
            if cm.config["api"]["key"]
            else t("not_set")
        )
        print(f"{t('gui_api_url')} : {cm.config['api']['url']}")
        print(f"{t('gui_api_key')} : {masked_key}")

        alerts_cfg = cm.config.get("alerts", {})
        active = alerts_cfg.get("active", ["mail"])
        channels = []
        if "mail" in active:
            channels.append(f"Mail ({cm.config['email']['sender']})")
        if "line" in active:
            channels.append("LINE")
        if "webhook" in active:
            channels.append("Webhook")

        print(f"{t('gui_alerts')}  : {', '.join(channels) if channels else t('not_set')}")
        print("-" * 40)
        print(t("settings_1"))
        print(t("settings_2"))
        ssl_status = (
            t("ssl_verify")
            if cm.config["api"].get("verify_ssl", True)
            else t("ssl_ignore")
        )
        print(t("settings_3", status=ssl_status))
        smtp_conf = cm.config.get("smtp", {})
        auth_status = f"Auth:{t('ssl_status_on') if smtp_conf.get('enable_auth') else t('ssl_status_off')}"
        print(
            f"{t('settings_4')} ({smtp_conf.get('host')}:{smtp_conf.get('port')} | {auth_status})"
        )
        rpt_cfg = cm.config.get("report", {})
        rpt_dir = rpt_cfg.get("output_dir", "reports/")
        rpt_ret = rpt_cfg.get("retention_days", 30)
        print(t("settings_5", output_dir=rpt_dir, retention_days=rpt_ret))
        rs_cfg = cm.config.get("rule_scheduler", {})
        rs_status = "ON" if rs_cfg.get("enabled", False) else "OFF"
        print(t("settings_6", status=rs_status))
        print(t("settings_7_web_gui_sec"))
        print(t("menu_return"))
        sel = safe_input(f"\n{t('please_select')}", int, range(0, 8))
        if sel is None:
            break
        if sel == 1:
            new_url = safe_input(
                t("lbl_api_url"), str, allow_cancel=True, hint=cm.config["api"]["url"]
            )
            if new_url:
                cm.config["api"]["url"] = new_url.strip('"').strip("'")

            cm.config["api"]["org_id"] = (
                safe_input(
                    t("lbl_org_id"), str, allow_cancel=True, hint=cm.config["api"]["org_id"]
                )
                or cm.config["api"]["org_id"]
            )
            cm.config["api"]["key"] = (
                safe_input(t("lbl_api_key"), str, allow_cancel=True, hint=masked_key)
                or cm.config["api"]["key"]
            )
            new_sec = safe_input(t("lbl_api_secret"), str, allow_cancel=True, hint="******", hidden=True)
            if new_sec:
                cm.config["api"]["secret"] = new_sec
            # Sync changes back to active PCE profile (if any)
            cm.sync_api_to_active_profile()
            cm.save()
        elif sel == 2:
            alert_settings_menu(cm)
        elif sel == 3:
            current = cm.config["api"].get("verify_ssl", True)
            print(
                f"{t('settings_3', status=t('ssl_status_on') if current else t('ssl_status_off'))}"
            )
            choice = safe_input(t("change_verify_to"), int, range(1, 3))
            if choice:
                cm.config["api"]["verify_ssl"] = choice == 1
                cm.sync_api_to_active_profile()
                cm.save()
        elif sel == 4:
            c = cm.config.get("smtp", {})
            print(f"\n{Colors.CYAN}{t('setup_smtp')}{Colors.ENDC}")
            c["host"] = safe_input(
                t("lbl_smtp_host"), str, allow_cancel=True, hint=c.get("host", "localhost")
            ) or c.get("host", "localhost")
            c["port"] = safe_input(
                t("lbl_smtp_port"), int, allow_cancel=True, hint=str(c.get("port", 25))
            ) or c.get("port", 25)

            enable_tls = safe_input(
                t("enable_starttls", status=c.get("enable_tls", False)),
                str,
                allow_cancel=True,
            )
            if enable_tls and enable_tls.lower() == "y":
                c["enable_tls"] = True
            elif enable_tls and enable_tls.lower() == "n":
                c["enable_tls"] = False

            enable_auth = safe_input(
                t("enable_auth", status=c.get("enable_auth", False)),
                str,
                allow_cancel=True,
            )
            if enable_auth and enable_auth.lower() == "y":
                c["enable_auth"] = True
            elif enable_auth and enable_auth.lower() == "n":
                c["enable_auth"] = False

            if c["enable_auth"]:
                c["user"] = safe_input(
                    t("lbl_username"), str, allow_cancel=True, hint=c.get("user", "")
                ) or c.get("user", "")
                new_pass = safe_input(t("lbl_password"), str, allow_cancel=True, hint="******", hidden=True)
                if new_pass:
                    c["password"] = new_pass

            cm.config["smtp"] = c
            cm.save()
        elif sel == 5:
            rc = cm.config.setdefault("report", {})
            print(f"\n{Colors.CYAN}{t('setup_report_output')}{Colors.ENDC}")
            new_dir = safe_input(
                t("report_output_dir"), str, allow_cancel=True,
                hint=rc.get("output_dir", "reports/")
            ) or rc.get("output_dir", "reports/")
            rc["output_dir"] = new_dir.strip()

            ret_hint = str(rc.get("retention_days", 30))
            new_ret = safe_input(
                t("report_retention_days"), int, allow_cancel=True, hint=ret_hint
            )
            if new_ret is not None:
                rc["retention_days"] = max(0, int(new_ret))
            cm.save()
            print(f"{Colors.GREEN}{t('saved')}{Colors.ENDC}")
        elif sel == 6:
            rs_c = cm.config.setdefault("rule_scheduler", {})
            print(f"\n{Colors.HEADER}╭── {Colors.BOLD}{t('rs_menu_settings')}{Colors.ENDC}")
            enabled = rs_c.get("enabled", False)
            interval = rs_c.get("check_interval_seconds", 300)
            en_str = f"{Colors.GREEN}ON{Colors.ENDC}" if enabled else f"{Colors.FAIL}OFF{Colors.ENDC}"
            print(f"{Colors.HEADER}│{Colors.ENDC} {t('rs_cfg_enabled')}: {en_str}")
            print(f"{Colors.HEADER}│{Colors.ENDC} {t('rs_cfg_interval')}: {interval}s")
            print(f"{Colors.HEADER}├{'─' * 40}{Colors.ENDC}")
            print(f"{Colors.HEADER}│{Colors.ENDC} 1. {t('rs_cfg_toggle')}")
            print(f"{Colors.HEADER}│{Colors.ENDC} 2. {t('rs_cfg_set_interval')}")
            print(f"{Colors.HEADER}│{Colors.ENDC} 0. {t('menu_return', default='0. Back')}")
            print(f"{Colors.HEADER}╰{'─' * 40}{Colors.ENDC}")
            rs_sel = safe_input(f"\n{t('please_select')}", int, range(0, 3))
            if rs_sel == 1:
                rs_c["enabled"] = not enabled
                cm.save()
            elif rs_sel == 2:
                new_int = safe_input(
                    t("rs_cfg_interval_prompt"), int, allow_cancel=True,
                    hint=str(interval)
                )
                if new_int and int(new_int) > 0:
                    rs_c["check_interval_seconds"] = int(new_int)
                    cm.save()
        elif sel == 7:
            web_gui_security_menu(cm)
