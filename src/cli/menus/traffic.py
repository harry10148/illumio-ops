"""CLI wizard for adding or editing traffic alert rules."""
from __future__ import annotations
import os
import datetime

from src.config import ConfigManager
from src.i18n import t
from src.utils import Colors, safe_input, draw_panel, get_last_input_action
from src.cli.menus._helpers import (
    _menu_hints,
    _wizard_step,
    _wizard_confirm,
    _empty_uses_default,
)


def add_traffic_menu(cm: ConfigManager, edit_rule=None) -> None:
    os.system("cls" if os.name == "nt" else "clear")

    def should_restart_flow():
        return get_last_input_action() == "cancel"

    title = (
        t("menu_add_traffic_title")
        if not edit_rule
        else t("modify_traffic_rule", name=edit_rule.get('name', ''))
    )
    draw_panel(
        title,
        _menu_hints("Rules > Traffic"),
    )
    _wizard_step(1, 5, t("wiz_basic_setup"))
    print("")

    def_name = edit_rule.get("name", "") if edit_rule else ""
    name = safe_input(t("rule_name"), str, allow_cancel=True, hint=def_name)
    if name is None:
        if should_restart_flow():
            add_traffic_menu(cm, edit_rule=edit_rule)
        return
    if name == "":
        name = def_name
    if not name:
        return

    def_pd = 1
    if edit_rule:
        tpd = edit_rule.get("pd", 2)
        if tpd == 2:
            def_pd = 1  # Blocked
        elif tpd == 0:
            def_pd = 2  # Potential
        elif tpd == 1:
            def_pd = 3  # Allowed
        elif tpd == -1:
            def_pd = 4  # All

    print(f"{Colors.DARK_GRAY}{t('def_traffic_pd')}{Colors.ENDC}")
    print(t("policy_decision"))
    print(t("pd_1"))
    print(t("pd_2"))
    print(t("pd_3"))
    print(t("pd_4"))
    pd_sel = safe_input(
        t("pd_select_default"), int, range(0, 5), allow_cancel=True, hint=str(def_pd)
    )
    if pd_sel is None:
        if _empty_uses_default(def_pd):
            pd_sel = def_pd
        else:
            if should_restart_flow():
                add_traffic_menu(cm, edit_rule=edit_rule)
            return

    # Menu mapping: 1=Blocked(pd=2), 2=Potential(pd=0), 3=Allowed(pd=1), 4=All(pd=-1)
    if pd_sel == 1:
        target_pd = 2
    elif pd_sel == 2:
        target_pd = 0
    elif pd_sel == 3:
        target_pd = 1
    else:
        target_pd = -1

    _wizard_step(2, 5, t("wiz_traffic_filters"))
    print(f"\n{Colors.CYAN}{t('advanced_filters')}{Colors.ENDC}")
    print(f"{Colors.DARK_GRAY}{t('hint_return')}{Colors.ENDC}")

    def_port = edit_rule.get("port", "") if edit_rule else ""
    port_in = safe_input(
        t("port_input"), int, allow_cancel=True, hint=str(def_port) if def_port else ""
    )
    if port_in is None:
        if _empty_uses_default(def_port):
            port_in = int(def_port)
        else:
            if should_restart_flow():
                add_traffic_menu(cm, edit_rule=edit_rule)
            return

    proto_in = None
    if port_in:
        def_proto = 0
        if edit_rule and edit_rule.get("proto") == 6:
            def_proto = 1
        elif edit_rule and edit_rule.get("proto") == 17:
            def_proto = 2
        p_sel = safe_input(
            t("proto_select"), int, range(0, 3), allow_cancel=True, hint=str(def_proto)
        )
        if p_sel is None:
            if _empty_uses_default(def_proto):
                p_sel = def_proto
            else:
                if should_restart_flow():
                    add_traffic_menu(cm, edit_rule=edit_rule)
                return

        if p_sel == 1:
            proto_in = 6
        elif p_sel == 2:
            proto_in = 17

    def_src = (
        edit_rule.get("src_label", edit_rule.get("src_ip_in", "")) if edit_rule else ""
    )
    src_in = safe_input(t("src_input"), str, allow_cancel=True, hint=def_src)
    if src_in is None:
        if should_restart_flow():
            add_traffic_menu(cm, edit_rule=edit_rule)
        return

    def_dst = (
        edit_rule.get("dst_label", edit_rule.get("dst_ip_in", "")) if edit_rule else ""
    )
    dst_in = safe_input(t("dst_input"), str, allow_cancel=True, hint=def_dst)
    if dst_in is None:
        if should_restart_flow():
            add_traffic_menu(cm, edit_rule=edit_rule)
        return
    if dst_in == "":
        dst_in = def_dst

    _wizard_step(3, 5, t("wiz_trigger_threshold"))
    def_win = edit_rule.get("threshold_window", 10) if edit_rule else 10
    win_in = safe_input(
        t("time_window_mins")
        .replace("[{win}]", "")
        .replace("[Default: 5]", "")
        .strip(),
        int,
        allow_cancel=True,
        hint=str(def_win),
    )
    if win_in is None:
        if _empty_uses_default(def_win):
            win_in = def_win
        else:
            if should_restart_flow():
                add_traffic_menu(cm, edit_rule=edit_rule)
            return
    win = win_in

    def_cnt = edit_rule.get("threshold_count", 10) if edit_rule else 10
    cnt_in = safe_input(
        t("trigger_threshold_count"), int, allow_cancel=True, hint=str(def_cnt)
    )
    if cnt_in is None:
        if _empty_uses_default(def_cnt):
            cnt_in = def_cnt
        else:
            if should_restart_flow():
                add_traffic_menu(cm, edit_rule=edit_rule)
            return
    cnt = cnt_in

    def_cd = edit_rule.get("cooldown_minutes", win) if edit_rule else win
    cd_in = safe_input(
        t("cooldown_mins").format(win=def_win),
        int,
        allow_cancel=True,
        hint=str(def_cd),
        help_text=t("def_cooldown"),
    )
    if cd_in is None:
        if _empty_uses_default(def_cd):
            cd_in = def_cd
        else:
            if should_restart_flow():
                add_traffic_menu(cm, edit_rule=edit_rule)
            return
    cd = cd_in

    src_label_val, src_ip_val = (
        (src_in, None) if src_in and "=" in src_in else (None, src_in)
    )
    dst_label_val, dst_ip_val = (
        (dst_in, None) if dst_in and "=" in dst_in else (None, dst_in)
    )

    _wizard_step(4, 5, t("wiz_exclusions"))
    print(f"\n{Colors.CYAN}{t('excludes_optional')}{Colors.ENDC}")
    def_ex_port = edit_rule.get("ex_port", "") if edit_rule else ""
    ex_port_in = safe_input(
        t("ex_port_input"), int, allow_cancel=True, hint=str(def_ex_port)
    )
    if ex_port_in is None:
        if _empty_uses_default(def_ex_port):
            ex_port_in = int(def_ex_port)
        else:
            if should_restart_flow():
                add_traffic_menu(cm, edit_rule=edit_rule)
            return

    def_ex_src = (
        edit_rule.get("ex_src_label", edit_rule.get("ex_src_ip", ""))
        if edit_rule
        else ""
    )
    ex_src_in = safe_input(t("ex_src_input"), str, allow_cancel=True, hint=def_ex_src)
    if ex_src_in is None:
        if should_restart_flow():
            add_traffic_menu(cm, edit_rule=edit_rule)
        return

    def_ex_dst = (
        edit_rule.get("ex_dst_label", edit_rule.get("ex_dst_ip", ""))
        if edit_rule
        else ""
    )
    ex_dst_in = safe_input(t("ex_dst_input"), str, allow_cancel=True, hint=def_ex_dst)
    if ex_dst_in is None:
        if should_restart_flow():
            add_traffic_menu(cm, edit_rule=edit_rule)
        return

    ex_src_label_val, ex_src_ip_val = (
        (ex_src_in, None) if ex_src_in and "=" in ex_src_in else (None, ex_src_in)
    )
    ex_dst_label_val, ex_dst_ip_val = (
        (ex_dst_in, None) if ex_dst_in and "=" in ex_dst_in else (None, ex_dst_in)
    )

    rid = (
        edit_rule.get("id", int(datetime.datetime.now().timestamp()))
        if edit_rule
        else int(datetime.datetime.now().timestamp())
    )

    _wizard_step(5, 5, t("wiz_review_save"))
    pd_text = {2: "Blocked", 0: "Potential", 1: "Allowed", -1: "All"}.get(
        target_pd, "All"
    )
    summary = [
        f"{t('sum_type')}: traffic",
        f"{t('sum_name')}: {name}",
        f"{t('sum_policy')}: {pd_text}",
        f"{t('sum_port_proto')}: {port_in or '-'} / {proto_in or 'both'}",
        f"{t('sum_src_dst')}: {src_in or '-'} -> {dst_in or '-'}",
        f"{t('sum_threshold')}: {cnt} in {win}m (cooldown {cd}m)",
        f"{t('sum_exclude')}: port={ex_port_in or '-'}, src={ex_src_in or '-'}, dst={ex_dst_in or '-'}",
    ]
    if not _wizard_confirm(summary):
        return

    cm.add_or_update_rule(
        {
            "id": rid,
            "type": "traffic",
            "name": name,
            "pd": target_pd,
            "port": port_in,
            "proto": proto_in,
            "src_label": src_label_val,
            "dst_label": dst_label_val,
            "src_ip_in": src_ip_val,
            "dst_ip_in": dst_ip_val,
            "ex_port": ex_port_in,
            "ex_src_label": ex_src_label_val,
            "ex_dst_label": ex_dst_label_val,
            "ex_src_ip": ex_src_ip_val,
            "ex_dst_ip": ex_dst_ip_val,
            "desc": name,
            "rec": t("check_policy"),
            "threshold_type": "count",
            "threshold_count": cnt,
            "threshold_window": win,
            "cooldown_minutes": cd,
        }
    )
    input(
        f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('traffic_rule_saved')} {Colors.GREEN}❯{Colors.ENDC} "
    )
