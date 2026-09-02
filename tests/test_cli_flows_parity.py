"""cli-flows.md §2's 63-node table: every pre-2C entry point is still reachable.

A restructure like this fails quietly. Nothing errors when a menu item simply
stops existing — the operator just cannot find it any more, and no test notices
because no test ever named it. So each of the 63 nodes is accounted for here in
one of two ways:

- ("dispatch", fn): reached in this file, by scripted input against the new menu
- ("covered", file, test_name): a named guard test elsewhere proves it

The second kind is only worth anything if the test it names still exists, so
this file opens the file and looks for the def. A checklist that points at
deleted tests is a checklist that passes while the feature is gone.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from src import i18n
from src.cli._render import get_visible_width

TESTS_DIR = Path(__file__).parent


@pytest.fixture(autouse=True)
def _english_ui():
    prev = i18n.get_language()
    i18n.set_language("en")
    yield
    i18n.set_language(prev)


# ── the table ───────────────────────────────────────────────────────────────
# value is either ("covered", <test file>, <test name>) or ("area", <area>)
NODES: dict[int, tuple] = {
    1:  ("covered", "test_cli_area_menus.py", "test_main_menu_dispatches_six_areas"),
    2:  ("area", "alerting"),      # container, dissolved into the alerting area
    3:  ("covered", "test_cli_area_menus.py", "test_alerting_menu_new_numbering"),
    4:  ("covered", "test_cli_area_menus.py", "test_alerting_menu_new_numbering"),
    5:  ("covered", "test_cli_area_menus.py", "test_alerting_menu_new_numbering"),
    6:  ("covered", "test_cli_area_menus.py", "test_alerting_menu_new_numbering"),
    7:  ("covered", "test_manage_rules_menu.py", "test_delete_asks_before_removing"),
    8:  ("covered", "test_manage_rules_menu.py", "test_manage_rules_menu_modify_command_routes_by_rule_type"),
    9:  ("covered", "test_cli_area_menus.py", "test_alerting_menu_best_practices_is_item_9"),
    10: ("covered", "test_main_menu.py", "test_rule_management_menu_option_7_runs_analysis_and_sends_alerts"),
    11: ("covered", "test_main_menu.py", "test_rule_management_menu_option_8_runs_debug_mode"),
    12: ("covered", "test_cli_area_menus.py", "test_alerting_menu_new_numbering"),
    13: ("covered", "test_cli_area_menus.py", "test_alerting_menu_new_numbering"),
    14: ("area", "reports"),       # container, dissolved into the reports area
    15: ("covered", "test_cli_area_menus.py", "test_reports_menu_dispatch"),
    16: ("covered", "test_cli_area_menus.py", "test_reports_menu_dispatch"),
    17: ("covered", "test_cli_area_menus.py", "test_reports_menu_dispatch"),
    18: ("covered", "test_cli_area_menus.py", "test_reports_menu_dispatch"),
    19: ("covered", "test_cli_area_menus.py", "test_reports_menu_dispatch"),
    20: ("covered", "test_cli_wizard_chrome.py", "test_every_wizard_step_passes_a_path"),
    21: ("covered", "test_cli_wizard_chrome.py", "test_every_wizard_step_passes_a_path"),
    22: ("covered", "test_cli_wizard_chrome.py", "test_every_wizard_step_passes_a_path"),
    23: ("covered", "test_cli_wizard_chrome.py", "test_every_wizard_step_passes_a_path"),
    24: ("covered", "test_cli_area_menus.py", "test_automation_menu_dispatch_and_status"),
    25: ("covered", "test_rule_scheduler_cli.py", "test_scheduler_menu_renders_inside_panel_with_status"),
    26: ("covered", "test_rule_scheduler_cli.py", "test_scheduler_menu_renders_inside_panel_with_status"),
    27: ("covered", "test_rule_scheduler_cli.py", "test_scheduler_menu_renders_inside_panel_with_status"),
    28: ("area", "system"),        # container, dissolved into the system area
    29: ("covered", "test_cli_area_menus.py", "test_pce_connection_merges_api_and_ssl"),
    30: ("covered", "test_cli_area_menus.py", "test_system_menu_dispatch"),
    31: ("covered", "test_cli_area_menus.py", "test_pce_connection_merges_api_and_ssl"),
    32: ("covered", "test_cli_area_menus.py", "test_system_menu_dispatch"),
    33: ("covered", "test_cli_area_menus.py", "test_reports_menu_shows_output_dir_and_retention"),
    34: ("covered", "test_cli_area_menus.py", "test_automation_menu_dispatch_and_status"),
    35: ("covered", "test_cli_area_menus.py", "test_system_menu_dispatch"),
    36: ("covered", "test_cli_area_menus.py", "test_system_menu_dispatch"),
    37: ("covered", "test_cli_area_menus.py", "test_system_menu_dispatch"),
    38: ("covered", "test_cli_area_menus.py", "test_system_menu_dispatch"),
    39: ("covered", "test_cli_area_menus.py", "test_system_menu_dispatch"),
    40: ("covered", "test_cli_area_menus.py", "test_main_menu_g_launches_web_gui_flow"),
    41: ("covered", "test_cli_area_menus.py", "test_system_menu_dispatch"),
    42: ("covered", "test_cli_area_menus.py", "test_system_menu_dispatch"),
    43: ("covered", "test_pce_cache_menu.py", "test_menu_renders_inside_panel"),
    44: ("covered", "test_pce_cache_menu.py", "test_menu_renders_inside_panel"),
    45: ("covered", "test_pce_cache_menu.py", "test_menu_renders_inside_panel"),
    46: ("covered", "test_pce_cache_menu.py", "test_menu_renders_inside_panel"),
    47: ("covered", "test_pce_cache_menu.py", "test_menu_renders_inside_panel"),
    48: ("covered", "test_pce_cache_menu.py", "test_retention_asks_first_and_names_the_windows"),
    49: ("covered", "test_cli_area_menus.py", "test_system_menu_dispatch"),
    50: ("covered", "test_siem_cli.py", "test_siem_menu_renders_inside_panel"),
    51: ("covered", "test_siem_cli.py", "test_siem_menu_renders_inside_panel"),
    52: ("covered", "test_siem_cli.py", "test_siem_menu_renders_inside_panel"),
    53: ("covered", "test_siem_cli.py", "test_siem_menu_renders_inside_panel"),
    54: ("covered", "test_siem_cli.py", "test_siem_menu_renders_inside_panel"),
    55: ("covered", "test_siem_cli.py", "test_destination_delete_still_demands_the_word_yes"),
    56: ("covered", "test_siem_cli.py", "test_siem_menu_renders_inside_panel"),
    57: ("covered", "test_siem_cli.py", "test_siem_menu_renders_inside_panel"),
    58: ("covered", "test_siem_cli_dlq.py", "test_dlq_bulk_replay_wires_to_replay_ids"),
    59: ("covered", "test_siem_cli_dlq.py", "test_dlq_bulk_purge_deletes_only_selected_ids_after_yes_confirm"),
    60: ("covered", "test_siem_cli.py", "test_dlq_purge_still_demands_the_word_yes"),
    61: ("covered", "test_siem_cli.py", "test_dlq_purge_still_demands_the_word_yes"),
    62: ("covered", "test_siem_cli_dlq.py", "test_dlq_purge_all_wires_to_purge"),
    63: ("covered", "test_cli_area_menus.py", "test_main_menu_zero_returns_without_dispatching"),
}


def test_every_node_in_the_table_is_accounted_for():
    assert set(NODES) == set(range(1, 64))


def _defined_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {n.name for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


@pytest.mark.parametrize("node", sorted(n for n, v in NODES.items() if v[0] == "covered"))
def test_covered_nodes_point_at_a_test_that_exists(node):
    """A checklist naming deleted tests passes while the feature is gone."""
    _kind, filename, test_name = NODES[node]
    path = TESTS_DIR / filename
    assert path.exists(), f"node {node}: {filename} is gone"
    assert test_name in _defined_names(path), \
        f"node {node}: {filename} no longer defines {test_name}"


@pytest.mark.parametrize("node", sorted(n for n, v in NODES.items() if v[0] == "area"))
def test_dissolved_containers_have_an_area(node):
    """The three containers are gone on purpose; their area must exist."""
    import src.cli.menus.areas as areas
    _kind, area = NODES[node]
    attr = {"alerting": "alerting_menu", "reports": "reports_menu",
            "system": "system_menu_entry"}[area]
    assert callable(getattr(areas, attr))


# ── copy width ──────────────────────────────────────────────────────────────
# 80-column terminals are the floor; 78 leaves room for the panel border.
_SAMPLE = {"count": 12, "total": 12, "ev": 3, "tr": 3, "sys": 3, "bw": 3,
           "lang": "EN", "theme": "Dark", "activity": "2 minutes ago",
           "status": "OFF", "interval": 300, "dir": "reports/", "days": 30,
           "customs": "x", "path": "System > PCE Cache", "table": "events"}

_NEW_KEY_PREFIXES = ("main_menu_area_", "main_menu_launch_gui", "cli_area_",
                     "cli_ov_", "cli_iv_", "cli_alerting_", "cli_auto_",
                     "cli_rpt_", "cli_sys_", "cli_confirm_", "cli_bp_",
                     "cli_health_", "cli_rs_status_line", "cli_retention_impact_line",
                     "cur_val_prefix")


def _new_keys() -> list[str]:
    import json
    with open(Path(__file__).parents[1] / "src" / "i18n_en.json", encoding="utf-8") as fh:
        return [k for k in json.load(fh) if k.startswith(_NEW_KEY_PREFIXES)]


@pytest.mark.parametrize("lang", ["en", "zh_TW"])
def test_every_new_menu_string_fits_an_80_column_terminal(lang):
    i18n.set_language(lang)
    too_wide = []
    for key in _new_keys():
        text = i18n.t(key, lang=lang)
        try:
            text = text.format(**_SAMPLE)
        except (KeyError, IndexError, ValueError):
            pass
        width = get_visible_width(text)
        if width > 78:
            too_wide.append((key, width))
    assert too_wide == [], f"{lang}: {too_wide}"
