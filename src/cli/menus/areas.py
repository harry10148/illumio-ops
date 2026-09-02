"""六區互動選單的區層入口（Phase 2C，cli-flows.md §3.3）。

主選單把八個扁平項目換成六個區。Overview 與 Investigate 是唯讀畫面，其餘四區
在本階段先轉呼叫舊容器——**任一時點每個功能都必須可達**，遷移不是把功能先拿掉
再補回來。T4–T7 逐一換上真身。

不得在模組頂層 import `src.main`（循環）：stub 走延遲 import，且以屬性存取取用，
測試 monkeypatch `main_module.<name>` 才會生效。
"""
from __future__ import annotations

import datetime as _dt
import os

from src.i18n import t
from src.utils import Colors, safe_input
from src.cli.menu_chrome import confirm_box, menu_screen
from src.cli.health_line import build_health_line
from src.settings import (
    add_event_menu,
    add_system_health_menu,
    add_traffic_menu,
    add_bandwidth_volume_menu,
    manage_rules_menu,
)


def _last_activity_text(log_file: str) -> str:
    """How long ago the log was last written, or a plain 'no activity' note."""
    if not log_file or not os.path.exists(log_file):
        return t("gui_no_log_activity", default="(no log activity)")
    try:
        from src.humanize_ext import human_time_ago
        return human_time_ago(_dt.datetime.fromtimestamp(os.path.getmtime(log_file)))
    except Exception:
        return t("gui_no_log_activity", default="(no log activity)")


def _rule_counts(cm) -> dict:
    rules = cm.config.get("rules", []) or []
    def _n(*types):
        return sum(1 for r in rules if str(r.get("type", "")) in types)
    return {
        "total": len(rules),
        "ev": _n("event"),
        "tr": _n("traffic"),
        "sys": _n("system", "system_health"),
        # bandwidth and volume share one counter — they are one rule family to
        # an operator reading a summary line.
        "bw": _n("bandwidth", "volume"),
    }


def _log_file() -> str:
    from src import main as _main
    log_file = getattr(_main, "LOG_FILE", "") or ""
    if log_file:
        return log_file
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(root, "logs", "illumio_ops.log")


def overview_menu(cm) -> None:
    """§3.3.1 — read-only. Everything here is changed somewhere else."""
    counts = _rule_counts(cm)
    settings = cm.config.get("settings", {}) or {}
    lines = [
        f"{t('cli_status_api', default='API')}: {cm.config.get('api', {}).get('url', '-')}",
        t("cli_ov_rules_configured", **counts),
        t("cli_ov_lang_theme",
          lang=(settings.get("language", "en") or "en").upper(),
          theme=(settings.get("theme", "dark") or "dark").capitalize(),
          activity=_last_activity_text(_log_file())),
        "-",
        f"{Colors.DARK_GRAY}{t('cli_ov_readonly_note')}{Colors.ENDC}",
        "",
        t("menu_return"),
    ]
    menu_screen(t("cli_area_overview"), lines, health=build_health_line(cm))
    safe_input(f"\n{t('please_select')}", int, range(0, 1))


def investigate_menu(cm) -> None:
    """§3.3.2 — the CLI's investigation surface is the workload subcommand."""
    lines = [
        t("cli_iv_note_1"),
        t("cli_iv_note_2"),
        "-",
        f"  {Colors.CYAN}{t('cli_iv_hint_cmd')}{Colors.ENDC}",
        "",
        t("menu_return"),
    ]
    menu_screen(t("cli_area_investigate"), lines, health=build_health_line(cm))
    safe_input(f"\n{t('please_select')}", int, range(0, 1))


# ── areas still forwarding to their pre-2C containers (T4-T7 replace these) ──

_BP_CUSTOM_LIST_CAP = 8


