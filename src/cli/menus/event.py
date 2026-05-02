"""CLI wizard for adding or editing event alert rules."""
from __future__ import annotations
import os
import datetime

from src.config import ConfigManager
from src.i18n import t
from src.utils import Colors, safe_input, draw_panel, draw_table
from src.events.catalog import (
    FULL_EVENT_CATALOG,
    ACTION_EVENTS,
    _SEVERITY_FILTER_EVENT_TYPES,
)
from src.cli.menus._helpers import _menu_hints, _wizard_step, _wizard_confirm


def add_event_menu(cm: ConfigManager, edit_rule=None):
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
            desc_key = FULL_EVENT_CATALOG[cat][k]
            desc = t(desc_key, default=desc_key)
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
