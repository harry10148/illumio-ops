import os
import datetime
from src.utils import Colors, safe_input
from src.config import ConfigManager
from src.i18n import t, set_language
from src import __version__

FULL_EVENT_CATALOG = {
    "Agent Health": {
        "system_task.agent_missed_heartbeats_check": "event_agent_missed_heartbeats",
        "system_task.agent_offline_check": "event_agent_offline",
        "lost_agent.found": "event_lost_agent_found",
        "agent.service_not_available": "event_service_not_available",
        "agent.goodbye": "event_agent_goodbye"
    },
    "Agent Security": {
        "agent.tampering": "event_agent_tampering",
        "agent.suspend": "event_agent_suspend",
        "agent.clone_detected": "event_agent_clone_detected",
        "agent.activate": "event_agent_activate",
        "agent.deactivate": "event_agent_deactivate"
    },
    "User Access": {
        "user.authenticate": "event_user_authenticate",
        "user.sign_in": "event_user_sign_in",
        "user.sign_out": "event_user_sign_out",
        "user.logout": "event_user_logout",
        "user.login_session_terminated": "event_user_login_session_terminated",
        "user.pce_session_terminated": "event_user_pce_session_terminated",
        "user.create_session": "event_user_create_session",
        "user.login_failure_count_exceeded": "event_brute_force",
        "user.csrf_validation_failed": "event_csrf_failed"
    },
    "Agent Health Detail": {
        "agent.policy_deploy_failed": "event_policy_fail",
        "agent.missing_heartbeats_after_upgrade": "event_upgrade_health",
        "agent.refresh_policy": "agent.refresh_policy",
        "agent.fw_state_table_threshold_exceeded": "agent.fw_state_table_threshold_exceeded"
    },
    "Auth & API": {
        "request.authentication_failed": "event_api_auth_failed",
        "request.authorization_failed": "event_api_authz_failed",
        "api_key.create": "event_api_key_create",
        "api_key.delete": "event_api_key_delete"
    },
    "Policy": {
        "rule_set.delete": "event_ruleset_delete",
        "rule_set.create": "event_ruleset_create",
        "rule_set.update": "event_ruleset_update",
        "sec_rule.create": "event_rule_create",
        "sec_rule.delete": "event_rule_delete",
        "sec_policy.create": "event_policy_prov"
    },
    "Workloads": {
        "workload.create": "event_workload_create",
        "workload.delete": "event_workload_delete",
        "workload.online": "event_workload_online",
        "workload.recalc_rules": "event_workload_recalc_rules",
        "workload.redetect_network": "event_workload_redetect_network"
    },
    "System": {
        "pce.application_started": "event_pce_start",
        "cluster.update": "event_cluster_update"
    }
}

