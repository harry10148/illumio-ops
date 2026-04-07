import os
import datetime
from src.utils import Colors, safe_input, draw_panel, draw_table, get_last_input_action
from src.config import ConfigManager
from src.i18n import t, set_language, get_language
from src import __version__

FULL_EVENT_CATALOG = {
    "General": {"*": "event_all_events"},
    "Agent Health": {
        "system_task.agent_missed_heartbeats_check": "event_agent_missed_heartbeats",
        "system_task.agent_offline_check": "event_agent_offline",
        "lost_agent.found": "event_lost_agent_found",
        "agent.service_not_available": "event_agent_service_not_available",
    },
    "Agent Security": {
        "agent.tampering": "event_agent_tampering",
        "agent.clone_detected": "event_agent_clone_detected",
        "agent.activate": "event_agent_activate",
        "agent.deactivate": "event_agent_deactivate",
    },
    "User Access": {
        "user.authenticate": "event_user_authenticate",
        "user.sign_in": "event_user_sign_in",
        "user.sign_out": "event_user_sign_out",
        "user.login_session_terminated": "event_user_login_session_terminated",
        "user.pce_session_terminated": "event_user_pce_session_terminated",
    },
    "Agent Health Detail": {
        "agent.goodbye": "event_agent_goodbye",
        "agent.suspend": "event_agent_suspend",
        "agent.refresh_policy": "event_agent_refresh_policy",
    },
    "Auth & API": {
        "request.authentication_failed": "event_api_auth_failed",
        "request.authorization_failed": "event_api_authz_failed",
        "api_key.create": "event_api_key_create",
        "api_key.delete": "event_api_key_delete",
    },
    "Policy": {
        "rule_set.delete": "event_ruleset_delete",
        "rule_set.create": "event_ruleset_create",
        "rule_set.update": "event_ruleset_update",
        "sec_rule.create": "event_rule_create",
        "sec_rule.update": "event_rule_update",
        "sec_rule.delete": "event_rule_delete",
        "sec_policy.create": "event_policy_prov",
    },
    "System": {
        "cluster.update": "event_cluster_update",
        "pce_health": "event_pce_health_check",
    },
}


def _tz_offset_info(cm: 'ConfigManager') -> tuple:
    """Return (tz_label: str, offset_hours: float) from config's settings.timezone."""
    tz_str = cm.config.get('settings', {}).get('timezone', 'local')
    if not tz_str or tz_str == 'local':
        offset = datetime.datetime.now(datetime.timezone.utc).astimezone().utcoffset()
        hours = offset.total_seconds() / 3600
        sign = '+' if hours >= 0 else '-'
        abs_h = abs(hours)
        label = (f"UTC{sign}{int(abs_h):02d}" if abs_h == int(abs_h)
                 else f"UTC{sign}{abs_h}")
        return label, hours
    if tz_str == 'UTC':
        return 'UTC', 0.0
    if tz_str.startswith('UTC+') or tz_str.startswith('UTC-'):
        sign = 1 if tz_str[3] == '+' else -1
        hours = sign * float(tz_str[4:])
        return tz_str, hours
    return 'UTC', 0.0


def _utc_to_local_hour(utc_hour: int, offset_hours: float) -> int:
    return int(((utc_hour + offset_hours) % 24 + 24) % 24)


def _local_to_utc_hour(local_hour: int, offset_hours: float) -> int:
    return int(((local_hour - offset_hours) % 24 + 24) % 24)


def _menu_hints(path):
    return [
        f"{Colors.DARK_GRAY}{t('cli_path_label', path=path)}{Colors.ENDC}",
        f"{Colors.DARK_GRAY}{t('cli_shortcuts_compact')}{Colors.ENDC}",
    ]


def _wizard_step(step, total, title):
    step_label = t("wiz_step")
    print(f"\n{Colors.BOLD}{Colors.CYAN}[{step_label} {step}/{total}] {title}{Colors.ENDC}")


def _wizard_confirm(summary_lines):
    title = t("wiz_review_config")
    draw_panel(title, summary_lines)
    prompt = t("wiz_save_rule_confirm")
    answer = (
        input(f"\n{Colors.CYAN}[?]{Colors.ENDC} {prompt} {Colors.GREEN}❯{Colors.ENDC} ")
        .strip()
        .lower()
    )
    if not answer:
        return True
    return answer in ["y", "yes", "是", "好"]


# Events that support Status (Success/Failure) and Severity filtering
ACTION_EVENTS = [
    "user.authenticate",
    "user.sign_in",
    "user.sign_out",
    "request.authentication_failed",
    "request.authorization_failed",
    "api_key.create",
    "api_key.delete",
    "rule_set.create",
    "rule_set.update",
    "rule_set.delete",
    "sec_rule.create",
    "sec_rule.update",
    "sec_rule.delete",
    "sec_policy.create",
    "cluster.update",
    "agent.activate",
    "agent.deactivate",
    "agent.refresh_policy",
]

# Events that are mostly discovery/state based (hide Status/Severity prompts)
DISCOVERY_EVENTS = [
    "system_task.agent_missed_heartbeats_check",
    "system_task.agent_offline_check",
    "lost_agent.found",
    "agent.service_not_available",
    "agent.tampering",
    "agent.clone_detected",
    "agent.goodbye",
    "agent.suspend",
]


