"""CLI wizard for Web GUI security settings (password, IP restrictions, TLS)."""
from __future__ import annotations
import os

from src.config import ConfigManager
from src.i18n import t
from src.utils import Colors, safe_input, draw_panel
from src.cli.menus._helpers import _menu_hints


def _clear_screen() -> None:
    """Centralised screen-clear so callers don't each invoke os.system."""
    os.system("cls" if os.name == "nt" else "clear")


def web_gui_security_menu(cm: ConfigManager) -> None:
    while True:
        os.system("cls" if os.name == "nt" else "clear")
        draw_panel(
            t("wgs_menu_title", default="=== Web GUI Security ==="),
            _menu_hints("Web GUI Security"),
        )

        gui_cfg = cm.config.get("web_gui", {})
        username = gui_cfg.get("username", "illumio")
        has_auth = bool(gui_cfg.get("password"))
        allowed_ips = gui_cfg.get("allowed_ips", [])

        auth_status = (
            f"{Colors.GREEN}{t('wgs_auth_configured')}{Colors.ENDC}"
            if has_auth
            else f"{Colors.WARNING}{t('wgs_auth_default_user')}{Colors.ENDC}"
        )
        ips_list = ", ".join(allowed_ips) if allowed_ips else t("wgs_ips_all")

        tls_cfg = gui_cfg.get("tls", {})
        tls_on = bool(tls_cfg.get("enabled"))
        tls_mode = (
            t("wgs_tls_mode_self", default="Self-signed") if tls_cfg.get("self_signed")
            else (t("wgs_tls_mode_custom", default="Custom cert") if tls_cfg.get("cert_file") else "-")
        )
        tls_status = (
            f"{Colors.GREEN}{t('status_on', default='ON')}{Colors.ENDC} ({tls_mode})" if tls_on
            else f"{Colors.WARNING}{t('status_off', default='OFF')}{Colors.ENDC}"
        )

        print(f"  {t('wgs_username', default='Username')}:    {username}")
        print(f"  {t('wgs_auth', default='Password')}:    {auth_status}")
        print(f"  {t('wgs_ips', default='Allowed IPs')}: {ips_list}")
        print(f"  {t('wgs_tls', default='TLS / HTTPS')}:       {tls_status}")
        print("-" * 40)
        print("  1. " + t("wgs_change_auth", default="Change Username / Password"))
        print("  2. " + t("wgs_manage_ips", default="Manage Allowed IPs"))
        print("  3. " + t("wgs_tls_menu", default="Configure TLS / HTTPS"))
        print("  0. " + t("menu_return", default="0. Return"))

        sel = safe_input(f"\n{t('please_select')}", int, range(0, 4))
        if sel is None or sel == 0:
            break

        elif sel == 1:
            cm.config.setdefault("web_gui", {})
            new_user = safe_input(t("wgs_user_input", default="New Username"), str, allow_cancel=True, hint=username)
            if new_user:
                cm.config["web_gui"]["username"] = new_user

            new_pass = safe_input(t("wgs_new_pass", default="New Password"), str, allow_cancel=True, hidden=True)
            if new_pass:
                from src.config import hash_password
                cm.config["web_gui"]["password"] = hash_password(new_pass)
                # CLI is the forgot-password recovery path. Once the admin has
                # reset the credential locally, don't bounce them back through
                # the must-change gate at next web login.
                cm.config["web_gui"].pop("_initial_password", None)
                cm.config["web_gui"].pop("must_change_password", None)
                print(f"\n{Colors.GREEN}{t('wgs_pw_updated')}{Colors.ENDC}")
                cm.save()
            input(f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('press_enter_to_continue')} ")

        elif sel == 2:
            while True:
                os.system("cls" if os.name == "nt" else "clear")
                curr_ips = cm.config.get("web_gui", {}).get("allowed_ips", [])
                print(f"=== {t('wgs_manage_ips', default='Manage Allowed IPs')} ===")
                if not curr_ips:
                    print(f"  {Colors.WARNING}{t('wgs_ips_empty')}{Colors.ENDC}")
                else:
                    for i, ip in enumerate(curr_ips):
                        print(f"  {i+1}. {ip}")
                print("-" * 40)
                print("  A. " + t("wgs_add_ip", default="Add IP/CIDR"))
                print("  D. " + t("wgs_del_ip", default="Delete IP/CIDR"))
                print("  0. " + t("menu_return", default="0. Return"))

                act = safe_input(f"\n{t('please_select')}", str, allow_cancel=True)
                if not act or act == "0": break

                act = act.upper()
                if act == "A":
                    new_ip = safe_input(t("wgs_prompt_add_ip"), str, allow_cancel=True)
                    if new_ip:
                        from src.gui._helpers import _validate_allowed_ips
                        normalized, invalid = _validate_allowed_ips([new_ip])
                        if invalid:
                            print(f"  {Colors.FAIL}{t('wgs_ip_invalid', entry=new_ip.strip())}{Colors.ENDC}")
                            input(f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('press_enter_to_continue')} ")
                        else:
                            curr_ips.extend(normalized)
                            cm.config.setdefault("web_gui", {})["allowed_ips"] = curr_ips
                            cm.save()
                elif act == "D" and curr_ips:
                    idx = safe_input(t("wgs_prompt_del_ip_index"), int, range(1, len(curr_ips) + 1))
                    if idx is not None:
                        curr_ips.pop(idx - 1)
                        cm.config["web_gui"]["allowed_ips"] = curr_ips
                        cm.save()

        elif sel == 3:
            _web_gui_tls_menu(cm)