def add_event_menu(cm: ConfigManager, edit_rule=None):
    from src.utils import Colors, safe_input
    
    while True:
        os.system('cls' if os.name == 'nt' else 'clear')
        title = t('menu_add_event_title') if not edit_rule else f"=== Modify Event Rule: {edit_rule.get('name', '')} ==="
        print(f"{Colors.HEADER}{title}{Colors.ENDC}")
        print(t('menu_return'))
        if not edit_rule:
            hc = t('ssl_status_on') if cm.config["settings"].get("enable_health_check", True) else t('ssl_status_off')
            print(t('set_health_check', status=hc))
        print("-" * 40)
        cats = list(FULL_EVENT_CATALOG.keys())
        for i, c in enumerate(cats): print(f"{i+1}. {c}")
        sel = input(f"\n{t('select_category')}").strip().upper()
        if sel == '0': break
        if sel == 'H':
            cm.config["settings"]["enable_health_check"] = not cm.config["settings"].get("enable_health_check", True)
            cm.save()
            continue
        if not sel.isdigit() or not (1 <= int(sel) <= len(cats)): continue
        cat = cats[int(sel)-1]
        evts = FULL_EVENT_CATALOG[cat]
        evt_keys = list(evts.keys())
        print(f"\n--- {cat} ---")
        # Header for the list
        print(f"{'No.':<4} {'Event Type':<40} | {'Description'}")
        print("-" * 80)
        for i, k in enumerate(evt_keys): 
            desc = t(evts[k])
            print(f"{i+1:<4} {k:<40} | {desc}")
        
        print(f"\n{t('menu_cancel')}")
        if edit_rule and edit_rule.get('filter_value') in evt_keys:
            def_idx = evt_keys.index(edit_rule['filter_value']) + 1
            ei = safe_input(f"{t('select_event')} [{def_idx}]", int, range(0, len(evt_keys)+1), allow_cancel=True) or def_idx
        else:
            ei = safe_input(t('select_event'), int, range(0, len(evt_keys)+1))
            
        if not ei or ei == 0: continue
        k = evt_keys[ei-1]
        print(f"\n{t('selected')}: {k}")
        pmpt = f"{t('rule_trigger_type_1')}  {t('rule_trigger_type_2')}"
        def_ti = 1 if not edit_rule or edit_rule.get('threshold_type') == 'immediate' else 2
        ti = safe_input(pmpt, int, range(0, 3), allow_cancel=True, help_text=t('def_threshold_type'))
        if ti is None: continue
        if ti == '' or ti == 0: ti = def_ti
        ttype, cnt, win = "immediate", 1, 10
        if ti == 2:
            ttype = "count"
            def_cnt = edit_rule.get('threshold_count', 5) if edit_rule else 5
            def_win = edit_rule.get('threshold_window', 10) if edit_rule else 10
            cnt_in = safe_input(t('cumulative_count'), int, hint=str(def_cnt), allow_cancel=True)
            if cnt_in is None: continue
            cnt = int(cnt_in) if cnt_in != '' else def_cnt
            win_in = safe_input(t('time_window_mins'), int, hint=str(def_win), allow_cancel=True)
            if win_in is None: continue
            win = int(win_in) if win_in != '' else def_win
            
        def_cd = edit_rule.get('cooldown_minutes', win) if edit_rule else win
        cd_in = safe_input(t('cooldown_mins_default').replace('[{win}]', '').replace('[Default: {win}]', '').strip(), int, allow_cancel=True, hint=str(def_cd), help_text=t('def_cooldown'))
        cd = int(cd_in) if cd_in and cd_in != '' else def_cd
        rid = edit_rule.get('id', int(datetime.datetime.now().timestamp())) if edit_rule else int(datetime.datetime.now().timestamp())

        # New Status & Severity Filters
        print(f"\n{Colors.CYAN}--- {t('advanced_filters')} ---{Colors.ENDC}")
        def_status = edit_rule.get('filter_status', 'all') if edit_rule else 'all'
        s_map = {1: 'success', 2: 'failure', 0: 'all'}
        s_inv = {v: k for k, v in s_map.items()}
        si = safe_input(t('filter_status').replace('[預設: 0]', '').replace('[Default: 0]', '').strip(), int, range(0, 3), allow_cancel=True, hint=str(s_inv.get(def_status, 0)), help_text=t('def_filters'))
        if si is None: break
        if si == '': si = s_inv.get(def_status, 0)
        sel_status = s_map.get(si, def_status)
        
        def_sev = edit_rule.get('filter_severity', 'all') if edit_rule else 'all'
        v_map = {1: 'error', 2: 'warning', 3: 'info', 0: 'all'}
        v_inv = {v: k for k, v in v_map.items()}
        vi = safe_input(t('filter_severity').replace('[預設: 0]', '').replace('[Default: 0]', '').strip(), int, range(0, 4), allow_cancel=True, hint=str(v_inv.get(def_sev, 0)), help_text=t('def_filters'))
        if vi is None: break
        if vi == '': vi = v_inv.get(def_sev, 0)
        sel_sev = v_map.get(vi, def_sev)

        cm.add_or_update_rule({
            "id": rid,
            "type": "event", "name": t(evts[k]), "filter_key": "event_type", "filter_value": k,
            "filter_status": sel_status, "filter_severity": sel_sev,
            "desc": t(evts[k]), "rec": "Check Logs", "threshold_type": ttype, "threshold_count": cnt, 
            "threshold_window": win, "cooldown_minutes": cd
        })
        input(t('rule_saved'))
        break