def add_event_menu(cm: ConfigManager, edit_rule=None):
    from src.utils import Colors, safe_input, draw_panel, draw_table

    while True:
        os.system("cls" if os.name == "nt" else "clear")
        title = (
            t("menu_add_event_title")
            if not edit_rule
            else t("modify_event_rule", name=edit_rule.get('name', ''))
        )
        draw_panel(
            title,
            _menu_hints("Rules > Event"),
        )

        sel = ""
        if not edit_rule:
            print("")
            cats = list(FULL_EVENT_CATALOG.keys())
            for i, c in enumerate(cats):
                print(f"{i + 1}. {c}")
            sel = (
                input(
                    f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('select_category')} {Colors.GREEN}❯{Colors.ENDC} "
                )
                .strip()
                .upper()
            )
        else:
            cats = list(FULL_EVENT_CATALOG.keys())
            cur_val = edit_rule.get("filter_value")
            cat = next(
                (name for name, ev in FULL_EVENT_CATALOG.items() if cur_val in ev), None
            )
            if not cat:
                cat = cats[0]
            sel = str(cats.index(cat) + 1)
        if sel == "0":
            break
        if not sel.isdigit() or not (1 <= int(sel) <= len(cats)):
            continue
        _wizard_step(
            1, 4, t("wiz_select_event_type")
        )
        cat = cats[int(sel) - 1]
        evts = FULL_EVENT_CATALOG[cat]
        evt_keys = list(evts.keys())
        print(f"\n{Colors.BOLD}{Colors.CYAN}--- {cat} ---{Colors.ENDC}")
        headers = [t("th_no"), t("th_event_type"), t("th_description")]
        rows = []
        for i, k in enumerate(evt_keys):
            desc = t(FULL_EVENT_CATALOG[cat][k])
            display_k = k if k != "*" else t("all_events")
            rows.append([str(i + 1), display_k, desc])
        draw_table(headers, rows)

        print(f"\n{t('menu_cancel')}")
        if edit_rule and edit_rule.get("filter_value") in evt_keys:
            def_idx = evt_keys.index(edit_rule["filter_value"]) + 1
            ei = (
                safe_input(
                    f"{t('select_event')} [{def_idx}]",
                    int,
                    range(0, len(evt_keys) + 1),
                    allow_cancel=True,
                )
                or def_idx
            )
        else:
            ei = safe_input(t("select_event"), int, range(0, len(evt_keys) + 1))

        if not ei or ei == 0:
            continue
        k = evt_keys[ei - 1]
        _wizard_step(
            2,
            4,
            t("wiz_set_trigger"),
        )
        print(f"\n{t('selected')}: {k}")
        pmpt = f"{t('rule_trigger_type_1')}  {t('rule_trigger_type_2')}"
        def_ti = (
            1 if not edit_rule or edit_rule.get("threshold_type") == "immediate" else 2
        )
        ti = safe_input(
            pmpt, int, range(0, 3), allow_cancel=True, help_text=t("def_threshold_type")
        )
        if ti is None:
            continue
        if ti == "" or ti == 0:
            ti = def_ti
        ttype, cnt, win = "immediate", 1, 10
        def_win = edit_rule.get("threshold_window", 10) if edit_rule else 10
        if ti == 2:
            ttype = "count"
            def_cnt = edit_rule.get("threshold_count", 5) if edit_rule else 5
            cnt_in = safe_input(
                t("cumulative_count"), int, hint=str(def_cnt), allow_cancel=True
            )
            if cnt_in is None:
                continue
            cnt = int(cnt_in) if cnt_in != "" else def_cnt
            win_in = safe_input(
                t("time_window_mins"), int, hint=str(def_win), allow_cancel=True
            )
            if win_in is None:
                continue
            win = int(win_in) if win_in != "" else def_win

        def_cd = edit_rule.get("cooldown_minutes", win) if edit_rule else win
        cd_in = safe_input(
            t("cooldown_mins").format(win=def_win),
            int,
            allow_cancel=True,
            hint=str(def_cd),
            help_text=t("def_cooldown"),
        )
        cd = int(cd_in) if cd_in and cd_in != "" else def_cd
        rid = (
            edit_rule.get("id", int(datetime.datetime.now().timestamp()))
            if edit_rule
            else int(datetime.datetime.now().timestamp())
        )

        # Determine if we should show Advanced Filters based on event type
        sel_status = "all"
        sel_sev = "all"

        show_status = k in ACTION_EVENTS
        show_severity = k in ACTION_EVENTS or k == "*"

        if show_status or show_severity:
            _wizard_step(
                3, 4, t("wiz_advanced_filters")
            )
            print(f"\n{Colors.CYAN}--- {t('advanced_filters')} ---{Colors.ENDC}")
            print(f"{Colors.DARK_GRAY}{t('hint_return')}{Colors.ENDC}")

            if show_status:
                def_status = (
                    edit_rule.get("filter_status", "all") if edit_rule else "all"
                )
                s_map = {1: "success", 2: "failure", 0: "all"}
                s_inv = {v: k for k, v in s_map.items()}
                si = safe_input(
                    t("filter_status").strip(),
                    int,
                    range(0, 3),
                    allow_cancel=True,
                    hint=str(s_inv.get(def_status, 0)),
                    help_text=t("def_filters"),
                )
                if si is None:
                    break
                if si == "":
                    si = s_inv.get(def_status, 0)
                sel_status = s_map.get(si, def_status)

            if show_severity:
                # Default to 'error' for global events (*)
                default_sev_key = "error" if k == "*" and not edit_rule else "all"
                def_sev = (
                    edit_rule.get("filter_severity", default_sev_key)
                    if edit_rule
                    else default_sev_key
                )
                v_map = {1: "error", 2: "warning", 3: "info", 0: "all"}
                v_inv = {v: k for k, v in v_map.items()}
                vi = safe_input(
                    t("filter_severity").strip(),
                    int,
                    range(0, 4),
                    allow_cancel=True,
                    hint=str(v_inv.get(def_sev, 0)),
                    help_text=t("def_filters"),
                )
                if vi is None:
                    break
                if vi == "":
                    vi = v_inv.get(def_sev, 0)
                sel_sev = v_map.get(vi, def_sev)

        _wizard_step(
            4, 4, t("wiz_review_save")
        )
        summary = [
            f"{t('sum_type')}: event",
            f"{t('sum_event')}: {k}",
            f"{t('sum_trigger')}: {ttype}",
            f"{t('sum_threshold')}: {cnt}",
            f"{t('sum_window_cooldown')}: {win}m / {cd}m",
            f"{t('sum_status_severity')}: {sel_status} / {sel_sev}",
        ]
        if not _wizard_confirm(summary):
            continue

        cm.add_or_update_rule(
            {
                "id": rid,
                "type": "event",
                "name": t(evts[k]),
                "filter_key": "event_type",
                "filter_value": k,
                "filter_status": sel_status,
                "filter_severity": sel_sev,
                "desc": t(evts[k]),
                "rec": t("check_logs"),
                "threshold_type": ttype,
                "threshold_count": cnt,
                "threshold_window": win,
                "cooldown_minutes": cd,
            }
        )
        input(
            f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('rule_saved')} {Colors.GREEN}❯{Colors.ENDC} "
        )
        break