def _web_gui_tls_menu(cm: ConfigManager) -> None:
    """Interactive TLS / HTTPS configuration for the Web GUI.

    Mirrors the options available in the GUI Settings → TLS fieldset so a
    headless operator can toggle HTTPS, switch between self-signed and
    custom certs, configure auto-renew, or force a manual renew without
    opening a browser.
    """
    # Lazy import — keeps the top-level CLI loadable even when Flask (and
    # therefore src.gui) is missing; we only need the helpers, not Flask.
    # COORDINATION WITH H5: If H5 has moved these helpers from
    # src/gui/__init__.py to src/gui/tls.py, update the import path to
    # `from src.gui.tls import ...` before committing this task.
    try:
        from src.gui import (
            _generate_self_signed_cert,
            _get_cert_info,
            _cert_days_remaining,
            _ROOT_DIR,
            _SELF_SIGNED_VALIDITY_DAYS,
        )
    except ImportError as exc:
        print(f"{Colors.FAIL}TLS helpers unavailable: {exc}{Colors.ENDC}")
        input(f"{t('press_enter_to_continue')} ")
        return

    cert_dir = os.path.join(_ROOT_DIR, "config", "tls")

    while True:
        _clear_screen()
        gui_cfg = cm.config.setdefault("web_gui", {})
        tls = gui_cfg.setdefault("tls", {})
        enabled = bool(tls.get("enabled"))
        self_signed = bool(tls.get("self_signed"))
        cert_file = tls.get("cert_file", "")
        key_file = tls.get("key_file", "")
        auto_renew = bool(tls.get("auto_renew", True))
        auto_renew_days = int(tls.get("auto_renew_days", 30))

        # Resolve effective cert path (either the custom one or the
        # self-signed file we manage in config/tls).
        active_cert_path = None
        if self_signed:
            active_cert_path = os.path.join(cert_dir, "self_signed.pem")
        elif cert_file:
            active_cert_path = cert_file

        draw_panel(
            t("wgs_tls_title", default="=== Web GUI TLS / HTTPS ==="),
            _menu_hints("TLS"),
        )

        on = f"{Colors.GREEN}ON{Colors.ENDC}"
        off = f"{Colors.WARNING}OFF{Colors.ENDC}"
        print(f"  {t('wgs_tls_enabled', default='HTTPS')}:         {on if enabled else off}")
        mode_label = (
            t("wgs_tls_mode_self", default="Self-signed") if self_signed
            else (t("wgs_tls_mode_custom", default="Custom cert") if cert_file else "-")
        )
        print(f"  {t('wgs_tls_mode', default='Mode')}:          {mode_label}")
        if cert_file or key_file:
            print(f"  {t('wgs_tls_cert_file', default='Cert file')}:    {cert_file or '-'}")
            print(f"  {t('wgs_tls_key_file',  default='Key file')}:    {key_file or '-'}")

        if active_cert_path:
            info = _get_cert_info(active_cert_path)
            if info.get("exists"):
                days = _cert_days_remaining(active_cert_path)
                days_str = f"{days}" if isinstance(days, int) else "?"
                expiry_hint = ""
                if info.get("expired"):
                    expiry_hint = f" {Colors.FAIL}{t('wgs_tls_expired')}{Colors.ENDC}"
                elif info.get("expiring_soon"):
                    expiry_hint = f" {Colors.WARNING}{t('wgs_tls_expiring_soon')}{Colors.ENDC}"
                print(f"  {t('wgs_tls_valid_until', default='Valid until')}: "
                      f"{info.get('not_after', '-')}{expiry_hint}")
                print(f"  {t('wgs_tls_days_remaining', default='Days remaining')}: {days_str}")
            else:
                print(f"  {t('wgs_tls_no_cert', default='No certificate found (will be generated on GUI start).')}")

        if self_signed:
            ar = on if auto_renew else off
            print(f"  {t('wgs_tls_auto_renew', default='Auto-renew')}:    {ar} "
                  f"({t('wgs_tls_threshold', default='threshold')}: {auto_renew_days}d)")
        print(f"  {t('wgs_tls_default_validity', default='Default validity')}: "
              f"{_SELF_SIGNED_VALIDITY_DAYS} days (~{_SELF_SIGNED_VALIDITY_DAYS // 365} years)")

        print("-" * 40)
        print("  1. " + t("wgs_tls_toggle", default="Toggle HTTPS (enable/disable)"))
        print("  2. " + t("wgs_tls_switch_mode", default="Switch mode (self-signed <-> custom)"))
        print("  3. " + t("wgs_tls_edit_paths", default="Edit custom cert/key paths"))
        print("  4. " + t("wgs_tls_toggle_autorenew", default="Toggle auto-renew"))
        print("  5. " + t("wgs_tls_set_threshold", default="Set auto-renew threshold (days)"))
        print("  6. " + t("wgs_tls_renew_now", default="Renew self-signed certificate now"))
        print("  0. " + t("menu_return", default="Return"))

        sel = safe_input(f"\n{t('please_select')}", int, range(0, 7))
        if sel is None or sel == 0:
            break

        if sel == 1:
            tls["enabled"] = not enabled
            cm.save()
            print(
                f"\n{Colors.GREEN}"
                f"{t('wgs_tls_https_enabled_msg' if tls['enabled'] else 'wgs_tls_https_disabled_msg', restart_hint=t('wgs_tls_restart_hint', default='Restart the Web GUI to apply.'))}"
                f"{Colors.ENDC}"
            )
            input(f"{t('press_enter_to_continue')} ")

        elif sel == 2:
            tls["self_signed"] = not self_signed
            if tls["self_signed"]:
                # When flipping to self-signed, clear out any stale custom
                # paths so startup uses the managed cert unambiguously.
                tls["cert_file"] = ""
                tls["key_file"] = ""
            cm.save()
            new_mode = (
                t("wgs_tls_mode_self", default="Self-signed")
                if tls["self_signed"]
                else t("wgs_tls_mode_custom", default="Custom cert")
            )
            print(f"\n{Colors.GREEN}{t('wgs_tls_mode_switched', new_mode=new_mode)}{Colors.ENDC}")
            input(f"{t('press_enter_to_continue')} ")

        elif sel == 3:
            new_cert = safe_input(
                t("wgs_tls_cert_prompt", default="Certificate file path (blank = keep)"),
                str, allow_cancel=True, hint=cert_file or "/path/to/cert.pem",
            )
            new_key = safe_input(
                t("wgs_tls_key_prompt", default="Private key file path (blank = keep)"),
                str, allow_cancel=True, hint=key_file or "/path/to/key.pem",
            )
            if new_cert is not None and new_cert != "":
                tls["cert_file"] = new_cert.strip()
            if new_key is not None and new_key != "":
                tls["key_file"] = new_key.strip()
            cm.save()
            input(f"{t('press_enter_to_continue')} ")

        elif sel == 4:
            tls["auto_renew"] = not auto_renew
            cm.save()
            print(
                f"\n{Colors.GREEN}"
                f"{t('wgs_tls_autorenew_enabled' if tls['auto_renew'] else 'wgs_tls_autorenew_disabled')}"
                f"{Colors.ENDC}"
            )
            input(f"{t('press_enter_to_continue')} ")

        elif sel == 5:
            val = safe_input(
                t("wgs_tls_threshold_prompt", default="Days before expiry to trigger renewal"),
                int, range(1, 366), allow_cancel=True, hint=str(auto_renew_days),
            )
            if isinstance(val, int):
                tls["auto_renew_days"] = val
                cm.save()
                print(f"\n{Colors.GREEN}{t('wgs_tls_threshold_set', val=val)}{Colors.ENDC}")
                input(f"{t('press_enter_to_continue')} ")

        elif sel == 6:
            if not self_signed:
                print(f"\n{Colors.WARNING}"
                      + t("wgs_tls_renew_not_self", default="Renew only applies to self-signed mode.")
                      + f"{Colors.ENDC}")
                input(f"{t('press_enter_to_continue')} ")
                continue
            try:
                cert_path, _ = _generate_self_signed_cert(cert_dir, force=True)
                days = _cert_days_remaining(cert_path)
                print(f"\n{Colors.GREEN}"
                      + t("wgs_tls_renewed", default="Certificate renewed. Restart the Web GUI to apply.")
                      + f" ({days} days){Colors.ENDC}")
            except (RuntimeError, OSError) as exc:
                print(f"\n{Colors.FAIL}{exc}{Colors.ENDC}")
            input(f"{t('press_enter_to_continue')} ")