def _best_practices_flow(cm) -> None:
    """§3.5.4 — loading the built-in rules REPLACES everything, including the
    operator's own rules. The box says which ones, by name."""
    rules = cm.config.get("rules", []) or []
    try:
        bp_rules = cm.get_best_practice_rules() or []
    except Exception:
        bp_rules = []
    bp_names = {r.get("name") for r in bp_rules}
    customs = [r.get("name", "?") for r in rules if r.get("name") not in bp_names]

    impact = [t("cli_bp_impact_load", count=len(bp_rules))]
    if customs:
        impact.append(t("cli_bp_impact_remove", count=len(customs)))
        for name in customs[:_BP_CUSTOM_LIST_CAP]:
            impact.append(f"    - {name}")
        if len(customs) > _BP_CUSTOM_LIST_CAP:
            # Say how many were left out. A list that just stops reads complete.
            impact.append(t("cli_bp_more_customs",
                            count=len(customs) - _BP_CUSTOM_LIST_CAP))
    impact.append(t("cli_bp_impact_backup"))

    if not confirm_box(t("cli_confirm_bp_title"), impact, t("cli_bp_ok_label")):
        print(t("operation_cancelled", default="Operation cancelled."))
        input(f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('press_enter_to_continue')} "
              f"{Colors.GREEN}\u276f{Colors.ENDC} ")
        return
    print(f"{Colors.BLUE}{t('loading_best_practices')}{Colors.ENDC}")
    cm.load_best_practices()
    input(f"\n{Colors.CYAN}[?]{Colors.ENDC} "
          f"{t('best_practice_loaded', default='Best practices loaded. Press Enter to continue...')} "
          f"{Colors.GREEN}\u276f{Colors.ENDC} ")


def alerting_menu(cm) -> None:
    """§3.3.3 — nine items. System Health moves to 4 (cli-flows #13) so the four
    'add a rule' wizards sit together."""
    while True:
        cm.load()
        rules = cm.config.get("rules", []) or []
        lines = [
            t("cli_alerting_1"),
            t("cli_alerting_2"),
            t("cli_alerting_3"),
            t("cli_alerting_4"),
            t("cli_alerting_5", count=len(rules)),
            t("cli_alerting_6"),
            t("cli_alerting_7"),
            t("cli_alerting_8"),
            t("cli_alerting_9"),
            "",
            t("menu_return"),
        ]
        menu_screen(t("cli_area_alerting"), lines, health=build_health_line(cm))
        sel = safe_input(f"\n{t('please_select')}", int, range(0, 10))
        if sel is None or sel == 0:
            break
        if sel == 1:
            add_event_menu(cm)
        elif sel == 2:
            add_traffic_menu(cm)
        elif sel == 3:
            add_bandwidth_volume_menu(cm)
        elif sel == 4:
            add_system_health_menu(cm)
        elif sel == 5:
            manage_rules_menu(cm)
        elif sel == 6:
            _send_test_alert(cm)
        elif sel == 7:
            _run_analysis_now(cm)
        elif sel == 8:
            _run_debug_mode(cm)
        elif sel == 9:
            _best_practices_flow(cm)


def _send_test_alert(cm) -> None:
    """Moved verbatim from main.rule_management_menu item 6, lock and all."""
    from src import main as _main
    from src.file_lock import file_lock as _file_lock
    try:
        with _file_lock(_main.analysis_lock_path(), timeout=_main._ANALYSIS_LOCK_WAIT_S):
            _main.Reporter(cm).send_alerts(force_test=True)
    except TimeoutError:
        print(f"{Colors.WARNING}{t('cli_analysis_in_progress')}{Colors.ENDC}")
    input(f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('done_msg')} {Colors.GREEN}\u276f{Colors.ENDC} ")


def _analyzer(cm):
    from src import main as _main
    api = _main.ApiClient(cm)
    rep = _main.Reporter(cm)
    sub_events, sub_flows = _main._make_subscribers(cm)
    ana = _main.Analyzer(cm, api, rep,
                         subscriber_events=sub_events, subscriber_flows=sub_flows,
                         cache_reader=_main._make_cache_reader(cm),
                         flow_delta_reader=_main._make_flow_delta_reader(cm))
    return api, rep, ana


def _run_analysis_now(cm) -> None:
    """Item 7, moved verbatim. The cross-process lock stays: a full cycle run
    beside the resident monitor would overwrite state from a stale snapshot and
    wipe alert cooldowns."""
    from src import main as _main
    from src.file_lock import file_lock as _file_lock
    try:
        with _file_lock(_main.analysis_lock_path(), timeout=_main._ANALYSIS_LOCK_WAIT_S):
            _api, rep, ana = _analyzer(cm)
            ana.run_analysis()
            rep.send_alerts()
    except TimeoutError:
        print(f"{Colors.WARNING}{t('cli_analysis_in_progress')}{Colors.ENDC}")
    input(f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('press_enter_to_continue')} "
          f"{Colors.GREEN}\u276f{Colors.ENDC} ")