def add_traffic_menu(cm: ConfigManager, edit_rule=None):
    from src.utils import Colors, safe_input
    
    title = t('menu_add_traffic_title') if not edit_rule else f"=== Modify Traffic Rule: {edit_rule.get('name', '')} ==="
    print(f"\n{Colors.HEADER}{title}{Colors.ENDC}")
    print(t('menu_return'))
    
    def_name = edit_rule.get('name', '') if edit_rule else ''
    name = safe_input(t('rule_name'), str, allow_cancel=True, hint=def_name)
    if name is None: return 
    if name == '': name = def_name
    if not name: return
    
    def_pd = 1
    if edit_rule:
        tpd = edit_rule.get('pd', 2)
        if tpd == 2: def_pd = 1    # Blocked
        elif tpd == 0: def_pd = 2  # Potential
        elif tpd == 1: def_pd = 3  # Allowed
        elif tpd == -1: def_pd = 4 # All

    pd_sel = safe_input(t('pd_select_default'), int, range(0, 5), allow_cancel=True, hint=str(def_pd), help_text=t('def_traffic_pd'))
    if pd_sel is None: return
    if pd_sel == '': pd_sel = def_pd
    
    # 選單對應: 1=Blocked(pd=2), 2=Potential(pd=0), 3=Allowed(pd=1), 4=All(pd=-1)
    if pd_sel == 1: target_pd = 2
    elif pd_sel == 2: target_pd = 0
    elif pd_sel == 3: target_pd = 1
    else: target_pd = -1
    
    print(f"\n{Colors.CYAN}{t('advanced_filters')}{Colors.ENDC}")
    
    def_port = edit_rule.get('port', '') if edit_rule else ''
    port_in = safe_input(t('port_input'), int, allow_cancel=True, hint=str(def_port) if def_port else '')
    if port_in is None: return
    if port_in == '': port_in = (int(def_port) if def_port else None)
    
    proto_in = None
    if port_in:
        def_proto = 0
        if edit_rule and edit_rule.get('proto') == 6: def_proto = 1
        elif edit_rule and edit_rule.get('proto') == 17: def_proto = 2
        p_sel = safe_input(t('proto_select'), int, range(0, 3), allow_cancel=True, hint=str(def_proto))
        if p_sel is None: return
        if p_sel == '': p_sel = def_proto
        
        if p_sel == 1: proto_in = 6
        elif p_sel == 2: proto_in = 17
        
    def_src = edit_rule.get('src_label', edit_rule.get('src_ip_in', '')) if edit_rule else ''
    src_in = safe_input(t('src_input'), str, allow_cancel=True, hint=def_src)
    if src_in is None: return
    
    def_dst = edit_rule.get('dst_label', edit_rule.get('dst_ip_in', '')) if edit_rule else ''
    dst_in = safe_input(t('dst_input'), str, allow_cancel=True, hint=def_dst)
    if dst_in is None: return
    if dst_in == '': dst_in = def_dst
    
    def_win = edit_rule.get('threshold_window', 10) if edit_rule else 10
    win_in = safe_input(t('time_window_mins_default_5').replace('[{win}]', '').replace('[Default: 5]', '').strip(), int, allow_cancel=True, hint=str(def_win))
    if win_in is None: return
    win = int(win_in) if win_in != '' else def_win
    
    def_cnt = edit_rule.get('threshold_count', 10) if edit_rule else 10
    cnt_in = safe_input(t('trigger_threshold_count'), int, allow_cancel=True, hint=str(def_cnt))
    if cnt_in is None: return
    cnt = int(cnt_in) if cnt_in != '' else def_cnt
    
    def_cd = edit_rule.get('cooldown_minutes', win) if edit_rule else win
    cd_in = safe_input(t('cooldown_mins_default').replace('[{win}]', '').replace('[Default: {win}]', '').strip(), int, allow_cancel=True, hint=str(def_cd), help_text=t('def_cooldown'))
    if cd_in is None: return
    cd = int(cd_in) if cd_in != '' else def_cd
    
    src_label_val, src_ip_val = (src_in, None) if src_in and '=' in src_in else (None, src_in)
    dst_label_val, dst_ip_val = (dst_in, None) if dst_in and '=' in dst_in else (None, dst_in)
    
    print(f"\n{Colors.CYAN}{t('excludes_optional')}{Colors.ENDC}")
    def_ex_port = edit_rule.get('ex_port', '') if edit_rule else ''
    ex_port_in = safe_input(t('ex_port_input'), int, allow_cancel=True, hint=str(def_ex_port))
    if ex_port_in is None: return
    
    def_ex_src = edit_rule.get('ex_src_label', edit_rule.get('ex_src_ip', '')) if edit_rule else ''
    ex_src_in = safe_input(t('ex_src_input'), str, allow_cancel=True, hint=def_ex_src)
    if ex_src_in is None: return
    
    def_ex_dst = edit_rule.get('ex_dst_label', edit_rule.get('ex_dst_ip', '')) if edit_rule else ''
    ex_dst_in = safe_input(t('ex_dst_input'), str, allow_cancel=True, hint=def_ex_dst)
    if ex_dst_in is None: return
    
    ex_src_label_val, ex_src_ip_val = (ex_src_in, None) if ex_src_in and '=' in ex_src_in else (None, ex_src_in)
    ex_dst_label_val, ex_dst_ip_val = (ex_dst_in, None) if ex_dst_in and '=' in ex_dst_in else (None, ex_dst_in)
    
    rid = edit_rule.get('id', int(datetime.datetime.now().timestamp())) if edit_rule else int(datetime.datetime.now().timestamp())
    
    cm.add_or_update_rule({
        "id": rid,
        "type": "traffic", "name": name, "pd": target_pd,
        "port": port_in, "proto": proto_in, 
        "src_label": src_label_val, "dst_label": dst_label_val,
        "src_ip_in": src_ip_val, "dst_ip_in": dst_ip_val,
        "ex_port": ex_port_in,
        "ex_src_label": ex_src_label_val, "ex_dst_label": ex_dst_label_val,
        "ex_src_ip": ex_src_ip_val, "ex_dst_ip": ex_dst_ip_val,
        "desc": name, "rec": "Check Policy", "threshold_type": "count", "threshold_count": cnt, 
        "threshold_window": win, "cooldown_minutes": cd
    })
    input(t('traffic_rule_saved'))

