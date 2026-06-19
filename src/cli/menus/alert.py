"""CLI wizard for alert-channel settings (mail, LINE, webhook, language)."""
from __future__ import annotations
import os

from src.config import ConfigManager
from src.i18n import t, set_language
from src.utils import Colors, safe_input, draw_panel
from src.cli.menus._helpers import _menu_hints, _wizard_step


def alert_settings_menu(cm: ConfigManager) -> None:
    while True:
        os.system("cls" if os.name == "nt" else "clear")
        draw_panel(
            t("settings_alert_title"), _menu_hints("Settings > Alerts")
        )
        _wizard_step(
            1,
            1,
            t("choose_alert_channel"),
        )
        print("")

        current_lang = cm.config.get("settings", {}).get("language", "en")
        active_alerts = cm.config.get("alerts", {}).get("active", ["mail"])

        mail_status = (
            t("ssl_status_on") if "mail" in active_alerts else t("ssl_status_off")
        )
        line_status = (
            t("ssl_status_on") if "line" in active_alerts else t("ssl_status_off")
        )
        webhook_status = (
            t("ssl_status_on") if "webhook" in active_alerts else t("ssl_status_off")
        )
        teams_status = (
            t("ssl_status_on") if "teams" in active_alerts else t("ssl_status_off")
        )

        print(t("change_language", current=current_lang))
        print(t("toggle_mail_alert", status=mail_status))
        print(t("toggle_line_alert", status=line_status))
        print(t("toggle_webhook_alert", status=webhook_status))
        print(t("edit_line_channel_access_token"))
        print(t("edit_line_target_id"))
        print(t("edit_webhook_url"))
        print(t("toggle_teams_alert", status=teams_status))
        print(t("edit_teams_webhook_url"))
        print(t("menu_return"))

        sel = safe_input(f"\n{t('please_select')}", int, range(0, 10))
        if sel is None:
            break

        if sel == 1:
            lang_sel = safe_input(t("select_language"), int, range(1, 3))
            if lang_sel == 1:
                cm.config.setdefault("settings", {})["language"] = "en"
            elif lang_sel == 2:
                cm.config.setdefault("settings", {})["language"] = "zh_TW"
            cm.save()

        elif sel in [2, 3, 4, 8]:
            channel = (
                "mail" if sel == 2
                else "line" if sel == 3
                else "webhook" if sel == 4
                else "teams"
            )
            if channel in active_alerts:
                active_alerts.remove(channel)
            else:
                active_alerts.append(channel)
            cm.config.setdefault("alerts", {})["active"] = active_alerts
            cm.save()

        elif sel == 5:
            current_token = cm.config.get("alerts", {}).get(
                "line_channel_access_token", ""
            )
            masked = current_token[:5] + "..." if current_token else t("not_set")
            new_token = safe_input(
                t("line_token_input"), str, allow_cancel=True, hint=masked
            )
            if new_token:
                cm.config.setdefault("alerts", {})["line_channel_access_token"] = (
                    new_token
                )
                cm.save()

        elif sel == 6:
            current_id = cm.config.get("alerts", {}).get("line_target_id", "")
            masked_id = current_id[:5] + "..." if current_id else t("not_set")
            new_id = safe_input(
                t("line_target_id_input"), str, allow_cancel=True, hint=masked_id
            )
            if new_id:
                cm.config.setdefault("alerts", {})["line_target_id"] = new_id
                cm.save()

        elif sel == 7:
            current_url = cm.config.get("alerts", {}).get("webhook_url", "")
            masked = current_url[:15] + "..." if current_url else t("not_set")
            new_url = safe_input(
                t("webhook_url_input"), str, allow_cancel=True, hint=masked
            )
            if new_url:
                cm.config.setdefault("alerts", {})["webhook_url"] = new_url
                cm.save()

        elif sel == 9:
            current_url = cm.config.get("alerts", {}).get("teams_webhook_url", "")
            masked = current_url[:15] + "..." if current_url else t("not_set")
            new_url = safe_input(
                t("teams_webhook_url_input"), str, allow_cancel=True, hint=masked
            )
            if new_url:
                cm.config.setdefault("alerts", {})["teams_webhook_url"] = new_url
                cm.save()
