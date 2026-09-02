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
from src.cli.menu_chrome import menu_screen
from src.cli.health_line import build_health_line


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

def alerting_menu(cm) -> None:
    from src import main as _main
    _main.rule_management_menu(cm)


def automation_menu(cm) -> None:
    from src import main as _main
    _main.manage_report_schedules_menu(cm)


def reports_menu(cm) -> None:
    from src import main as _main
    _main.report_generation_menu(cm)


def system_menu_entry(cm) -> None:
    from src import main as _main
    _main.settings_menu(cm)