def add_traffic_menu(cm: ConfigManager, edit_rule=None):
    from src.utils import Colors, safe_input, draw_panel
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
        if should_restart_flow():
            add_traffic_menu(cm, edit_rule=edit_rule)
        return
    if pd_sel == "":
        pd_sel = def_pd

    # 選單對應: 1=Blocked(pd=2), 2=Potential(pd=0), 3=Allowed(pd=1), 4=All(pd=-1)
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
        if should_restart_flow():
            add_traffic_menu(cm, edit_rule=edit_rule)
        return
    if port_in == "":
        port_in = int(def_port) if def_port else None

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
            if should_restart_flow():
                add_traffic_menu(cm, edit_rule=edit_rule)
            return
        if p_sel == "":
            p_sel = def_proto

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
        if should_restart_flow():
            add_traffic_menu(cm, edit_rule=edit_rule)
        return
    win = int(win_in) if win_in != "" else def_win

    def_cnt = edit_rule.get("threshold_count", 10) if edit_rule else 10
    cnt_in = safe_input(
        t("trigger_threshold_count"), int, allow_cancel=True, hint=str(def_cnt)
    )
    if cnt_in is None:
        if should_restart_flow():
            add_traffic_menu(cm, edit_rule=edit_rule)
        return
    cnt = int(cnt_in) if cnt_in != "" else def_cnt

    def_cd = edit_rule.get("cooldown_minutes", win) if edit_rule else win
    cd_in = safe_input(
        t("cooldown_mins").format(win=def_win),
        int,
        allow_cancel=True,
        hint=str(def_cd),
        help_text=t("def_cooldown"),
    )
    if cd_in is None:
        if should_restart_flow():
            add_traffic_menu(cm, edit_rule=edit_rule)
        return
    cd = int(cd_in) if cd_in != "" else def_cd

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