def add_bandwidth_volume_menu(cm: ConfigManager, edit_rule=None):
    from src.utils import Colors, safe_input
    
    title = t('menu_add_bw_vol_title') if not edit_rule else f"=== Modify Rule: {edit_rule.get('name', '')} ==="
    print(f"\n{Colors.HEADER}{title}{Colors.ENDC}")
    print(t('menu_return'))
    
    def_name = edit_rule.get('name', '') if edit_rule else ''
    name = safe_input(t('rule_name_bw'), str, allow_cancel=True, hint=def_name)
    if name is None: return
    if name == '': name = def_name
    if not name: return
    
    print(f"\n{Colors.CYAN}{t('step_1_metric')}{Colors.ENDC}")
    print(t('metric_1'))
    print(t('metric_2'))
    
    def_msel = 1 if edit_rule and edit_rule.get('type') == 'bandwidth' else (2 if edit_rule else None)
    m_sel = safe_input(t('please_select'), int, range(0, 3), allow_cancel=True, hint=str(def_msel))
    if m_sel is None: return
    if m_sel == '' and def_msel: m_sel = def_msel
    if not m_sel or m_sel not in (1, 2): return
    
    rtype = "bandwidth" if m_sel == 1 else "volume"
    unit_prompt = "Mbps" if m_sel == 1 else "MB"
    
    print(f"\n{Colors.CYAN}{t('step_2_filters')}{Colors.ENDC}")
    
    def_port = edit_rule.get('port', '') if edit_rule else ''
    port_in = safe_input(t('port_input'), int, allow_cancel=True, hint=str(def_port) if def_port else '')
    if port_in is None: return
    if port_in == '': port_in = (int(def_port) if def_port else None)
    
    proto_in = None
    if port_in:
        def_proto = 0
        if edit_rule and edit_rule.get('proto') == 6: def_proto = 1
        elif edit_rule and edit_rule.get('proto') == 17: def_proto = 2
        p_sel = safe_input(t('proto_select'), int, range(0, 3), allow_cancel=True, hint=str(def_proto))
        if p_sel is None: return
        if p_sel == 1: proto_in = 6
        elif p_sel == 2: proto_in = 17
        elif p_sel == '': proto_in = (edit_rule.get('proto') if edit_rule else None)
        
    def_src = edit_rule.get('src_label', edit_rule.get('src_ip_in', '')) if edit_rule else ''
    src_in = safe_input(t('src_input'), str, allow_cancel=True, hint=def_src)
    if src_in is None: return
    
    def_dst = edit_rule.get('dst_label', edit_rule.get('dst_ip_in', '')) if edit_rule else ''
    dst_in = safe_input(t('dst_input'), str, allow_cancel=True, hint=def_dst)
    if dst_in is None: return
    
    src_label_val, src_ip_val = (src_in, None) if src_in and '=' in src_in else (None, src_in)
    dst_label_val, dst_ip_val = (dst_in, None) if dst_in and '=' in dst_in else (None, dst_in)
    
    print(f"\n{Colors.CYAN}{t('step_3_threshold')}{Colors.ENDC}")
    def_th = edit_rule.get('threshold_count', '') if edit_rule else ''
    th_in = safe_input(t('trigger_threshold_unit', unit=unit_prompt), float, allow_cancel=True, hint=str(def_th) if def_th else '', help_text=t('def_traffic_vol'))
    if th_in is None: return
    th = float(th_in) if th_in != '' else (float(def_th) if def_th != '' else None)
    if th is None: return
    
    def_win = edit_rule.get('threshold_window', 5) if edit_rule else 5
    win_in = safe_input(t('time_window_mins_default_5').replace('[{win}]', '').replace('[Default: 5]', '').strip(), int, allow_cancel=True, hint=str(def_win))
    if win_in is None: return
    win = int(win_in) if win_in != '' else def_win
    
    def_cd = edit_rule.get('cooldown_minutes', win) if edit_rule else win
    cd_in = safe_input(t('cooldown_mins_default').replace('[{win}]', '').replace('[Default: {win}]', '').strip(), int, allow_cancel=True, hint=str(def_cd), help_text=t('def_cooldown'))
    if cd_in is None: return
    cd = int(cd_in) if cd_in != '' else def_cd
    
    print(f"\n{Colors.CYAN}{t('excludes_optional')}{Colors.ENDC}")
    def_ex_port = edit_rule.get('ex_port', '') if edit_rule else ''
    ex_port_in = safe_input(t('ex_port_input'), int, allow_cancel=True, hint=str(def_ex_port))
    if ex_port_in is None: return
    
    def_ex_src = edit_rule.get('ex_src_label', edit_rule.get('ex_src_ip', '')) if edit_rule else ''
    ex_src_in = safe_input(t('ex_src_input'), str, allow_cancel=True, hint=def_ex_src)
    if ex_src_in is None: return
    
    def_ex_dst = edit_rule.get('ex_dst_label', edit_rule.get('ex_dst_ip', '')) if edit_rule else ''
    ex_dst_in = safe_input(t('ex_dst_input'), str, allow_cancel=True, hint=def_ex_dst)
    if ex_dst_in is None: return
    
    ex_src_label_val, ex_src_ip_val = (ex_src_in, None) if ex_src_in and '=' in ex_src_in else (None, ex_src_in)
    ex_dst_label_val, ex_dst_ip_val = (ex_dst_in, None) if ex_dst_in and '=' in ex_dst_in else (None, ex_dst_in)
    
    rid = edit_rule.get('id', int(datetime.datetime.now().timestamp())) if edit_rule else int(datetime.datetime.now().timestamp())
    
    cm.add_or_update_rule({
        "id": rid,
        "type": rtype, "name": name, "pd": edit_rule.get('pd', -1) if edit_rule else -1,
        "port": port_in, "proto": proto_in, 
        "src_label": src_label_val, "dst_label": dst_label_val,
        "src_ip_in": src_ip_val, "dst_ip_in": dst_ip_val,
        "ex_port": ex_port_in,
        "ex_src_label": ex_src_label_val, "ex_dst_label": ex_dst_label_val,
        "ex_src_ip": ex_src_ip_val, "ex_dst_ip": ex_dst_ip_val,
        "threshold_type": "immediate", 
        "threshold_count": th, 
        "threshold_window": win, "cooldown_minutes": cd,
        "desc": f"Alert when {rtype} > {th} {unit_prompt}", "rec": "Check network activity"
    })
    input(t('rule_saved'))

