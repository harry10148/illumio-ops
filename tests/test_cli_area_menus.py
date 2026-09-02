"""Phase 2C Task 3 — the six-area main menu and the two read-only areas.

The eight flat items become six areas plus a G shortcut for the web GUI. Areas
that Tasks 4-7 have not reached yet forward to the old containers, so every
function stays reachable at every point in the migration.
"""
from __future__ import annotations

import sys
import types
from types import SimpleNamespace

import pytest

from src import i18n
import src.main as main_module
import src.cli.menus.areas as areas_module


@pytest.fixture(autouse=True)
def _english_ui():
    prev = i18n.get_language()
    i18n.set_language("en")
    yield
    i18n.set_language(prev)


def _make_cm(rules=None):
    return SimpleNamespace(
        load=lambda: None,
        config={
            "api": {"url": "https://pce.test:8443"},
            "rules": rules if rules is not None else [],
            "settings": {"language": "en", "theme": "dark", "timezone": "UTC+8"},
        },
    )


def _run_main_menu(monkeypatch, selections):
    answers = iter(selections)
    monkeypatch.setattr(main_module, "setup_logger", lambda *a, **k: None)
    monkeypatch.setattr(main_module, "ConfigManager", lambda: _make_cm())
    monkeypatch.setitem(sys.modules, "src.module_log",
                        types.SimpleNamespace(ModuleLog=types.SimpleNamespace(init=lambda *a: None)))
    monkeypatch.setattr(main_module, "draw_panel", lambda *a, **k: None)
    monkeypatch.setattr(main_module, "build_health_line", lambda cm: "")
    monkeypatch.setattr(main_module, "safe_input", lambda *a, **k: next(answers))
    main_module.main_menu()


@pytest.mark.parametrize(("selection", "target"), [
    ("1", "overview_menu"),
    ("2", "investigate_menu"),
    ("3", "alerting_menu"),
    ("4", "automation_menu"),
    ("5", "reports_menu"),
    ("6", "system_menu_entry"),
])
def test_main_menu_dispatches_six_areas(monkeypatch, selection, target):
    calls = []
    for name in ("overview_menu", "investigate_menu", "alerting_menu",
                 "automation_menu", "reports_menu", "system_menu_entry"):
        monkeypatch.setattr(main_module, name,
                            (lambda n: lambda _cm: calls.append(n))(name))
    _run_main_menu(monkeypatch, [selection, None])
    assert calls == [target]


def test_main_menu_g_launches_web_gui_flow(monkeypatch):
    calls = []
    monkeypatch.setattr(main_module, "_launch_web_gui_flow", lambda _cm: calls.append("gui"))
    _run_main_menu(monkeypatch, ["G", None])
    assert calls == ["gui"]


def test_main_menu_lowercase_g_also_launches(monkeypatch):
    calls = []
    monkeypatch.setattr(main_module, "_launch_web_gui_flow", lambda _cm: calls.append("gui"))
    _run_main_menu(monkeypatch, ["g", None])
    assert calls == ["gui"]


def test_main_menu_zero_returns_without_dispatching(monkeypatch):
    calls = []
    for name in ("overview_menu", "investigate_menu", "alerting_menu",
                 "automation_menu", "reports_menu", "system_menu_entry"):
        monkeypatch.setattr(main_module, name,
                            (lambda n: lambda _cm: calls.append(n))(name))
    _run_main_menu(monkeypatch, ["0"])
    assert calls == []


def test_overview_menu_is_read_only_and_returns(monkeypatch):
    screens = []
    monkeypatch.setattr(areas_module, "menu_screen",
                        lambda path, lines, **kw: screens.append((path, lines)))
    monkeypatch.setattr(areas_module, "build_health_line", lambda cm: "")
    monkeypatch.setattr(areas_module, "safe_input", lambda *a, **k: None)
    cm = _make_cm(rules=[{"type": "event"}, {"type": "traffic"}, {"type": "system"}])
    areas_module.overview_menu(cm)
    _path, lines = screens[0]
    joined = "\n".join(str(x) for x in lines)
    assert "https://pce.test:8443" in joined
    assert "3" in joined
    assert "OV-1" in joined


def test_overview_counts_rules_by_type(monkeypatch):
    screens = []
    monkeypatch.setattr(areas_module, "menu_screen",
                        lambda path, lines, **kw: screens.append(lines))
    monkeypatch.setattr(areas_module, "build_health_line", lambda cm: "")
    monkeypatch.setattr(areas_module, "safe_input", lambda *a, **k: None)
    cm = _make_cm(rules=[{"type": "event"}, {"type": "event"}, {"type": "traffic"},
                         {"type": "bandwidth"}, {"type": "volume"}])
    areas_module.overview_menu(cm)
    joined = "\n".join(str(x) for x in screens[0])
    assert "5" in joined            # total
    assert "2" in joined            # two event rules
    # bandwidth and volume are one lamp's worth of counting, per the spec
    assert "bw" in joined.lower() or "bandwidth" in joined.lower()


def test_investigate_menu_points_to_workload_subcommand(monkeypatch):
    screens = []
    monkeypatch.setattr(areas_module, "menu_screen",
                        lambda path, lines, **kw: screens.append(lines))
    monkeypatch.setattr(areas_module, "build_health_line", lambda cm: "")
    monkeypatch.setattr(areas_module, "safe_input", lambda *a, **k: None)
    areas_module.investigate_menu(_make_cm())
    joined = "\n".join(str(x) for x in screens[0])
    assert "illumio-ops workload --help" in joined


@pytest.mark.parametrize("area", ["alerting_menu", "automation_menu",
                                  "reports_menu", "system_menu_entry"])
def test_unmigrated_areas_still_reach_their_old_container(monkeypatch, area):
    """Tasks 4-7 replace these; until then every function must stay reachable."""
    calls = []
    monkeypatch.setattr(main_module, "rule_management_menu", lambda _cm: calls.append("hit"))
    monkeypatch.setattr(main_module, "report_generation_menu", lambda _cm: calls.append("hit"))
    monkeypatch.setattr(main_module, "manage_report_schedules_menu", lambda _cm: calls.append("hit"))
    monkeypatch.setattr(main_module, "settings_menu", lambda _cm: calls.append("hit"))
    getattr(areas_module, area)(_make_cm())
    assert calls == ["hit"]