def add_bandwidth_volume_menu(cm: ConfigManager, edit_rule=None):
    from src.utils import Colors, safe_input, draw_panel
    os.system("cls" if os.name == "nt" else "clear")

    def should_restart_flow():
        return get_last_input_action() == "cancel"

    title = (
        t("menu_add_bw_vol_title")
        if not edit_rule
        else t("modify_rule", name=edit_rule.get('name', ''))
    )
    draw_panel(
        title,
        _menu_hints("Rules > Bandwidth/Volume"),
    )
    _wizard_step(1, 5, t("wiz_basic_setup"))
    print("")

    def_name = edit_rule.get("name", "") if edit_rule else ""
    name = safe_input(t("rule_name_bw"), str, allow_cancel=True, hint=def_name)
    if name is None:
        if should_restart_flow():
            add_bandwidth_volume_menu(cm, edit_rule=edit_rule)
        return
    if name == "":
        name = def_name
    if not name:
        return

    _wizard_step(2, 5, t("wiz_select_metric"))
    print(f"\n{Colors.CYAN}{t('step_1_metric')}{Colors.ENDC}")
    print(t("metric_1"))
    print(t("metric_2"))

    def_msel = (
        1
        if edit_rule and edit_rule.get("type") == "bandwidth"
        else (2 if edit_rule else None)
    )
    m_sel = safe_input(
        t("please_select"), int, range(0, 3), allow_cancel=True, hint=str(def_msel)
    )
    if m_sel is None:
        if should_restart_flow():
            add_bandwidth_volume_menu(cm, edit_rule=edit_rule)
        return
    if m_sel == "" and def_msel:
        m_sel = def_msel
    if not m_sel or m_sel not in (1, 2):
        return

    rtype = "bandwidth" if m_sel == 1 else "volume"
    unit_prompt = "Mbps" if m_sel == 1 else "MB"

    _wizard_step(3, 5, t("wiz_filters"))
    print(f"\n{Colors.CYAN}{t('step_2_filters')}{Colors.ENDC}")
    print(f"{Colors.DARK_GRAY}{t('hint_return')}{Colors.ENDC}")

    def_port = edit_rule.get("port", "") if edit_rule else ""
    port_in = safe_input(
        t("port_input"), int, allow_cancel=True, hint=str(def_port) if def_port else ""
    )
    if port_in is None:
        if should_restart_flow():
            add_bandwidth_volume_menu(cm, edit_rule=edit_rule)
        return
    if port_in == "":
        port_in = int(def_port) if def_port else None

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
            if should_restart_flow():
                add_bandwidth_volume_menu(cm, edit_rule=edit_rule)
            return
        if p_sel == 1:
            proto_in = 6
        elif p_sel == 2:
            proto_in = 17
        elif p_sel == "":
            proto_in = edit_rule.get("proto") if edit_rule else None

    def_src = (
        edit_rule.get("src_label", edit_rule.get("src_ip_in", "")) if edit_rule else ""
    )
    src_in = safe_input(t("src_input"), str, allow_cancel=True, hint=def_src)
    if src_in is None:
        if should_restart_flow():
            add_bandwidth_volume_menu(cm, edit_rule=edit_rule)
        return

    def_dst = (
        edit_rule.get("dst_label", edit_rule.get("dst_ip_in", "")) if edit_rule else ""
    )
    dst_in = safe_input(t("dst_input"), str, allow_cancel=True, hint=def_dst)
    if dst_in is None:
        if should_restart_flow():
            add_bandwidth_volume_menu(cm, edit_rule=edit_rule)
        return

    src_label_val, src_ip_val = (
        (src_in, None) if src_in and "=" in src_in else (None, src_in)
    )
    dst_label_val, dst_ip_val = (
        (dst_in, None) if dst_in and "=" in dst_in else (None, dst_in)
    )

    _wizard_step(4, 5, t("wiz_threshold"))
    print(f"\n{Colors.CYAN}{t('step_3_threshold')}{Colors.ENDC}")
    def_th = edit_rule.get("threshold_count", "") if edit_rule else ""
    th_in = safe_input(
        t("trigger_threshold_unit", unit=unit_prompt),
        float,
        allow_cancel=True,
        hint=str(def_th) if def_th else "",
        help_text=t("def_traffic_vol"),
    )
    if th_in is None:
        if should_restart_flow():
            add_bandwidth_volume_menu(cm, edit_rule=edit_rule)
        return
    th = float(th_in) if th_in != "" else (float(def_th) if def_th != "" else None)
    if th is None:
        return

    def_win = edit_rule.get("threshold_window", 5) if edit_rule else 5
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
        if should_restart_flow():
            add_bandwidth_volume_menu(cm, edit_rule=edit_rule)
        return
    win = int(win_in) if win_in != "" else def_win

    def_cd = edit_rule.get("cooldown_minutes", win) if edit_rule else win
    cd_in = safe_input(
        t("cooldown_mins").format(win=def_win),
        int,
        allow_cancel=True,
        hint=str(def_cd),
        help_text=t("def_cooldown"),
    )
    if cd_in is None:
        if should_restart_flow():
            add_bandwidth_volume_menu(cm, edit_rule=edit_rule)
        return
    cd = int(cd_in) if cd_in != "" else def_cd

    print(f"\n{Colors.CYAN}{t('excludes_optional')}{Colors.ENDC}")
    def_ex_port = edit_rule.get("ex_port", "") if edit_rule else ""
    ex_port_in = safe_input(
        t("ex_port_input"), int, allow_cancel=True, hint=str(def_ex_port)
    )
    if ex_port_in is None:
        if should_restart_flow():
            add_bandwidth_volume_menu(cm, edit_rule=edit_rule)
        return

    def_ex_src = (
        edit_rule.get("ex_src_label", edit_rule.get("ex_src_ip", ""))
        if edit_rule
        else ""
    )
    ex_src_in = safe_input(t("ex_src_input"), str, allow_cancel=True, hint=def_ex_src)
    if ex_src_in is None:
        if should_restart_flow():
            add_bandwidth_volume_menu(cm, edit_rule=edit_rule)
        return

    def_ex_dst = (
        edit_rule.get("ex_dst_label", edit_rule.get("ex_dst_ip", ""))
        if edit_rule
        else ""
    )
    ex_dst_in = safe_input(t("ex_dst_input"), str, allow_cancel=True, hint=def_ex_dst)
    if ex_dst_in is None:
        if should_restart_flow():
            add_bandwidth_volume_menu(cm, edit_rule=edit_rule)
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
    summary = [
        f"{t('sum_type')}: {rtype}",
        f"{t('sum_name')}: {name}",
        f"{t('sum_unit_threshold')}: {unit_prompt} / {th}",
        f"{t('sum_port_proto')}: {port_in or '-'} / {proto_in or 'both'}",
        f"{t('sum_src_dst')}: {src_in or '-'} -> {dst_in or '-'}",
        f"{t('sum_window_cooldown')}: {win}m / {cd}m",
        f"{t('sum_exclude')}: port={ex_port_in or '-'}, src={ex_src_in or '-'}, dst={ex_dst_in or '-'}",
    ]
    if not _wizard_confirm(summary):
        return

    cm.add_or_update_rule(
        {
            "id": rid,
            "type": rtype,
            "name": name,
            "pd": edit_rule.get("pd", -1) if edit_rule else -1,
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
            "threshold_type": "immediate",
            "threshold_count": th,
            "threshold_window": win,
            "cooldown_minutes": cd,
            "desc": t("alert_desc", type=rtype, threshold=th, unit=unit_prompt),
            "rec": t("check_network"),
        }
    )
    input(
        f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('rule_saved')} {Colors.GREEN}❯{Colors.ENDC} "
    )