def manage_rules_menu(cm: ConfigManager):
    while True:
        os.system('cls' if os.name == 'nt' else 'clear')
        print(f"{Colors.HEADER}{t('menu_manage_rules_title')}{Colors.ENDC}")
        print(f"{'No.':<4} {'Name':<30} {'Type':<10} {'Condition':<20} {'Filters / Excludes'}")
        print("-" * 100)
        if not cm.config['rules']: print(t('no_rules'))
        for i, r in enumerate(cm.config['rules']):
            rtype = r['type'].capitalize()
            val = r['threshold_count']
            if r['type'] == 'volume': val = f"{val} MB" 
            elif r['type'] == 'bandwidth': val = f"{val} Mbps"
            elif r['type'] == 'traffic': val = f"{val} ({t('table_num_conns')})"
            cond = f"> {val} (Win: {r.get('threshold_window')}m)"
            cd = r.get("cooldown_minutes", r.get("threshold_window", 10))
            cond += f" (CD:{cd}m)"
            filters = []
            if r['type'] == 'traffic':
                pd_map = {2: t('decision_blocked'), 1: t('decision_potential'), 0: t('decision_allowed'), -1: t('pd_4')}
                filters.append(f"[{pd_map.get(r.get('pd', 2), '?')}]")
            if r.get('port'):
                proto_str = "/TCP" if r.get('proto')==6 else "/UDP" if r.get('proto')==17 else ""
                filters.append(f"[Port:{r['port']}{proto_str}]")
            if r.get('src_label'): filters.append(f"[Src:{r['src_label']}]")
            if r.get('dst_label'): filters.append(f"[Dst:{r['dst_label']}]")
            if r.get('src_ip_in'): filters.append(f"[SrcIP:{r['src_ip_in']}]")
            if r.get('dst_ip_in'): filters.append(f"[DstIP:{r['dst_ip_in']}]")
            if r.get('ex_port'): filters.append(f"{Colors.WARNING}[Excl Port:{r['ex_port']}]{Colors.ENDC}")
            if r.get('ex_src_label'): filters.append(f"{Colors.WARNING}[Excl Src:{r['ex_src_label']}]{Colors.ENDC}")
            if r.get('ex_dst_label'): filters.append(f"{Colors.WARNING}[Excl Dst:{r['ex_dst_label']}]{Colors.ENDC}")
            if r.get('ex_src_ip'): filters.append(f"{Colors.WARNING}[Excl SrcIP:{r['ex_src_ip']}]{Colors.ENDC}")
            if r.get('ex_dst_ip'): filters.append(f"{Colors.WARNING}[Excl DstIP:{r['ex_dst_ip']}]{Colors.ENDC}")
            filter_str = " ".join(filters)
            
            from src.utils import pad_string
            # Truncate string gracefully if it's too long
            display_name = r['name']
            from src.utils import get_display_width
            if get_display_width(display_name) > 28:
                # Rough truncation for mixed width
                display_name = display_name[:25] + "..."
                
            padded_name = pad_string(display_name, 30)
            padded_type = pad_string(rtype, 10)
            print(f"{i:<4} {padded_name} {padded_type} {cond:<20} {filter_str}")
        val = input(f"\n{t('input_delete_indices')}").strip().lower()
        if val == '0' or not val: break
        
        if val.startswith('d ') or (val.startswith('d') and len(val) > 1 and val[1].isdigit()):
            # Handle both 'd 0, 1' and 'd0, 1'
            target = val[1:].strip()
            if target.startswith('d'): target = target[1:].strip()
            try:
                indices = [int(x.strip()) for x in target.split(',')]
                cm.remove_rules_by_index(indices)
                print(t('done'))
            except Exception as e:
                print(f"Error deleting: {e}")
        elif val.startswith('m ') or (val.startswith('m') and len(val) > 1 and val[1].isdigit()):
            target = val[1:].strip()
            if target.startswith('m'): target = target[1:].strip()
            try:
                idx = int(target)
                if 0 <= idx < len(cm.config['rules']):
                    rule = cm.config['rules'][idx]
                    print(f"\n{Colors.CYAN}--- Modifying Rule: {rule['name']} ---{Colors.ENDC}")
                    rtype = rule['type']
                    cm.remove_rules_by_index([idx])
                    if rtype == 'event':
                        add_event_menu(cm, edit_rule=rule)
                    elif rtype == 'traffic':
                        add_traffic_menu(cm, edit_rule=rule)
                    elif rtype in ['bandwidth', 'volume']:
                        add_bandwidth_volume_menu(cm, edit_rule=rule)
            except Exception as e:
                print(f"Error modifying: {e}")
        else:
            print(f"{Colors.FAIL}{t('error_format', default='Invalid format.')}{Colors.ENDC}")
            
        input(t('press_enter_to_continue'))


