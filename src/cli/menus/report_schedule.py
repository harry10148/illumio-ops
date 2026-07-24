"""CLI wizard for managing report schedules."""
from __future__ import annotations
import os
import json as _json
from pathlib import Path

from src.config import ConfigManager
from src.i18n import t
from src.utils import Colors, safe_input, draw_panel, draw_table
from src.cli.menus._helpers import (
    _menu_hints,
    _wizard_step,
    _wizard_confirm,
    _tz_offset_info,
    _utc_to_local_hour,
    _local_to_utc_hour,
)

# This file lives at src/cli/menus/report_schedule.py.
# parents[0]=menus  parents[1]=cli  parents[2]=src  parents[3]=project_root
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def manage_report_schedules_menu(cm: ConfigManager) -> None:
    """Main menu for listing and managing report schedules."""
    while True:
        os.system("cls" if os.name == "nt" else "clear")
        schedules = cm.get_report_schedules()

        # Load last-run states from state.json
        state_file = str(_PROJECT_ROOT / "logs" / "state.json")
        states = {}
        if os.path.exists(state_file):
            try:
                with open(state_file, "r", encoding="utf-8") as f:
                    states = _json.load(f).get("report_schedule_states", {})
            except Exception:
                pass  # intentional fallback: state enrichment is best-effort; schedules still listed without last-run state

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
                enabled = f"{Colors.GREEN}{t('status_on', default='ON')}{Colors.ENDC}" if s.get("enabled") else f"{Colors.FAIL}{t('status_off', default='OFF')}{Colors.ENDC}"

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
                confirm = safe_input(t("confirm_delete_sched", name=sched.get('name', '')), str)
                if confirm is None:
                    continue
                confirm = confirm.strip().lower()
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


def _add_report_schedule_wizard(cm: ConfigManager, edit_sched: dict = None) -> None:
    """Wizard for adding or editing a report schedule."""
    is_edit = edit_sched is not None
    title = t("sched_edit") if is_edit else t("sched_add")
    os.system("cls" if os.name == "nt" else "clear")
    draw_panel(title, [])

    def _ask(prompt, default="", cast=str):
        hint = f" (default: {default})" if default != "" else ""
        while True:
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
                print(f"{Colors.FAIL}{t('cli_invalid_number', value=val)}{Colors.ENDC}")
                continue

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
    if not (1 <= lookback_days <= 3650):
        print(f"{Colors.FAIL}{t('cli_lookback_out_of_range')}{Colors.ENDC}")
        input(f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('press_enter_to_continue')} ")
        return

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