def manage_rules_menu(cm: ConfigManager):
    from src.utils import draw_panel, draw_table, get_visible_width

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

            import unicodedata

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

        val = (
            input(
                f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('input_delete_indices')} {Colors.GREEN}❯{Colors.ENDC} "
            )
            .strip()
            .lower()
        )
        if val == "0" or not val:
            break

        if val.startswith("d ") or (
            val.startswith("d") and len(val) > 1 and val[1].isdigit()
        ):
            # Handle both 'd 0, 1' and 'd0, 1'
            target = val[1:].strip()
            if target.startswith("d"):
                target = target[1:].strip()
            try:
                indices = [int(x.strip()) for x in target.split(",")]
                cm.remove_rules_by_index(indices)
                print(t("done"))
            except Exception as e:
                print(t("error_deleting", error=str(e)))
        elif val.startswith("m ") or (
            val.startswith("m") and len(val) > 1 and val[1].isdigit()
        ):
            target = val[1:].strip()
            if target.startswith("m"):
                target = target[1:].strip()
            try:
                idx = int(target)
                if 0 <= idx < len(cm.config["rules"]):
                    rule = cm.config["rules"][idx]
                    print(
                        f"\n{Colors.CYAN}{t('modifying_rule', name=rule['name'])}{Colors.ENDC}"
                    )
                    rtype = rule["type"]
                    cm.remove_rules_by_index([idx])
                    if rtype == "event":
                        add_event_menu(cm, edit_rule=rule)
                    elif rtype == "traffic":
                        add_traffic_menu(cm, edit_rule=rule)
                    elif rtype in ["bandwidth", "volume"]:
                        add_bandwidth_volume_menu(cm, edit_rule=rule)
            except Exception as e:
                print(t("error_modifying", error=str(e)))
        else:
            print(
                f"{Colors.FAIL}{t('error_format', default='Invalid format.')}{Colors.ENDC}"
            )

        input(
            f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('press_enter_to_continue')} {Colors.GREEN}❯{Colors.ENDC} "
        )


def alert_settings_menu(cm: ConfigManager):
    from src.utils import draw_panel

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

        print(t("change_language", lang=current_lang))
        print(t("toggle_mail_alert", status=mail_status))
        print(t("toggle_line_alert", status=line_status))
        print(t("toggle_webhook_alert", status=webhook_status))
        print(t("edit_line_channel_access_token"))
        print(t("edit_line_target_id"))
        print(t("edit_webhook_url"))
        print(t("menu_return"))

        sel = safe_input(f"\n{t('please_select')}", int, range(0, 8))
        if sel is None:
            break

        if sel == 1:
            lang_sel = safe_input(t("select_language"), int, range(1, 3))
            if lang_sel == 1:
                cm.config.setdefault("settings", {})["language"] = "en"
            elif lang_sel == 2:
                cm.config.setdefault("settings", {})["language"] = "zh_TW"
            cm.save()

        elif sel in [2, 3, 4]:
            channel = "mail" if sel == 2 else "line" if sel == 3 else "webhook"
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


