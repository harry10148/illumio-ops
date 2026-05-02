"""Shared helper functions for all CLI wizard menus.

Previously defined in src/settings.py; extracted here as part of the H6 refactor.
"""
from __future__ import annotations
import datetime

from src.utils import Colors, draw_panel, get_last_input_action
from src.i18n import t


def _tz_offset_info(cm) -> tuple[str, float]:
    """Return (tz_label, offset_hours) from config's settings.timezone."""
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


def _menu_hints(path: str) -> list[str]:
    return [
        f"{Colors.DARK_GRAY}{t('cli_path_label', path=path)}{Colors.ENDC}",
        f"{Colors.DARK_GRAY}{t('cli_shortcuts_compact')}{Colors.ENDC}",
    ]


def _wizard_step(step: int, total: int, title: str) -> None:
    step_label = t("wiz_step")
    print(f"\n{Colors.BOLD}{Colors.CYAN}[{step_label} {step}/{total}] {title}{Colors.ENDC}")


def _wizard_confirm(summary_lines: list[str]) -> bool:
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


def _empty_uses_default(default_value) -> bool:
    return get_last_input_action() == "empty" and default_value not in (None, "")
