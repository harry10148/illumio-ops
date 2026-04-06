"""
Rule Scheduler CLI — Interactive interface for managing rule schedules.
Ported from illumio_Rule-Scheduler/src/cli_ui.py, adapted for illumio_ops.
"""
import datetime
import traceback
from src.utils import Colors
from src.i18n import t
from src.rule_scheduler import ScheduleDB, ScheduleEngine, truncate, extract_id

# ─── Helpers ─────────────────────────────────────────────────────────────────


def clean_input(text):
    """Process raw input, stripping control characters."""
    if not text:
        return ""
    chars = []
    for char in text:
        if char in ('\x08', '\x7f'):
            if chars:
                chars.pop()
        elif ord(char) >= 32 or char == '\t':
            chars.append(char)
    return "".join(chars).strip()


def get_valid_time(prompt):
    """Prompt for HH:MM time, returns string or None on cancel."""
    while True:
        raw = clean_input(input(prompt))
        if raw.lower() in ['q', 'b']:
            return None
        try:
            datetime.datetime.strptime(raw, "%H:%M")
            return raw
        except ValueError:
            print(f"{Colors.FAIL}[-] {t('rs_sch_time_error')}{Colors.ENDC}")


def paginate_and_select(items, format_func, title="", header_str=""):
    """Paginated list with selection. Returns selected item or None."""
    PAGE_SIZE = 50
    total = len(items)
    if total == 0:
        print(f"{Colors.WARNING}[-] {t('rs_list_no_schedule')}{Colors.ENDC}")
        return None

    page = 0
    while True:
        start = page * PAGE_SIZE
        end = start + PAGE_SIZE
        current_batch = items[start:end]

        print(f"\n{Colors.HEADER}--- {title} ({start+1}-{min(end, total)} / {total}) ---{Colors.ENDC}")
        if header_str:
            print(f"{Colors.BOLD}{header_str}{Colors.ENDC}")
            print("-" * 120)
        else:
            print("-" * 80)

        for i, item in enumerate(current_batch):
            real_idx = start + i + 1
            print(format_func(real_idx, item))
        print("-" * 120 if header_str else "-" * 80)

        prompt = t('rs_select_prompt')
        opts = []
        if end < total:
            opts.append(f"(n){t('rs_next_page')}")
        if page > 0:
            opts.append(f"(p){t('rs_prev_page')}")
        opts.append(f"(q){t('rs_back')}")

        ans = clean_input(input(f"{Colors.CYAN}❯{Colors.ENDC} {prompt} [{' '.join(opts)}]: ")).lower()

        if ans in ['q', 'b', '0']:
            return None
        elif ans == 'n' and end < total:
            page += 1
        elif ans == 'p' and page > 0:
            page -= 1
        elif ans.isdigit():
            idx = int(ans) - 1
            if 0 <= idx < total:
                return items[idx]
            else:
                print(f"{Colors.FAIL}[-] {t('rs_invalid_number')}{Colors.ENDC}")
        else:
            print(f"{Colors.FAIL}[-] {t('rs_invalid_input')}{Colors.ENDC}")


# ─── Main Entry Point ────────────────────────────────────────────────────────


def rule_scheduler_menu(cm):
    """Main entry point for the Rule Scheduler CLI, called from main menu."""
    import os
    from src.api_client import ApiClient

    PKG_DIR = os.path.dirname(os.path.abspath(__file__))
    ROOT_DIR = os.path.dirname(PKG_DIR)
    db_path = os.path.join(ROOT_DIR, "config", "rule_schedules.json")

    db = ScheduleDB(db_path)
    db.load()
    api = ApiClient(cm)
    engine = ScheduleEngine(db, api)

    print(f"\n{Colors.BLUE}[*] {t('rs_browse_loading', default='Loading label cache...')}{Colors.ENDC}")
    api.update_label_cache(silent=True)

    cli = _RuleSchedulerCLI(db, api, engine, cm)
    cli.run()