def alert_settings_menu(cm: ConfigManager):
    while True:
        os.system('cls' if os.name == 'nt' else 'clear')
        print(f"{Colors.HEADER}{t('settings_alert_title')}{Colors.ENDC}")
        
        current_lang = cm.config.get("settings", {}).get("language", "en")
        active_alerts = cm.config.get("alerts", {}).get("active", ["mail"])
        
        mail_status = t('ssl_status_on') if 'mail' in active_alerts else t('ssl_status_off')
        line_status = t('ssl_status_on') if 'line' in active_alerts else t('ssl_status_off')
        webhook_status = t('ssl_status_on') if 'webhook' in active_alerts else t('ssl_status_off')
        
        print(t('change_language', lang=current_lang))
        print(t('toggle_mail_alert', status=mail_status))
        print(t('toggle_line_alert', status=line_status))
        print(t('toggle_webhook_alert', status=webhook_status))
        print(t('edit_line_channel_access_token'))
        print(t('edit_line_target_id'))
        print(t('edit_webhook_url'))
        print(t('menu_return'))
        
        sel = safe_input(f"\n{t('please_select')}", int, range(0, 8))
        if sel is None: break
        
        if sel == 1:
            lang_sel = safe_input(t('select_language'), int, range(1, 3))
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
            current_token = cm.config.get("alerts", {}).get("line_channel_access_token", "")
            masked = current_token[:5] + "..." if current_token else t('not_set')
            new_token = safe_input(t('line_token_input'), str, allow_cancel=True, hint=masked)
            if new_token:
                cm.config.setdefault("alerts", {})["line_channel_access_token"] = new_token
                cm.save()
                
        elif sel == 6:
            current_id = cm.config.get("alerts", {}).get("line_target_id", "")
            masked_id = current_id[:5] + "..." if current_id else t('not_set')
            new_id = safe_input(t('line_target_id_input'), str, allow_cancel=True, hint=masked_id)
            if new_id:
                cm.config.setdefault("alerts", {})["line_target_id"] = new_id
                cm.save()
                
        elif sel == 7:
            current_url = cm.config.get("alerts", {}).get("webhook_url", "")
            masked = current_url[:15] + "..." if current_url else t('not_set')
            new_url = safe_input(t('webhook_url_input'), str, allow_cancel=True, hint=masked)
            if new_url:
                cm.config.setdefault("alerts", {})["webhook_url"] = new_url
                cm.save()

