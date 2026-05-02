"""CLI wizard for adding or editing system-health alert rules."""
from __future__ import annotations
import os
import datetime

from src.config import ConfigManager
from src.i18n import t
from src.utils import Colors, safe_input, draw_panel
from src.cli.menus._helpers import _menu_hints, _wizard_step, _wizard_confirm


def add_system_health_menu(cm: ConfigManager, edit_rule=None) -> None:
    os.system("cls" if os.name == "nt" else "clear")
    title = (
        t("menu_add_system_health_title", default="=== Add System Health Rule ===")
        if not edit_rule
        else t("modify_rule", name=edit_rule.get("name", ""))
    )
    draw_panel(title, _menu_hints("Rules > System Health"))

    _wizard_step(1, 3, t("wiz_basic_setup"))
    print("")

    def_name = edit_rule.get("name", t("gui_system_health_pce")) if edit_rule else t("gui_system_health_pce")
    name = safe_input(t("rule_name"), str, allow_cancel=True, hint=def_name)
    if name is None:
        return
    if name == "":
        name = def_name
    if not name:
        return

    _wizard_step(2, 3, t("wiz_set_trigger"))
    print(f"\n{Colors.CYAN}{t('gui_system_health_desc')}{Colors.ENDC}")
    print(f"{Colors.DARK_GRAY}{t('gui_system_health_threshold_hint')}{Colors.ENDC}")

    threshold = int(edit_rule.get("threshold_count", 1)) if edit_rule else 1
    window = int(edit_rule.get("threshold_window", 10)) if edit_rule else 10
    def_cd = int(edit_rule.get("cooldown_minutes", 30)) if edit_rule else 30
    cd_in = safe_input(
        t("cooldown_mins").format(win=window),
        int,
        allow_cancel=True,
        hint=str(def_cd),
        help_text=t("def_cooldown"),
    )
    if cd_in is None:
        return
    cooldown = int(cd_in) if cd_in != "" else def_cd

    _wizard_step(3, 3, t("wiz_review_save"))
    summary = [
        f"{t('sum_type')}: system",
        f"{t('sum_name')}: {name}",
        f"{t('sum_event')}: pce_health",
        f"{t('sum_trigger')}: immediate",
        f"{t('sum_threshold')}: {threshold}",
        f"{t('sum_window_cooldown')}: {window}m / {cooldown}m",
    ]
    if not _wizard_confirm(summary):
        return

    rid = (
        edit_rule.get("id", int(datetime.datetime.now().timestamp()))
        if edit_rule
        else int(datetime.datetime.now().timestamp())
    )
    cm.add_or_update_rule(
        {
            "id": rid,
            "type": "system",
            "name": name,
            "filter_key": "system_check",
            "filter_value": "pce_health",
            "desc": t("gui_system_health_desc"),
            "rec": t("check_logs"),
            "threshold_type": "immediate",
            "threshold_count": threshold,
            "threshold_window": window,
            "cooldown_minutes": cooldown,
            "throttle": edit_rule.get("throttle", "") if edit_rule else "",
        }
    )
    input(
        f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('rule_saved')} {Colors.GREEN}❯{Colors.ENDC} "
    )