def web_gui_security_menu(cm: ConfigManager):
    import secrets
    import hashlib
    from src.utils import draw_panel

    def _hash_pass(salt, pw):
        return hashlib.sha256((salt + pw).encode('utf-8')).hexdigest()

    while True:
        os.system("cls" if os.name == "nt" else "clear")
        draw_panel(
            t("wgs_menu_title", default="=== Web GUI Security ==="),
            _menu_hints("Web GUI Security"),
        )
        
        gui_cfg = cm.config.get("web_gui", {})
        username = gui_cfg.get("username", "illumio")
        has_auth = bool(gui_cfg.get("password_hash"))
        allowed_ips = gui_cfg.get("allowed_ips", [])
        
        auth_status = f"{Colors.GREEN}Configured{Colors.ENDC}" if has_auth else f"{Colors.WARNING}Default (illumio){Colors.ENDC}"
        ips_list = ", ".join(allowed_ips) if allowed_ips else "All (No restriction)"
        
        print(f"  {t('wgs_username', default='Username')}:    {username}")
        print(f"  {t('wgs_auth', default='Password')}:    {auth_status}")
        print(f"  {t('wgs_ips', default='Allowed IPs')}: {ips_list}")
        print("-" * 40)
        print("  1. " + t("wgs_change_auth", default="Change Username / Password"))
        print("  2. " + t("wgs_manage_ips", default="Manage Allowed IPs"))
        print("  0. " + t("menu_return", default="0. Return"))
        
        sel = safe_input(f"\n{t('please_select')}", int, range(0, 3))
        if sel is None or sel == 0:
            break
            
        elif sel == 1:
            cm.config.setdefault("web_gui", {})
            new_user = safe_input(t("wgs_user_input", default="New Username"), str, allow_cancel=True, hint=username)
            if new_user:
                cm.config["web_gui"]["username"] = new_user
                
            new_pass = safe_input(t("wgs_new_pass", default="New Password"), str, allow_cancel=True)
            if new_pass:
                salt = secrets.token_hex(8)
                cm.config["web_gui"]["password_salt"] = salt
                cm.config["web_gui"]["password_hash"] = _hash_pass(salt, new_pass)
                print(f"\n{Colors.GREEN}Password updated.{Colors.ENDC}")
                cm.save()
            input(f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('press_enter_to_continue')} ")
            
        elif sel == 2:
            while True:
                os.system("cls" if os.name == "nt" else "clear")
                curr_ips = cm.config.get("web_gui", {}).get("allowed_ips", [])
                print(f"=== {t('wgs_manage_ips', default='Manage Allowed IPs')} ===")
                if not curr_ips:
                    print(f"  {Colors.WARNING}List is empty. All IPs are allowed.{Colors.ENDC}")
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
                    new_ip = safe_input("Enter IP or CIDR (e.g. 192.168.1.100 or 10.0.0.0/8): ", str, allow_cancel=True)
                    if new_ip:
                        curr_ips.append(new_ip.strip())
                        cm.config.setdefault("web_gui", {})["allowed_ips"] = curr_ips
                        cm.save()
                elif act == "D" and curr_ips:
                    idx = safe_input("Enter number to delete: ", int, range(1, len(curr_ips) + 1))
                    if idx is not None:
                        curr_ips.pop(idx - 1)
                        cm.config["web_gui"]["allowed_ips"] = curr_ips
                        cm.save()


def settings_menu(cm: ConfigManager):
    from src.utils import draw_panel

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
            new_sec = safe_input(t("lbl_api_secret"), str, allow_cancel=True, hint="******")
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
                new_pass = safe_input(t("lbl_password"), str, allow_cancel=True, hint="******")
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


# ─── Report Schedule Management ───────────────────────────────────────────────

