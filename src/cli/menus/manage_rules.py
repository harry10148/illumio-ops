"""CLI wizard for the manage-rules menu (list, delete, modify rules)."""
from __future__ import annotations
import os
import re
import sys
import unicodedata

from src.config import ConfigManager
from src.i18n import t
from src.utils import Colors, safe_input, draw_panel, draw_table, get_visible_width
from src.cli.menus._helpers import _menu_hints
from src.cli.menus.event import add_event_menu
from src.cli.menus.system_health import add_system_health_menu
from src.cli.menus.traffic import add_traffic_menu
from src.cli.menus.bandwidth import add_bandwidth_volume_menu


_MANAGE_RULES_COMMAND_RE = re.compile(
    r"^\s*([dm])\s*(\d+(?:\s*,\s*\d+)*)\s*$", re.IGNORECASE
)


def _parse_manage_rules_command(raw: str):
    text = (raw or "").strip()
    match = _MANAGE_RULES_COMMAND_RE.fullmatch(text)
    if not match:
        raise ValueError(t("error_manage_rules_command"))

    action = match.group(1).lower()
    indices = [int(part.strip()) for part in match.group(2).split(",")]

    if action == "m":
        if len(indices) != 1:
            raise ValueError(t("error_manage_rules_modify_single"))
        return action, indices[0]

    return action, indices


def manage_rules_menu(cm: ConfigManager):
    while True:
        os.system("cls" if os.name == "nt" else "clear")
        draw_panel(
            t("menu_manage_rules_title"), _menu_hints("Rules > Manage")
        )
        print("")

        if not cm.config["rules"]:
            print(t("no_rules"))
        else:
            headers = [t("th_no"), t("th_name"), t("th_type"), t("th_condition"), t("th_filters_excludes")]
            rows = []
        for i, r in enumerate(cm.config["rules"]):
            rtype = r["type"].capitalize()
            val = r["threshold_count"]
            if r["type"] == "volume":
                val = f"{val} MB"
            elif r["type"] == "bandwidth":
                val = f"{val} Mbps"
            elif r["type"] == "traffic":
                val = f"{val} ({t('table_num_conns')})"
            cond = f"> {val} (Win: {r.get('threshold_window')}m)"
            cd = r.get("cooldown_minutes", r.get("threshold_window", 10))
            cond += f" (CD:{cd}m)"
            filters = []
            if r["type"] == "traffic":
                pd_map = {
                    2: t("decision_blocked"),
                    1: t("decision_potential"),
                    0: t("decision_allowed"),
                    -1: t("pd_4"),
                }
                filters.append(f"[{pd_map.get(r.get('pd', 2), '?')}]")
            if r.get("port"):
                proto_str = (
                    "/TCP"
                    if r.get("proto") == 6
                    else "/UDP"
                    if r.get("proto") == 17
                    else ""
                )
                filters.append(f"[Port:{r['port']}{proto_str}]")
            if r.get("src_label"):
                filters.append(f"[Src:{r['src_label']}]")
            if r.get("dst_label"):
                filters.append(f"[Dst:{r['dst_label']}]")
            if r.get("src_ip_in"):
                filters.append(f"[SrcIP:{r['src_ip_in']}]")
            if r.get("dst_ip_in"):
                filters.append(f"[DstIP:{r['dst_ip_in']}]")
            if r.get("ex_port"):
                filters.append(
                    f"{Colors.WARNING}[Excl Port:{r['ex_port']}]{Colors.ENDC}"
                )
            if r.get("ex_src_label"):
                filters.append(
                    f"{Colors.WARNING}[Excl Src:{r['ex_src_label']}]{Colors.ENDC}"
                )
            if r.get("ex_dst_label"):
                filters.append(
                    f"{Colors.WARNING}[Excl Dst:{r['ex_dst_label']}]{Colors.ENDC}"
                )
            if r.get("ex_src_ip"):
                filters.append(
                    f"{Colors.WARNING}[Excl SrcIP:{r['ex_src_ip']}]{Colors.ENDC}"
                )
            if r.get("ex_dst_ip"):
                filters.append(
                    f"{Colors.WARNING}[Excl DstIP:{r['ex_dst_ip']}]{Colors.ENDC}"
                )
            filter_str = " ".join(filters)

            display_name = r["name"]

            # CJK-aware truncation to keep table aligned
            if get_visible_width(display_name) > 28:
                temp_name = ""
                curr_w = 0
                for char in display_name:
                    char_w = (
                        2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
                    )
                    if curr_w + char_w + 3 > 28:
                        temp_name += "..."
                        break
                    temp_name += char
                    curr_w += char_w
                display_name = temp_name

            rows.append([str(i), display_name, rtype, cond, filter_str])

        if cm.config["rules"]:
            draw_table(headers, rows)

        val = safe_input(
            t("input_manage_rules_action", default=t("input_delete_indices")),
            str,
            allow_cancel=True,
            help_text=t("help_manage_rules_command"),
        )
        if val in (None, ""):
            break

        try:
            action, target = _parse_manage_rules_command(val)
        except ValueError as exc:
            print(f"{Colors.FAIL}{exc}{Colors.ENDC}")
            input(
                f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('press_enter_to_continue')} {Colors.GREEN}❯{Colors.ENDC} "
            )
            continue

        if action == "d":
            try:
                cm.remove_rules_by_index(target)
                print(t("done"))
            except Exception as e:
                print(t("error_deleting", error=str(e)))
        elif action == "m":
            try:
                idx = target
                if not (0 <= idx < len(cm.config["rules"])):
                    raise ValueError(t("error_out_of_range"))

                rule = cm.config["rules"][idx]
                print(
                    f"\n{Colors.CYAN}{t('modifying_rule', name=rule['name'])}{Colors.ENDC}"
                )
                rtype = rule["type"]
                _s = sys.modules.get("src.settings", sys.modules[__name__])
                if rtype == "event":
                    _s.add_event_menu(cm, edit_rule=rule)
                elif rtype == "system":
                    _s.add_system_health_menu(cm, edit_rule=rule)
                elif rtype == "traffic":
                    _s.add_traffic_menu(cm, edit_rule=rule)
                elif rtype in ["bandwidth", "volume"]:
                    _s.add_bandwidth_volume_menu(cm, edit_rule=rule)
            except Exception as e:
                print(t("error_modifying", error=str(e)))

        input(
            f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('press_enter_to_continue')} {Colors.GREEN}❯{Colors.ENDC} "
        )