class _RuleSchedulerCLI:
    """Internal CLI class for rule scheduler operations."""

    def __init__(self, db, api, engine, cm):
        self.db = db
        self.api = api
        self.engine = engine
        self.cm = cm

    # ── Formatters ──

    def format_ruleset_row(self, idx, rs):
        r_count = len(rs.get('rules', []))

        is_en = rs.get('enabled')
        st_text = "✔ ON" if is_en else "✖ OFF"
        st_pad = f"{st_text:<8}"
        status = f"{Colors.GREEN}{st_pad}{Colors.ENDC}" if is_en else f"{Colors.FAIL}{st_pad}{Colors.ENDC}"

        rid = f"{Colors.CYAN}{extract_id(rs['href']):<6}{Colors.ENDC}"
        name = truncate(rs['name'], 40)

        ut = rs.get('update_type')
        prov_text = "DRAFT" if ut else "ACTIVE"
        prov_pad = f"{prov_text:<6}"
        prov_state = f"{Colors.WARNING}{prov_pad}{Colors.ENDC}" if ut else f"{Colors.GREEN}{prov_pad}{Colors.ENDC}"

        sType = self.db.get_schedule_type(rs)
        if sType == 1:
            mark = f"{Colors.WARNING}★{Colors.ENDC}"
        elif sType == 2:
            mark = f"{Colors.CYAN}●{Colors.ENDC}"
        else:
            mark = " "

        return f"{idx:<4} │ {mark} │ {rid} │ {prov_state} │ {status} │ Rules:{str(r_count):<4} │ {name}"

    def format_rule_row(self, idx, r):
        rid = f"{Colors.CYAN}{extract_id(r['href']):<6}{Colors.ENDC}"
        raw_desc = r.get('description') or ""
        note = truncate(raw_desc, 30)

        is_en = r.get('enabled')
        st_text = "✔ ON" if is_en else "✖ OFF"
        st_pad = f"{st_text:<8}"
        status = f"{Colors.GREEN}{st_pad}{Colors.ENDC}" if is_en else f"{Colors.FAIL}{st_pad}{Colors.ENDC}"

        dest_field = r.get('destinations', r.get('consumers', []))
        src = truncate(self.api.resolve_actor_str(dest_field), 15)
        dst = truncate(self.api.resolve_actor_str(r.get('providers', [])), 15)
        svc = truncate(self.api.resolve_service_str(r.get('ingress_services', [])), 10)

        ut = r.get('update_type')
        prov_text = "DRAFT" if ut else "ACTIVE"
        prov_pad = f"{prov_text:<6}"
        prov_state = f"{Colors.WARNING}{prov_pad}{Colors.ENDC}" if ut else f"{Colors.GREEN}{prov_pad}{Colors.ENDC}"

        is_sched = r['href'] in self.db.get_all()
        mark = f"{Colors.WARNING}★{Colors.ENDC}" if is_sched else " "

        return f"{idx:<4} │ {mark} │ {rid} │ {prov_state} │ {status} │ {note:<30} │ {src:<15} │ {dst:<15} │ {svc}"

    # ── Schedule Management (unified view) ──

    def schedule_management_ui(self):
        while True:
            self._list_grouped()

            print(f"\n{Colors.HEADER}╭── {Colors.BOLD}Commands{Colors.ENDC}")
            print(f"{Colors.HEADER}│{Colors.ENDC} {Colors.BOLD}{t('rs_sch_hint')}{Colors.ENDC}: {Colors.WARNING}★{Colors.ENDC}={t('rs_sch_hint_rs')}, {Colors.CYAN}●{Colors.ENDC}={t('rs_sch_hint_child')}")
            print(f"{Colors.HEADER}│{Colors.ENDC} {Colors.GREEN}a{Colors.ENDC}={t('rs_sch_browse')}  |  {Colors.CYAN}e <ID>{Colors.ENDC}={t('rs_sch_edit')}  |  {Colors.FAIL}d <ID,ID,...>{Colors.ENDC}={t('rs_sch_delete')}")
            print(f"{Colors.HEADER}│{Colors.ENDC} {Colors.CYAN}r{Colors.ENDC}=Refresh  |  {Colors.CYAN}q{Colors.ENDC}={t('rs_sch_back')}")
            print(f"{Colors.HEADER}╰{'─' * 40}{Colors.ENDC}")

            ans = clean_input(input(f"{Colors.CYAN}❯{Colors.ENDC} ")).strip()
            if ans.lower() in ['q', 'b', '']:
                return

            try:
                if ans.lower() == 'a':
                    self._browse_and_add()
                elif ans.lower() == 'r':
                    continue
                elif ans.lower().startswith('e '):
                    edit_id = ans[2:].strip()
                    if edit_id:
                        self._edit_by_id(edit_id)
                elif ans.lower().startswith('d '):
                    ids_str = ans[2:].strip()
                    if ids_str:
                        self._delete_by_ids(ids_str)
                else:
                    if ans.isdigit():
                        self._edit_by_id(ans)
                    else:
                        print(f"{Colors.FAIL}[-] {t('rs_invalid_input')}{Colors.ENDC}")
            except Exception as e:
                print(f"{Colors.FAIL}[ERROR] {e}{Colors.ENDC}")
                traceback.print_exc()

    # ── Collect Schedule Parameters ──

    def _collect_schedule_params(self, target_name, is_rs, meta_rs, meta_src, meta_dst, meta_svc, existing=None):
        print(f"\n[{t('rs_sch_target')}] {Colors.BOLD}{target_name}{Colors.ENDC}")
        print(f"1. {Colors.GREEN}{t('rs_sch_type_recurring')}{Colors.ENDC}")
        print(f"2. {Colors.FAIL}{t('rs_sch_type_expire')}{Colors.ENDC}")

        default_mode = ""
        if existing:
            default_mode = "1" if existing.get('type') == 'recurring' else "2"
            curr_type = t('rs_sch_type_recurring') if default_mode == '1' else t('rs_sch_type_expire')
            print(f"{Colors.DARK_GRAY}({t('rs_sch_current')}: {curr_type}){Colors.ENDC}")

        mode_sel = clean_input(input(f"{t('rs_select_prompt')} (q={t('rs_back')}) > "))
        if mode_sel.lower() in ['q', 'b']:
            return None, None
        if not mode_sel and default_mode:
            mode_sel = default_mode

        if mode_sel == '1':
            print(f"\n[{t('rs_sch_action_label')}] 1.{Colors.GREEN}{t('rs_sch_action_enable')}{Colors.ENDC} / 2.{Colors.FAIL}{t('rs_sch_action_disable')}{Colors.ENDC}")
            default_act = ""
            if existing and existing.get('type') == 'recurring':
                default_act = "2" if existing.get('action') == 'block' else "1"
                print(f"{Colors.DARK_GRAY}({t('rs_sch_current')}: {'2' if default_act == '2' else '1'}){Colors.ENDC}")

            act_in = clean_input(input(">> "))
            if act_in.lower() in ['q', 'b']:
                return None, None
            if not act_in and default_act:
                act_in = default_act
            act = 'block' if act_in == '2' else 'allow'

            default_days = ""
            if existing and existing.get('type') == 'recurring':
                default_days = ",".join(existing.get('days', []))
            print(f"[{t('rs_sch_days_prompt')}]")
            if default_days:
                print(f"{Colors.DARK_GRAY}({t('rs_sch_current')}: {default_days}){Colors.ENDC}")
            raw_days = clean_input(input(">> "))
            if raw_days.lower() in ['q', 'b']:
                return None, None
            if not raw_days and default_days:
                raw_days = default_days
            days = [d.strip() for d in raw_days.split(',')] if raw_days else [
                "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"
            ]
            days_str = t('rs_action_everyday') if not raw_days else raw_days

            default_start = existing.get('start', '') if existing and existing.get('type') == 'recurring' else ''
            default_end = existing.get('end', '') if existing and existing.get('type') == 'recurring' else ''

            prompt_s = t('rs_sch_start_prompt')
            if default_start:
                prompt_s += f" ({t('rs_sch_current')}: {default_start})"
            prompt_s += f" {t('rs_sch_time_format_hint')} "
            s_time = clean_input(input(prompt_s))
            if s_time.lower() in ['q', 'b']:
                return None, None
            if not s_time and default_start:
                s_time = default_start

            prompt_e = t('rs_sch_end_prompt')
            if default_end:
                prompt_e += f" ({t('rs_sch_current')}: {default_end})"
            prompt_e += f" {t('rs_sch_time_format_hint')} "
            e_time = clean_input(input(prompt_e))
            if e_time.lower() in ['q', 'b']:
                return None, None
            if not e_time and default_end:
                e_time = default_end

            try:
                t1 = datetime.datetime.strptime(s_time, "%H:%M")
                t2 = datetime.datetime.strptime(e_time, "%H:%M")
                if t1 >= t2:
                    raise ValueError
            except ValueError:
                print(f"{Colors.FAIL}[-] {t('rs_sch_time_invalid')}{Colors.ENDC}")
                return None, None

            act_str = t('rs_action_enable_in_window') if act == 'allow' else t('rs_action_disable_in_window')
            db_entry = {
                "type": "recurring", "name": target_name, "is_ruleset": is_rs,
                "action": act, "days": days, "start": s_time, "end": e_time,
                "detail_rs": meta_rs, "detail_src": meta_src, "detail_dst": meta_dst, "detail_svc": meta_svc,
                "detail_name": target_name
            }
            note_msg = f"[📅 {t('rs_sch_tag_recurring')}: {days_str} {s_time}-{e_time} {act_str}]"
            return db_entry, note_msg

        elif mode_sel == '2':
            default_expire = ''
            if existing and existing.get('type') == 'one_time':
                default_expire = existing.get('expire_at', '').replace('T', ' ')

            prompt_ex = t('rs_sch_expire_prompt')
            if default_expire:
                prompt_ex += f" ({t('rs_sch_current')}: {default_expire})"
            prompt_ex += " "
            raw_ex = clean_input(input(prompt_ex))
            if raw_ex.lower() in ['q', 'b']:
                return None, None
            if not raw_ex and default_expire:
                raw_ex = default_expire

            try:
                ex_fmt = raw_ex.replace(" ", "T")
                datetime.datetime.fromisoformat(ex_fmt)
            except ValueError:
                print(f"{Colors.FAIL}[-] {t('rs_sch_time_error')}{Colors.ENDC}")
                return None, None

            db_entry = {
                "type": "one_time", "name": target_name, "is_ruleset": is_rs,
                "action": "allow", "expire_at": ex_fmt,
                "detail_rs": meta_rs, "detail_src": meta_src, "detail_dst": meta_dst, "detail_svc": meta_svc,
                "detail_name": target_name
            }
            note_msg = f"[⏳ {t('rs_sch_tag_expire')}: {raw_ex}]"
            return db_entry, note_msg

        return None, None

    # ── Browse & Add ──

    def _browse_and_add(self):
        print(f"\n{Colors.HEADER}--- {t('rs_browse_title')} ---{Colors.ENDC}")

        raw = clean_input(input(f"{t('rs_browse_prompt')} "))
        if raw.lower() in ['q', 'b']:
            return

        selected_rs = None
        matches = []

        if not raw:
            print(f"{Colors.BLUE}[*] {t('rs_browse_loading')}{Colors.ENDC}")
            matches = self.api.get_all_rulesets()
        elif raw.isdigit():
            print(f"{Colors.BLUE}[*] {t('rs_browse_locate')} {raw} ...{Colors.ENDC}")
            rs = self.api.get_ruleset_by_id(raw)
            if rs:
                selected_rs = rs
            else:
                print(f"{Colors.WARNING}[-] {t('rs_browse_not_found')}{Colors.ENDC}")
                matches = self.api.search_rulesets(raw)
        else:
            matches = self.api.search_rulesets(raw)

        if not selected_rs:
            if not matches:
                return print(f"{Colors.FAIL}[-] {t('rs_browse_no_result')}{Colors.ENDC}")
            header = f"{t('rs_hdr_no'):<4} | {t('rs_hdr_sch'):<1} | {t('rs_hdr_id'):<6} | {'PROV':<6} | {t('rs_hdr_status'):<8} | {t('rs_hdr_rules'):<9} | {t('rs_hdr_name')}"
            selected_rs = paginate_and_select(matches, self.format_ruleset_row, title="RuleSets", header_str=header)
            if not selected_rs:
                return

        rs_href = selected_rs['href']
        rs_name = selected_rs['name']

        print(f"\n{Colors.GREEN}[+] {t('rs_browse_selected')} {rs_name} (ID: {extract_id(rs_href)}){Colors.ENDC}")
        print(f"1. {t('rs_browse_opt_rs')}")
        print(f"2. {t('rs_browse_opt_rule')}")

        sub_act = clean_input(input(f"{t('rs_browse_action')} "))
        if sub_act.lower() in ['q', 'b']:
            return

        target_href, target_name, is_rs = "", "", False
        meta_src, meta_dst, meta_svc, meta_rs = "All", "All", "All", rs_name
        ut = None

        if sub_act == '1':
            target_href, target_name, is_rs = rs_href, f"{rs_name}", True
            ut = selected_rs.get('update_type')

        elif sub_act == '2':
            full_rs = self.api.get_ruleset_by_id(extract_id(rs_href))
            rules = full_rs.get('rules', []) if full_rs else []
            if not rules:
                return print(f"{Colors.FAIL}[-] {t('rs_browse_no_rules')}{Colors.ENDC}")

            header = f"{t('rs_hdr_no'):<4} | {t('rs_hdr_sch'):<1} | {t('rs_hdr_id'):<6} | {'PROV':<6} | {t('rs_hdr_status'):<8} | {t('rs_hdr_note'):<30} | {t('rs_hdr_source'):<15} | {t('rs_hdr_dest'):<15} | {t('rs_hdr_service')}"
            r = paginate_and_select(rules, self.format_rule_row, title=f"Rules ({rs_name})", header_str=header)
            if not r:
                return

            target_href = r['href']
            target_name = r.get('description') or f"Rule {extract_id(r['href'])}"
            is_rs = False
            ut = r.get('update_type')

            dest_field = r.get('destinations', r.get('consumers', []))
            meta_src = self.api.resolve_actor_str(dest_field)
            meta_dst = self.api.resolve_actor_str(r.get('providers', []))
            meta_svc = self.api.resolve_service_str(r.get('ingress_services', []))
        else:
            return

        # Block draft-only scheduling natively to protect rulesets
        if self.api.has_draft_changes(target_href) or not self.api.is_provisioned(target_href):
            print(f"{Colors.FAIL}[!] {t('rs_sch_draft_block')}{Colors.ENDC}")
            return

        if target_href in self.db.get_all():
            print(f"{Colors.WARNING}[!] {t('rs_sch_exists_warn')}{Colors.ENDC}")
            if clean_input(input(f"{t('rs_sch_confirm')} ")).lower() != 'y':
                return

        db_entry, note_msg = self._collect_schedule_params(target_name, is_rs, meta_rs, meta_src, meta_dst, meta_svc)
        if not db_entry:
            return

        self.db.put(target_href, db_entry)
        self.api.update_rule_note(target_href, note_msg)
        print(f"\n{Colors.GREEN}[+] {t('rs_sch_saved')} (ID: {extract_id(target_href)}){Colors.ENDC}")

    # ── List Grouped ──

    def _list_grouped(self):
        db_data = self.db.get_all()
        if not db_data:
            print(f"\n{Colors.WARNING}[-] {t('rs_list_no_schedule')}{Colors.ENDC}")
            return

        groups = {}
        for href, conf in db_data.items():
            rs_name = conf.get('detail_rs', 'Uncategorized')
            if rs_name not in groups:
                groups[rs_name] = {'rs_config': None, 'rules': []}

            conf_action = conf.get('action', 'allow')
            entry_data = (href, conf, conf_action)

            if conf.get('is_ruleset'):
                groups[rs_name]['rs_config'] = entry_data
            else:
                groups[rs_name]['rules'].append(entry_data)

        print("\n" + Colors.BLUE + "━" * 145 + Colors.ENDC)
        print(f"{t('rs_hdr_sch'):<3} │ {t('rs_hdr_id'):<6} │ {'Type':<6} │ {t('rs_hdr_note'):<25} │ {t('rs_hdr_source'):<12} │ {t('rs_hdr_dest'):<12} │ {t('rs_hdr_service'):<16} │ {t('rs_list_mode'):<10} │ {t('rs_list_timing')}")
        print(Colors.BLUE + "─" * 145 + Colors.ENDC)

        for rs_name in sorted(groups.keys()):
            group = groups[rs_name]
            rs_entry = group['rs_config']

            if rs_entry:
                h, c, act = rs_entry
                rid = f"{Colors.CYAN}{extract_id(h):<6}{Colors.ENDC}"
                mark = f"{Colors.WARNING}★{Colors.ENDC}"

                status, live_data = self.api.get_live_item(h)
                if status == 200 and live_data:
                    if c.get('pce_status') == 'deleted':
                        c['pce_status'] = 'active'
                        self.db.put(h, c)
                    live_name = live_data.get('name', c['name'])
                    raw_name = truncate(f"[RS] {live_name}", 25)
                    display_name = f"{Colors.BOLD}{raw_name:<25}{Colors.ENDC}"
                elif live_data is None:
                    raw_name = truncate(f"[RS] {c.get('name', rs_name)} (Failed)", 25)
                    display_name = f"{Colors.WARNING}{raw_name:<25}{Colors.ENDC}"
                else:
                    if c.get('pce_status') != 'deleted':
                        c['pce_status'] = 'deleted'
                        self.db.put(h, c)
                    raw_name = truncate(f"[RS] {t('rs_list_deleted')}", 25)
                    display_name = f"{Colors.FAIL}{raw_name:<25}{Colors.ENDC}"

                if c['type'] == 'recurring':
                    mode_raw = t('rs_sch_action_enable') if act == 'allow' else t('rs_sch_action_disable')
                    mode_pad = f"{mode_raw:<10}"
                    mode = f"{Colors.GREEN}{mode_pad}{Colors.ENDC}" if act == 'allow' else f"{Colors.FAIL}{mode_pad}{Colors.ENDC}"
                    d_str = t('rs_action_everyday') if len(c['days']) == 7 else ",".join([d[:3] for d in c['days']])
                    time_str = f"{d_str} {c['start']}-{c['end']}"
                else:
                    mode = f"{Colors.FAIL}EXPIRE    {Colors.ENDC}"
                    time_str = f"Until {c['expire_at'].replace('T', ' ')}"

                print(f" {mark}  │ {rid} │ {'RS':<6} │ {display_name} │ {'-':<12} │ {'-':<12} │ {'-':<16} │ {mode} │ {time_str}")
            else:
                if group['rules']:
                    name = truncate(f"[RS] {rs_name}", 25)
                    print(f" {' ':1}  │ {' ':6} │ {'      '} │ {Colors.BOLD}{Colors.DARK_GRAY}{name:<25}{Colors.ENDC} │ {' ':12} │ {' ':12} │ {' ':16} │ {' ':10} │ {' '}")

            for h, c, act in group['rules']:
                rid = f"{Colors.CYAN}{extract_id(h):<6}{Colors.ENDC}"
                mark = f"{Colors.CYAN}●{Colors.ENDC}"

                status, live_data = self.api.get_live_item(h)
                if status == 200 and live_data:
                    if c.get('pce_status') == 'deleted':
                        c['pce_status'] = 'active'
                        self.db.put(h, c)
                    dest_field = live_data.get('destinations', live_data.get('consumers', []))
                    src = truncate(self.api.resolve_actor_str(dest_field), 12)
                    dst = truncate(self.api.resolve_actor_str(live_data.get('providers', [])), 12)
                    svc = truncate(self.api.resolve_service_str(live_data.get('ingress_services', [])), 16)

                    rule_action = live_data.get('action', 'allow')
                    if 'deny' in rule_action.lower():
                        type_str = f"{Colors.FAIL}{'Deny':<6}{Colors.ENDC}"
                    else:
                        type_str = f"{Colors.GREEN}{'Allow':<6}{Colors.ENDC}"

                    desc = live_data.get('description', '').strip()
                    if not desc or desc == '-':
                        desc = "(No description)"
                    else:
                        desc = desc.split('\n')[0]

                    raw_name = truncate(f" └─ {desc}", 25)
                    display_name = f"{Colors.DARK_GRAY}{raw_name:<25}{Colors.ENDC}"
                elif live_data is None:
                    type_str = f"{Colors.WARNING}{'Wait':<6}{Colors.ENDC}"
                    src = dst = svc = "-"
                    raw_name = truncate(f" └─ (Failed connection)", 25)
                    display_name = f"{Colors.WARNING}{raw_name:<25}{Colors.ENDC}"
                else:
                    if c.get('pce_status') != 'deleted':
                        c['pce_status'] = 'deleted'
                        self.db.put(h, c)
                    type_str = f"{Colors.FAIL}{'-':<6}{Colors.ENDC}"
                    src = dst = svc = "-"
                    raw_name = truncate(f" └─ {t('rs_list_rule_deleted')}", 25)
                    display_name = f"{Colors.FAIL}{raw_name:<25}{Colors.ENDC}"

                if c['type'] == 'recurring':
                    mode_raw = t('rs_sch_action_enable') if act == 'allow' else t('rs_sch_action_disable')
                    mode_pad = f"{mode_raw:<10}"
                    mode = f"{Colors.GREEN}{mode_pad}{Colors.ENDC}" if act == 'allow' else f"{Colors.FAIL}{mode_pad}{Colors.ENDC}"
                    d_str = t('rs_action_everyday') if len(c['days']) == 7 else ",".join([d[:3] for d in c['days']])
                    time_str = f"{d_str} {c['start']}-{c['end']}"
                else:
                    mode = f"{Colors.FAIL}EXPIRE    {Colors.ENDC}"
                    time_str = f"Until {c['expire_at'].replace('T', ' ')}"

                print(f" {mark}  │ {rid} │ {type_str} │ {display_name} │ {src:<12} │ {dst:<12} │ {svc:<16} │ {mode} │ {time_str}")

        print(Colors.BLUE + "━" * 145 + Colors.ENDC)

    # ── Edit by ID ──

    def _edit_by_id(self, edit_id):
        db_data = self.db.get_all()
        found = [x for x in db_data if extract_id(x) == edit_id]
        if not found:
            return print(f"{Colors.FAIL}[-] {t('rs_edit_not_found')}{Colors.ENDC}")

        href = found[0]
        existing = db_data[href]

        print(f"\n{Colors.CYAN}[*] {t('rs_edit_editing')} {existing.get('detail_name', existing['name'])} (ID: {edit_id}){Colors.ENDC}")
        print(f"{Colors.DARK_GRAY}{t('rs_sch_keep_enter')}{Colors.ENDC}")

        target_name = existing.get('detail_name', existing.get('name', ''))
        is_rs = existing.get('is_ruleset', False)
        meta_rs = existing.get('detail_rs', '')
        meta_src = existing.get('detail_src', 'All')
        meta_dst = existing.get('detail_dst', 'All')
        meta_svc = existing.get('detail_svc', 'All')

        db_entry, note_msg = self._collect_schedule_params(target_name, is_rs, meta_rs, meta_src, meta_dst, meta_svc, existing=existing)
        if not db_entry:
            return

        self.db.put(href, db_entry)
        self.api.update_rule_note(href, note_msg)
        print(f"\n{Colors.GREEN}[+] {t('rs_sch_updated')} (ID: {extract_id(href)}){Colors.ENDC}")

    # ── Delete by IDs (multi-delete) ──

    def _delete_by_ids(self, ids_str):
        db_data = self.db.get_all()
        ids = [x.strip() for x in ids_str.replace(' ', ',').split(',') if x.strip()]

        to_delete = []
        for k in ids:
            found = [x for x in db_data if extract_id(x) == k]
            if found:
                href = found[0]
                conf = db_data[href]
                to_delete.append((href, conf, k))
                print(f"  {t('rs_delete_target')} {conf.get('detail_name', conf['name'])} (ID: {k})")
            else:
                print(f"  {Colors.FAIL}[-] ID {k}: {t('rs_delete_not_found')}{Colors.ENDC}")

        if not to_delete:
            return

        if clean_input(input(f"\n  {t('rs_delete_confirm')} ({len(to_delete)} items) ")).lower() != 'y':
            return

        for href, conf, k in to_delete:
            try:
                self.api.update_rule_note(href, "", remove=True)
            except Exception:
                pass
            self.db.delete(href)
            print(f"  {Colors.GREEN}[OK] ID {k} {t('rs_delete_done')}{Colors.ENDC}")

    # ── Main Menu ──

    def run(self):
        while True:
            print(f"\n{Colors.HEADER}╭── {Colors.BOLD}{t('rs_menu_title')}{Colors.ENDC} {Colors.DARK_GRAY}[CLI]{Colors.ENDC}")
            print(f"{Colors.HEADER}│{Colors.ENDC} 1. {t('rs_menu_schedule')}")
            print(f"{Colors.HEADER}│{Colors.ENDC} 2. {t('rs_menu_check')}")
            print(f"{Colors.HEADER}│{Colors.ENDC} 3. {t('rs_menu_settings')}")
            print(f"{Colors.HEADER}│{Colors.ENDC} 0. {t('rs_back')}")
            print(f"{Colors.HEADER}╰{'─' * 40}{Colors.ENDC}")
            ans = clean_input(input(f"{Colors.CYAN}❯{Colors.ENDC} "))

            try:
                if ans == '1':
                    self.schedule_management_ui()
                elif ans == '2':
                    tz_str = self.cm.config.get('settings', {}).get('timezone', 'local')
                    self.engine.check(silent=False, tz_str=tz_str)
                    input(f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('press_enter_to_continue', default='Press Enter to continue...')} {Colors.GREEN}❯{Colors.ENDC} ")
                elif ans == '3':
                    self._settings_submenu()
                elif ans in ['0', 'q', 'b']:
                    break
            except Exception as e:
                print(f"{Colors.FAIL}[ERROR] {e}{Colors.ENDC}")
                traceback.print_exc()

    def _settings_submenu(self):
        """Rule scheduler settings (enable/disable, check interval)."""
        rs_cfg = self.cm.config.setdefault("rule_scheduler", {})
        enabled = rs_cfg.get("enabled", False)
        interval = rs_cfg.get("check_interval_seconds", 300)

        print(f"\n{Colors.HEADER}╭── {Colors.BOLD}{t('rs_menu_settings')}{Colors.ENDC}")
        status_str = f"{Colors.GREEN}ON{Colors.ENDC}" if enabled else f"{Colors.FAIL}OFF{Colors.ENDC}"
        print(f"{Colors.HEADER}│{Colors.ENDC} {t('rs_cfg_enabled', default='Enabled')}: {status_str}")
        print(f"{Colors.HEADER}│{Colors.ENDC} {t('rs_cfg_interval', default='Check Interval')}: {interval}s")
        print(f"{Colors.HEADER}├{'─' * 40}{Colors.ENDC}")
        print(f"{Colors.HEADER}│{Colors.ENDC} 1. {t('rs_cfg_toggle', default='Toggle Enable/Disable')}")
        print(f"{Colors.HEADER}│{Colors.ENDC} 2. {t('rs_cfg_set_interval', default='Set Check Interval')}")
        print(f"{Colors.HEADER}│{Colors.ENDC} 0. {t('rs_back')}")
        print(f"{Colors.HEADER}╰{'─' * 40}{Colors.ENDC}")

        ans = clean_input(input(f"{Colors.CYAN}❯{Colors.ENDC} "))
        if ans == '1':
            rs_cfg["enabled"] = not enabled
            self.cm.save()
            new_status = f"{Colors.GREEN}ON{Colors.ENDC}" if rs_cfg["enabled"] else f"{Colors.FAIL}OFF{Colors.ENDC}"
            print(f"{Colors.GREEN}[+] Rule Scheduler → {new_status}{Colors.ENDC}")
        elif ans == '2':
            raw = clean_input(input(f"{t('rs_cfg_interval_prompt', default='New interval (seconds)')}: "))
            if raw.isdigit() and int(raw) > 0:
                rs_cfg["check_interval_seconds"] = int(raw)
                self.cm.save()
                print(f"{Colors.GREEN}[+] Interval → {raw}s{Colors.ENDC}")
            else:
                print(f"{Colors.FAIL}[-] {t('rs_invalid_input')}{Colors.ENDC}")