def manage_report_schedules_menu(cm: ConfigManager):
    """Main menu for listing and managing report schedules."""
    from src.utils import Colors, safe_input, draw_panel, draw_table

    while True:
        os.system("cls" if os.name == "nt" else "clear")
        schedules = cm.get_report_schedules()

        # Load last-run states from state.json
        import json as _json
        pkg_dir = os.path.dirname(os.path.abspath(__file__))
        root_dir = os.path.dirname(pkg_dir)
        state_file = os.path.join(root_dir, "logs", "state.json")
        states = {}
        if os.path.exists(state_file):
            try:
                with open(state_file, "r", encoding="utf-8") as f:
                    states = _json.load(f).get("report_schedule_states", {})
            except Exception:
                pass

        draw_panel(t("sched_menu_title"), [])

        if not schedules:
            print(f"\n  {Colors.DARK_GRAY}{t('sched_no_schedules')}{Colors.ENDC}")
        else:
            headers = [
                t("sched_col_name"), t("sched_col_type"), t("sched_col_freq"),
                t("sched_col_last"), t("sched_col_status"), t("sched_col_enabled"),
            ]
            rows = []
            for i, s in enumerate(schedules):
                sid = str(s.get("id", ""))
                state = states.get(sid, {})
                last_run = (state.get("last_run") or t("sched_status_never"))[:16]
                status_raw = state.get("status", "")
                if status_raw == "success":
                    status = f"{Colors.GREEN}{t('sched_status_success')}{Colors.ENDC}"
                elif status_raw == "failed":
                    status = f"{Colors.FAIL}{t('sched_status_failed')}{Colors.ENDC}"
                else:
                    status = Colors.DARK_GRAY + t("sched_status_never") + Colors.ENDC
                enabled = f"{Colors.GREEN}ON{Colors.ENDC}" if s.get("enabled") else f"{Colors.FAIL}OFF{Colors.ENDC}"

                freq_map = {"daily": t("freq_daily"), "weekly": t("freq_weekly", day=s.get('day_of_week','')[:3].capitalize()),
                            "monthly": t("freq_monthly", day=s.get('day_of_month', 1))}
                freq = freq_map.get(s.get("schedule_type", "weekly"), s.get("schedule_type", "?"))

                type_map = {"traffic": t("type_traffic"), "audit": t("type_audit"), "ven_status": t("type_ven")}
                rtype = type_map.get(s.get("report_type", ""), s.get("report_type", "?"))
                rows.append([f"[{i+1}] {s.get('name','')}", rtype, freq, last_run, status, enabled])

            draw_table(headers, rows)

        print(f"\n  {t('sched_add')}  |  {t('sched_edit')}  |  {t('sched_toggle')}  |  {t('sched_delete')}  |  {t('sched_run_now')}  |  {t('sched_back')}")
        action = safe_input(f"\n{t('sched_select_action')} [A/E/T/D/R/0]", str)
        if action is None:
            action = "0"
        action = action.strip().upper()

        if action == "0" or action == "":
            break
        elif action == "A":
            _add_report_schedule_wizard(cm)
        elif action in ("E", "T", "D", "R"):
            if not schedules:
                print(f"{Colors.WARNING}{t('no_schedules_to_act')}{Colors.ENDC}")
                input(f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('press_enter_to_continue')} ")
                continue
            idx_str = safe_input(t("sched_select_index") + f" [1-{len(schedules)}]", str)
            try:
                idx = int(idx_str) - 1   # display is 1-based; 0 is reserved for "back"
                if not (0 <= idx < len(schedules)):
                    raise ValueError
            except (ValueError, TypeError):
                print(f"{Colors.FAIL}{t('invalid_selection')}{Colors.ENDC}")
                input(f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('press_enter_to_continue')} ")
                continue
            sched = schedules[idx]

            if action == "E":
                _add_report_schedule_wizard(cm, edit_sched=sched)
            elif action == "T":
                new_enabled = not sched.get("enabled", False)
                cm.update_report_schedule(sched["id"], {"enabled": new_enabled})
                msg = t("sched_enabled") if new_enabled else t("sched_disabled")
                print(f"{Colors.GREEN}{msg}{Colors.ENDC}")
                input(f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('press_enter_to_continue')} ")
            elif action == "D":
                confirm = safe_input(t("confirm_delete_sched", name=sched.get('name', '')), str).strip().lower()
                if confirm in ("", "y", "yes"):
                    cm.remove_report_schedule(sched["id"])
                    print(f"{Colors.GREEN}{t('sched_deleted')}{Colors.ENDC}")
                    input(f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('press_enter_to_continue')} ")
            elif action == "R":
                print(f"\n{Colors.CYAN}{t('sched_running')}{Colors.ENDC}")
                try:
                    from src.report_scheduler import ReportScheduler
                    from src.reporter import Reporter
                    reporter = Reporter(cm)
                    scheduler = ReportScheduler(cm, reporter)
                    scheduler.run_schedule(sched)
                    print(f"{Colors.GREEN}{t('sched_run_success')}{Colors.ENDC}")
                except Exception as e:
                    print(f"{Colors.FAIL}{t('sched_run_failed', error=e)}{Colors.ENDC}")
                input(f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('press_enter_to_continue')} ")