def _run_debug_mode(cm) -> None:
    """Item 8, moved verbatim — read-only, so no lock (matches the original)."""
    _api, _rep, ana = _analyzer(cm)
    ana.run_debug_mode()
    input(f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('press_enter_to_continue')} "
          f"{Colors.GREEN}\u276f{Colors.ENDC} ")


def automation_menu(cm) -> None:
    """§3.3.4 — rule schedules and report schedules, with their state on the row.

    AU-2: the rule scheduler's enable/interval switch has exactly one home,
    inside rule_scheduler_cli's own Settings. This is an entry point, not a
    second place to toggle it.
    """
    while True:
        cm.load()
        rs_cfg = cm.config.get("rule_scheduler", {}) or {}
        try:
            sched_count = len(cm.get_report_schedules() or [])
        except Exception:
            # One unreadable status number must not take the menu down with it.
            sched_count = 0
        lines = [
            t("cli_auto_rule_scheduler",
              status="ON" if rs_cfg.get("enabled", False) else "OFF",
              interval=rs_cfg.get("check_interval_seconds", 300)),
            t("cli_auto_report_schedules", count=sched_count),
            "",
            t("menu_return"),
        ]
        menu_screen(t("cli_area_automation"), lines, health=build_health_line(cm))
        sel = safe_input(f"\n{t('please_select')}", int, range(0, 3))
        if sel is None or sel == 0:
            break
        if sel == 1:
            import src.rule_scheduler_cli as rsc
            rsc.rule_scheduler_menu(cm)
        elif sel == 2:
            import src.cli.menus.report_schedule as rsched
            rsched.manage_report_schedules_menu(cm)


def report_output_settings_menu(cm) -> None:
    """RP-1's new home. Moved from the settings menu unchanged: blank keeps the
    current value rather than clearing it."""
    rc = cm.config.setdefault("report", {})
    print(f"\n{Colors.CYAN}{t('setup_report_output')}{Colors.ENDC}")
    new_dir = safe_input(
        t("report_output_dir"), str, allow_cancel=True,
        hint=rc.get("output_dir", "reports/"), hint_is_current=True,
    ) or rc.get("output_dir", "reports/")
    rc["output_dir"] = new_dir.strip()

    new_ret = safe_input(
        t("report_retention_days"), int, allow_cancel=True,
        hint=str(rc.get("retention_days", 30)), hint_is_current=True,
    )
    if new_ret is not None:
        rc["retention_days"] = max(0, int(new_ret))
    cm.save()
    print(f"{Colors.GREEN}{t('saved')}{Colors.ENDC}")


def reports_menu(cm) -> None:
    """§3.3.5 — the four generators, a pointer to schedules, and output settings.

    Report Schedules lives in Automation; item 5 opens the same function from
    here so an operator looking for it under Reports still finds it.
    """
    while True:
        cm.load()
        rc = cm.config.get("report", {}) or {}
        lines = [
            t("main_menu_9"),
            t("main_menu_10"),
            t("main_menu_11"),
            t("main_menu_pu"),
            t("cli_rpt_schedules_pointer"),
            t("cli_rpt_output_settings",
              dir=rc.get("output_dir", "reports/"),
              days=rc.get("retention_days", 30)),
            "",
            t("menu_return"),
        ]
        menu_screen(t("cli_area_reports"), lines, health=build_health_line(cm))
        sel = safe_input(f"\n{t('please_select')}", int, range(0, 7))
        if sel is None or sel == 0:
            break
        from src import main as _main
        if sel == 1:
            _main._run_report_menu(cm)
        elif sel == 2:
            _main._run_audit_report_menu(cm)
        elif sel == 3:
            _main._run_ven_status_menu(cm)
        elif sel == 4:
            _main._run_policy_usage_menu(cm)
        elif sel == 5:
            import src.cli.menus.report_schedule as rsched
            rsched.manage_report_schedules_menu(cm)
        elif sel == 6:
            report_output_settings_menu(cm)


def system_menu_entry(cm) -> None:
    from src.cli.menus._root import system_menu
    system_menu(cm)
