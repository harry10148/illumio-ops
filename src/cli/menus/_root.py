"""Top-level settings wizard (entry point for all settings navigation)."""
from __future__ import annotations
import os

from pydantic import ValidationError

from src import __version__
from src import config_models
from src.config import ConfigManager, resolve_state_file
from src.i18n import t
from src.utils import Colors, safe_input, draw_panel
from src.cli.menus._helpers import _menu_hints, _wizard_step
from src.cli.menu_chrome import menu_screen
from src.cli.health_line import build_health_line
from src.cli.menus.alert import alert_settings_menu
from src.cli.menus.web_gui import web_gui_security_menu
from src.pce_target import normalize_org_id, normalize_pce_url, pce_target_changed


def _pce_connection_menu(cm) -> None:
    """#29+#31 merged: connection fields and the SSL toggle on one screen.

    The three-state commit below is load-bearing and is NOT a confirm box.
    "Clear the cache", "keep it" and "cancel the edit" are three answers; a
    bool carries two, and folding them loses the middle one — an operator
    moving the appliance to a new address for the same PCE.

    The flush must precede cm.save(): past the save the stored connection
    names the new PCE, the guard never fires for this edit again, and the
    old PCE's cache would stay for good.
    """
    # Collect into locals first, don't touch cm.config yet: if the
    # target-change question below gets cancelled, the whole edit
    # must be abandoned rather than half-saved.
    masked_key = (
        cm.config["api"]["key"][:5] + "..."
        if cm.config["api"]["key"]
        else t("not_set")
    )
    old_api = dict(cm.config["api"])
    deployment_raw = safe_input(
        t("lbl_deployment_type"), str, {"saas", "on_prem"},
        allow_cancel=True, hint=old_api.get("deployment_type", "on_prem"),
    )
    if deployment_raw is None:
        return
    new_deployment = deployment_raw or old_api.get("deployment_type", "on_prem")
    console_default = old_api.get("console_url", "")
    if new_deployment == "saas" and not console_default:
        console_default = "https://console.illum.io"
    console_raw = safe_input(
        t("lbl_console_url"), str, allow_cancel=True, hint=console_default,
    )
    if console_raw is None:
        return
    new_console_url = (console_raw or console_default) \
        if new_deployment == "saas" else console_raw
    new_url_raw = safe_input(
        t("lbl_api_url"), str, allow_cancel=True, hint=old_api["url"]
    )
    # Normalized before it is compared or stored, same as the other
    # two paths (src/pce_target.py) — otherwise a retyped trailing
    # slash reads as a different PCE and offers to destroy a cache
    # that was fine.
    new_url = normalize_pce_url(
        new_url_raw.strip('"').strip("'") if new_url_raw else old_api["url"])
    new_org_id = normalize_org_id(
        safe_input(t("lbl_org_id"), str, allow_cancel=True, hint=old_api["org_id"])
        or old_api["org_id"]
    )
    new_key = (
        safe_input(t("lbl_api_key"), str, allow_cancel=True, hint=masked_key)
        or old_api["key"]
    )
    new_sec = safe_input(t("lbl_api_secret"), str, allow_cancel=True, hint="******", hidden=True)
    new_secret = new_sec if new_sec else old_api["secret"]

    candidate_api = dict(old_api)
    candidate_api.update({
        "deployment_type": new_deployment,
        "console_url": new_console_url,
        "url": new_url,
        "org_id": new_org_id,
        "key": new_key,
        "secret": new_secret,
    })
    try:
        validated_api = config_models.ApiSettings.model_validate(candidate_api)
    except ValidationError as exc:
        errors = [
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
            for err in exc.errors()
        ]
        print(f"{Colors.FAIL}"
              f"{t('cli_config_validation_failed', errors='; '.join(errors))}"
              f"{Colors.ENDC}")
        safe_input(t("press_enter_to_continue"), str, allow_cancel=True)
        return
    validated_api_dict = validated_api.model_dump()

    # Changing which PCE this appliance talks to is not an edit — the
    # cache, the ingestion positions, the archive files and the alert
    # cooldowns all carry the previous PCE's data with no marker
    # saying so. There's an operator watching this menu, so ask now
    # rather than defaulting to either behaviour.
    current = cm.config["api"].get("verify_ssl", True)
    print(
        f"{t('settings_3', status=t('ssl_status_on') if current else t('ssl_status_off'))}"
    )
    choice = safe_input(t("change_verify_to"), int, range(1, 3))
    if choice:
        # No save here: this screen has one commit point, below, and the
        # flush has to run before it.
        candidate_api["verify_ssl"] = choice == 1
        validated_api_dict["verify_ssl"] = choice == 1

    do_flush = False
    cancelled = False
    target_changed = pce_target_changed(old_api, new_url, new_org_id)
    runtime_connection_changed = any(
        old_api.get(k, validated_api_dict[k]) != validated_api_dict[k]
        for k in ("deployment_type", "console_url")
    )
    if target_changed:
        choice = safe_input(t("cli_pce_target_change_prompt_menu"), int, range(1, 3))
        if choice is None:
            cancelled = True
        else:
            do_flush = choice == 1

    if not cancelled:
        saved = True
        if do_flush:
            # Before cm.save(), the same order the other two paths use:
            # past the save the stored connection names the new PCE, so
            # the guard never fires for this edit again and the old
            # PCE's cache would stay for good. A clear that fails here
            # costs a re-run, whose clear is idempotent.
            from src.pce_cache.flush import flush_pce_derived_state
            try:
                flush_pce_derived_state(cm.models.pce_cache.db_path,
                                        resolve_state_file())
            except Exception as exc:
                saved = False
                print(f"{Colors.FAIL}"
                      f"{t('cli_pce_flush_failed_menu', error=str(exc)[:200])}"
                      f"{Colors.ENDC}")
                safe_input(t("press_enter_to_continue"), str, allow_cancel=True)
        if saved:
            cm.config["api"] = validated_api_dict
            cm.save()
            if target_changed or runtime_connection_changed:
                # A running monitor service holds its own
                # ConfigManager for the life of the process and never
                # reloads it. Only a target change can also involve a
                # flush; metadata-only edits get accurate guidance.
                restart_key = ("cli_pce_restart_required_menu" if target_changed
                               else "cli_connection_restart_required_menu")
                print(f"{Colors.WARNING}"
                      f"{t(restart_key)}{Colors.ENDC}")
                safe_input(t("press_enter_to_continue"), str, allow_cancel=True)