def settings_menu(cm: ConfigManager):
    while True:
        os.system('cls' if os.name == 'nt' else 'clear')
        print(f"{Colors.HEADER}{t('menu_settings_title', version=__version__)}{Colors.ENDC}")
        masked_key = cm.config['api']['key'][:5] + "..." if cm.config['api']['key'] else t('not_set')
        print(f"API URL : {cm.config['api']['url']}")
        print(f"API Key : {masked_key}")
        
        alerts_cfg = cm.config.get('alerts', {})
        active = alerts_cfg.get('active', ['mail'])
        channels = []
        if 'mail' in active: channels.append(f"Mail ({cm.config['email']['sender']})")
        if 'line' in active: channels.append("LINE")
        if 'webhook' in active: channels.append("Webhook")
        
        print(f"Alerts  : {', '.join(channels) if channels else t('not_set')}")
        print("-" * 40)
        print(t('settings_1'))
        print(t('settings_2'))
        ssl_status = t('ssl_verify') if cm.config['api'].get('verify_ssl', True) else t('ssl_ignore')
        print(t('settings_3', status=ssl_status))
        smtp_conf = cm.config.get('smtp', {})
        auth_status = f"Auth:{t('ssl_status_on') if smtp_conf.get('enable_auth') else t('ssl_status_off')}"
        print(f"{t('settings_4')} ({smtp_conf.get('host')}:{smtp_conf.get('port')} | {auth_status})")
        print(t('menu_return'))
        sel = safe_input(f"\n{t('please_select')}", int, range(0, 5))
        if sel is None: break
        if sel == 1:
            new_url = safe_input("API URL", str, allow_cancel=True, hint=cm.config['api']['url'])
            if new_url: cm.config['api']['url'] = new_url.strip('"').strip("'")
            
            cm.config['api']['org_id'] = safe_input("Org ID", str, allow_cancel=True, hint=cm.config['api']['org_id']) or cm.config['api']['org_id']
            cm.config['api']['key'] = safe_input("API Key", str, allow_cancel=True, hint=masked_key) or cm.config['api']['key']
            new_sec = safe_input("API Secret", str, allow_cancel=True, hint="******")
            if new_sec: cm.config['api']['secret'] = new_sec
            cm.save()
        elif sel == 2:
            alert_settings_menu(cm)
        elif sel == 3:
            current = cm.config['api'].get('verify_ssl', True)
            print(f"{t('settings_3', status=t('ssl_status_on') if current else t('ssl_status_off'))}")
            choice = safe_input(t('change_verify_to'), int, range(1, 3))
            if choice:
                cm.config['api']['verify_ssl'] = (choice == 1)
                cm.save()
        elif sel == 4:
            c = cm.config.get('smtp', {})
            print(f"\n{Colors.CYAN}{t('setup_smtp')}{Colors.ENDC}")
            c['host'] = safe_input("SMTP Host", str, allow_cancel=True, hint=c.get('host','localhost')) or c.get('host','localhost')
            c['port'] = safe_input("SMTP Port", int, allow_cancel=True, hint=str(c.get('port', 25))) or c.get('port', 25)
            
            enable_tls = safe_input(t('enable_starttls', status=c.get('enable_tls', False)), str, allow_cancel=True)
            if enable_tls and enable_tls.lower() == 'y': c['enable_tls'] = True
            elif enable_tls and enable_tls.lower() == 'n': c['enable_tls'] = False
            
            enable_auth = safe_input(t('enable_auth', status=c.get('enable_auth', False)), str, allow_cancel=True)
            if enable_auth and enable_auth.lower() == 'y': c['enable_auth'] = True
            elif enable_auth and enable_auth.lower() == 'n': c['enable_auth'] = False
            
            if c['enable_auth']:
                c['user'] = safe_input("Username", str, allow_cancel=True, hint=c.get('user','')) or c.get('user','')
                new_pass = safe_input("Password", str, allow_cancel=True, hint="******")
                if new_pass: c['password'] = new_pass
            
            cm.config['smtp'] = c
            cm.save()