def _add_report_schedule_wizard(cm: ConfigManager, edit_sched: dict = None):
    """Wizard for adding or editing a report schedule."""
    from src.utils import Colors, safe_input, draw_panel

    is_edit = edit_sched is not None
    title = t("sched_edit") if is_edit else t("sched_add")
    os.system("cls" if os.name == "nt" else "clear")
    draw_panel(title, [])

    def _ask(prompt, default="", cast=str):
        hint = f" (default: {default})" if default != "" else ""
        val = safe_input(f"{prompt}{hint}", str, allow_cancel=True)
        if val is None:
            return None
        val = val.strip()
        if val == "" and default != "":
            val = str(default)
        if val == "":
            return None
        try:
            return cast(val)
        except (ValueError, TypeError):
            return default

    # Step 1: Name
    _wizard_step(1, 7, t("sched_name"))
    default_name = edit_sched.get("name", "") if is_edit else ""
    name = _ask(t("sched_name"), default=default_name)
    if name is None:
        return

    # Step 2: Report type
    _wizard_step(2, 7, t("sched_report_type"))
    type_map = {"1": "traffic", "2": "audit", "3": "ven_status"}
    default_type_k = {"traffic": "1", "audit": "2", "ven_status": "3"}.get(
        edit_sched.get("report_type", "traffic") if is_edit else "traffic", "1")
    print(f"  {t('opt_traffic_report')}\n  {t('opt_audit_report')}\n  {t('opt_ven_report')}")
    type_sel = _ask(t("sched_report_type"), default=default_type_k)
    if type_sel is None:
        return
    report_type = type_map.get(str(type_sel), "traffic")

    # Step 3: Frequency
    _wizard_step(3, 7, t("sched_schedule_type"))
    freq_map = {"1": "daily", "2": "weekly", "3": "monthly"}
    default_freq_k = {"daily": "1", "weekly": "2", "monthly": "3"}.get(
        edit_sched.get("schedule_type", "weekly") if is_edit else "weekly", "2")
    print(f"  {t('opt_daily')}\n  {t('opt_weekly')}\n  {t('opt_monthly')}")
    freq_sel = _ask(t("sched_schedule_type"), default=default_freq_k)
    if freq_sel is None:
        return
    schedule_type = freq_map.get(str(freq_sel), "weekly")

    day_of_week = edit_sched.get("day_of_week", "monday") if is_edit else "monday"
    day_of_month = edit_sched.get("day_of_month", 1) if is_edit else 1
    if schedule_type == "weekly":
        dow = _ask(t("sched_day_of_week"), default=day_of_week)
        if dow is None:
            return
        day_of_week = dow
    elif schedule_type == "monthly":
        dom = _ask(t("sched_day_of_month"), default=str(day_of_month), cast=int)
        if dom is None:
            return
        day_of_month = dom

    # Step 4: Time (input in configured timezone, stored as UTC)
    tz_label, offset_hours = _tz_offset_info(cm)
    _wizard_step(4, 7, t("wiz_execution_time", tz=tz_label))
    # When editing, convert stored UTC hour → local display hour
    stored_hour = edit_sched.get("hour", 8) if is_edit else 8
    default_local_hour = str(_utc_to_local_hour(int(stored_hour), offset_hours))
    default_minute = str(edit_sched.get("minute", 0)) if is_edit else "0"
    hour_val = _ask(f"{t('sched_hour')} ({tz_label})", default=default_local_hour, cast=int)
    if hour_val is None:
        return
    minute_val = _ask(t("sched_minute"), default=default_minute, cast=int)
    if minute_val is None:
        return
    local_hour = max(0, min(23, int(hour_val)))
    minute = max(0, min(59, int(minute_val)))
    # Convert local tz hour → UTC for storage
    hour = _local_to_utc_hour(local_hour, offset_hours)

    # Step 5: Lookback days
    _wizard_step(5, 7, t("sched_lookback_days"))
    default_lookback = str(edit_sched.get("lookback_days", 7)) if is_edit else "7"
    lookback_val = _ask(t("sched_lookback_days"), default=default_lookback, cast=int)
    if lookback_val is None:
        return
    lookback_days = int(lookback_val)

    # Step 6: Output format
    _wizard_step(6, 7, t("sched_format"))
    fmt_map = {"1": ["html"], "2": ["csv"], "3": ["html", "csv"]}
    current_fmt = edit_sched.get("format", ["html"]) if is_edit else ["html"]
    default_fmt_k = "3" if len(current_fmt) > 1 else ("2" if current_fmt == ["csv"] else "1")
    print(f"  {t('opt_html')}\n  {t('opt_csv_zip')}\n  {t('opt_html_csv')}")
    fmt_sel = _ask(t("sched_format"), default=default_fmt_k)
    if fmt_sel is None:
        return
    fmt = fmt_map.get(str(fmt_sel), ["html"])

    # Step 7: Email
    _wizard_step(7, 7, t("wiz_email_options"))
    default_email = "Y" if (edit_sched.get("email_report", False) if is_edit else False) else "N"
    email_ans = _ask(t("sched_email_report"), default=default_email)
    if email_ans is None:
        return
    send_email = email_ans.upper() in ("Y", "YES")

    custom_recipients = []
    if send_email:
        default_recips = ",".join(edit_sched.get("email_recipients", [])) if is_edit else ""
        recips_str = _ask(t("sched_email_recipients"), default=default_recips) or ""
        custom_recipients = [r.strip() for r in recips_str.split(",") if r.strip()]

    # Confirm
    _email_val = t('sum_no')
    if send_email:
        _email_val = t('sum_yes') + (' → ' + t('sum_custom') + ': ' + ','.join(custom_recipients) if custom_recipients else ' ' + t('sum_default'))
    summary = [
        f"  {t('sum_name')}:       {name}",
        f"  {t('sum_type')}:       {report_type}",
        f"  {t('sum_frequency')}:  {schedule_type}" + (f" ({day_of_week})" if schedule_type == "weekly" else
                                             f" (day {day_of_month})" if schedule_type == "monthly" else ""),
        f"  {t('sum_time')}:       {local_hour:02d}:{minute:02d} {tz_label}  (= {hour:02d}:{minute:02d} UTC)",
        f"  {t('sum_lookback')}:   {lookback_days} {t('sum_days')}",
        f"  {t('sum_format')}:     {'+'.join(fmt)}",
        f"  {t('sum_email')}:      {_email_val}",
    ]
    if not _wizard_confirm(summary):
        return

    sched = {
        "name": name,
        "report_type": report_type,
        "schedule_type": schedule_type,
        "day_of_week": day_of_week,
        "day_of_month": day_of_month,
        "hour": hour,
        "minute": minute,
        "lookback_days": lookback_days,
        "format": fmt,
        "email_report": send_email,
        "email_recipients": custom_recipients,
        "enabled": True,
        "output_dir": cm.config.get("report", {}).get("output_dir", "reports/"),
    }

    if is_edit:
        sched["id"] = edit_sched["id"]
        sched["enabled"] = edit_sched.get("enabled", True)
        cm.update_report_schedule(edit_sched["id"], sched)
    else:
        cm.add_report_schedule(sched)

    print(f"\n{Colors.GREEN}{t('sched_saved')}{Colors.ENDC}")
    input(f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('press_enter_to_continue')} ")