def _smtp_menu(cm) -> None:
    """Moved out of the settings dispatch unchanged."""
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


def _view_logs_entry() -> None:
    """Thin wrapper so the menu test can stub it without importing main."""
    from src import main as _main
    log_file = getattr(_main, "LOG_FILE", "") or ""
    if not log_file:
        root = os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))))
        log_file = os.path.join(root, "logs", "illumio_ops.log")
    _main.view_logs(log_file)


def system_menu(cm: ConfigManager) -> None:
    """§3.3.6 — every setting has exactly one home, and this is the list of them.

    Two items are gone rather than moved twice: Report Output settings live in
    the Reports area (RP-1), and the rule scheduler's enable/interval switch has
    its only home inside rule_scheduler_cli (AU-2).
    """
    while True:
        cm.load()
        masked_key = (
            cm.config["api"]["key"][:5] + "..."
            if cm.config["api"]["key"]
            else t("not_set")
        )
        lines = [
            f"{t('gui_api_url')} : {cm.config['api']['url']}",
            f"{t('gui_api_key')} : {masked_key}",
            "-",
            t("cli_sys_pce_connection"),
            t("cli_sys_alert_channels"),
            t("cli_sys_smtp"),
            t("cli_sys_web_gui"),
            t("cli_sys_pce_cache"),
            t("cli_sys_siem"),
            t("cli_sys_view_logs"),
            "",
            t("menu_return"),
        ]
        menu_screen(t("cli_area_system"), lines, health=build_health_line(cm))
        sel = safe_input(f"\n{t('please_select')}", int, range(0, 8))
        if sel is None or sel == 0:
            break
        if sel == 1:
            _pce_connection_menu(cm)
        elif sel == 2:
            alert_settings_menu(cm)
        elif sel == 3:
            _smtp_menu(cm)
        elif sel == 4:
            web_gui_security_menu(cm)
        elif sel == 5:
            import src.pce_cache_cli as pcc
            pcc.manage_pce_cache_menu(cm)
        elif sel == 6:
            import src.siem_cli as siem
            siem.manage_siem_menu(cm)
        elif sel == 7:
            _view_logs_entry()


# src/settings/__init__.py's shim imports this name; keep it resolving.
settings_menu = system_menu
