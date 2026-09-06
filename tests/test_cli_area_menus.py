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
    for name in ("overview_menu", "investigate_menu", "policy_menu",
                 "reports_menu", "system_menu_entry"):
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


def test_system_area_opens_the_system_menu(monkeypatch):
    """The last forwarding stub is gone: all six areas have their own menus."""
    calls = []
    import src.cli.menus._root as root_mod
    monkeypatch.setattr(root_mod, "system_menu", lambda _cm: calls.append("system"))
    areas_module.system_menu_entry(_make_cm())
    assert calls == ["system"]


# ── Task 4: Alerting area ───────────────────────────────────────────────────

def _prepare_alerting(monkeypatch, selections):
    answers = iter(selections)
    monkeypatch.setattr(areas_module, "menu_screen", lambda *a, **k: None)
    monkeypatch.setattr(areas_module, "build_health_line", lambda cm: "")
    monkeypatch.setattr(areas_module, "safe_input", lambda *a, **k: next(answers))
    monkeypatch.setattr("builtins.input", lambda *a, **k: "")


@pytest.mark.parametrize(("selection", "target"), [
    (1, "add_event_menu"), (2, "add_traffic_menu"),
    (3, "add_bandwidth_volume_menu"), (4, "add_system_health_menu"),
    (5, "manage_rules_menu"),
])
def test_policy_menu_keeps_the_alerting_numbering(monkeypatch, selection, target):
    """System Health moves to 4 (cli-flows #13); Manage Rules to 5."""
    calls = []
    for name in ("add_event_menu", "add_traffic_menu", "add_bandwidth_volume_menu",
                 "add_system_health_menu", "manage_rules_menu"):
        monkeypatch.setattr(areas_module, name,
                            (lambda n: lambda *a, **k: calls.append(n))(name))
    _prepare_alerting(monkeypatch, [selection, None])
    areas_module.policy_menu(_make_cm())
    assert calls == [target]


def test_policy_menu_best_practices_is_item_9(monkeypatch):
    calls = []
    monkeypatch.setattr(areas_module, "_best_practices_flow",
                        lambda _cm: calls.append("bp"))
    _prepare_alerting(monkeypatch, [9, None])
    areas_module.policy_menu(_make_cm())
    assert calls == ["bp"]


def test_best_practices_flow_states_what_is_lost(monkeypatch):
    """Replace wipes custom rules — the box must name them, not just warn."""
    boxes = []
    monkeypatch.setattr("builtins.input", lambda *a, **k: "")
    monkeypatch.setattr(areas_module, "confirm_box",
                        lambda title, lines, ok: boxes.append((title, lines, ok)) or False)
    cm = _make_cm(rules=[{"name": "My Custom Rule", "type": "event"},
                         {"name": "Another Custom", "type": "traffic"}])
    cm.get_best_practice_rules = lambda: [{"name": "BP1"}, {"name": "BP2"}, {"name": "BP3"}]
    cm.load_best_practices = lambda: (_ for _ in ()).throw(AssertionError("must not run on cancel"))
    areas_module._best_practices_flow(cm)
    _title, lines, _ok = boxes[0]
    joined = "\n".join(lines)
    assert "My Custom Rule" in joined
    assert "Another Custom" in joined
    assert "3" in joined            # rules being loaded


def test_best_practices_flow_caps_the_custom_list_visibly(monkeypatch):
    """Never silently drop entries from an impact summary."""
    boxes = []
    monkeypatch.setattr("builtins.input", lambda *a, **k: "")
    monkeypatch.setattr(areas_module, "confirm_box",
                        lambda title, lines, ok: boxes.append(lines) or False)
    cm = _make_cm(rules=[{"name": f"Custom {i}", "type": "event"} for i in range(12)])
    cm.get_best_practice_rules = lambda: [{"name": "BP1"}]
    areas_module._best_practices_flow(cm)
    joined = "\n".join(boxes[0])
    assert "Custom 0" in joined
    assert "Custom 11" not in joined          # capped
    assert "4" in joined                      # "... and 4 more"


def test_best_practices_flow_runs_only_after_confirmation(monkeypatch):
    ran = []
    monkeypatch.setattr(areas_module, "confirm_box", lambda *a, **k: True)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "")
    cm = _make_cm(rules=[])
    cm.get_best_practice_rules = lambda: [{"name": "BP1"}]
    cm.load_best_practices = lambda: ran.append("ran")
    areas_module._best_practices_flow(cm)
    assert ran == ["ran"]


# ── Task 5 的自動化區：Phase 3C 之後是「規則」區的第 10、11 項 ──────────────
#
# 這三條原本測的是 automation_menu 的第 1、2 項。合併之後同樣兩個功能變成
# policy_menu 的第 10、11 項——**斷言的意義沒有改變**（同樣兩個進入點、同樣的
# 狀態讀數要出現在畫面上），改的只是它們在哪一個選單的第幾號。編號不能沿用
# 1/2，那是「新增 Event 規則」與「新增 Traffic 規則」。

def test_policy_menu_schedule_items_dispatch_and_show_status(monkeypatch):
    calls, screens = [], []
    cm = _make_cm()
    cm.config["rule_scheduler"] = {"enabled": True, "check_interval_seconds": 300}
    cm.get_report_schedules = lambda: [{"id": "s1"}]
    monkeypatch.setattr(areas_module, "menu_screen",
                        lambda path, lines, **kw: screens.append(lines))
    monkeypatch.setattr(areas_module, "build_health_line", lambda cm: "")
    monkeypatch.setattr(areas_module, "safe_input",
                        (lambda it: lambda *a, **k: next(it))(iter([10, 11, None])))
    import src.rule_scheduler_cli as rsc
    monkeypatch.setattr(rsc, "rule_scheduler_menu", lambda _cm: calls.append("rs"))
    import src.cli.menus.report_schedule as rsched
    monkeypatch.setattr(rsched, "manage_report_schedules_menu", lambda _cm: calls.append("sched"))
    areas_module.policy_menu(cm)
    assert calls == ["rs", "sched"]
    joined = "\n".join(str(x) for x in screens[0])
    assert "300" in joined and "1" in joined


def test_policy_menu_shows_scheduler_off(monkeypatch):
    screens = []
    cm = _make_cm()
    cm.config["rule_scheduler"] = {}
    cm.get_report_schedules = lambda: []
    monkeypatch.setattr(areas_module, "menu_screen",
                        lambda path, lines, **kw: screens.append(lines))
    monkeypatch.setattr(areas_module, "build_health_line", lambda cm: "")
    monkeypatch.setattr(areas_module, "safe_input", lambda *a, **k: None)
    areas_module.policy_menu(cm)
    assert "OFF" in "\n".join(str(x) for x in screens[0])


def test_policy_menu_survives_missing_schedule_api(monkeypatch):
    """A menu must not die because one status number cannot be read."""
    screens = []
    cm = _make_cm()
    cm.config["rule_scheduler"] = {"enabled": False}
    monkeypatch.setattr(areas_module, "menu_screen",
                        lambda path, lines, **kw: screens.append(lines))
    monkeypatch.setattr(areas_module, "build_health_line", lambda cm: "")
    monkeypatch.setattr(areas_module, "safe_input", lambda *a, **k: None)
    areas_module.policy_menu(cm)          # cm has no get_report_schedules
    assert screens


# ── Task 6: Reports area ────────────────────────────────────────────────────

def test_reports_menu_dispatch(monkeypatch):
    calls = []
    cm = _make_cm()
    cm.config["report"] = {"output_dir": "reports/", "retention_days": 30}
    monkeypatch.setattr(areas_module, "menu_screen", lambda *a, **k: None)
    monkeypatch.setattr(areas_module, "build_health_line", lambda cm: "")
    monkeypatch.setattr(areas_module, "safe_input",
                        (lambda it: lambda *a, **k: next(it))(iter([1, 5, 6, None])))
    import src.main as m
    monkeypatch.setattr(m, "_run_report_menu", lambda _cm: calls.append("traffic"))
    import src.cli.menus.report_schedule as rsched
    monkeypatch.setattr(rsched, "manage_report_schedules_menu", lambda _cm: calls.append("sched"))
    monkeypatch.setattr(areas_module, "report_output_settings_menu",
                        lambda _cm: calls.append("output"))
    areas_module.reports_menu(cm)
    assert calls == ["traffic", "sched", "output"]


def test_reports_menu_shows_output_dir_and_retention(monkeypatch):
    screens = []
    cm = _make_cm()
    cm.config["report"] = {"output_dir": "/srv/out", "retention_days": 7}
    monkeypatch.setattr(areas_module, "menu_screen",
                        lambda path, lines, **kw: screens.append(lines))
    monkeypatch.setattr(areas_module, "build_health_line", lambda cm: "")
    monkeypatch.setattr(areas_module, "safe_input", lambda *a, **k: None)
    areas_module.reports_menu(cm)
    joined = "\n".join(str(x) for x in screens[0])
    assert "/srv/out" in joined and "7" in joined


def test_report_output_settings_saves_both_fields(monkeypatch):
    saved = []
    cm = _make_cm()
    cm.config["report"] = {"output_dir": "reports/", "retention_days": 30}
    cm.save = lambda: saved.append(dict(cm.config["report"]))
    monkeypatch.setattr(areas_module, "safe_input",
                        (lambda it: lambda *a, **k: next(it))(iter(["/new/dir", 14])))
    areas_module.report_output_settings_menu(cm)
    assert saved == [{"output_dir": "/new/dir", "retention_days": 14}]


def test_report_output_settings_keeps_current_on_blank(monkeypatch):
    """Enter means 'leave it alone', not 'set it to empty'."""
    saved = []
    cm = _make_cm()
    cm.config["report"] = {"output_dir": "reports/", "retention_days": 30}
    cm.save = lambda: saved.append(dict(cm.config["report"]))
    monkeypatch.setattr(areas_module, "safe_input",
                        (lambda it: lambda *a, **k: next(it))(iter(["", None])))
    areas_module.report_output_settings_menu(cm)
    assert saved == [{"output_dir": "reports/", "retention_days": 30}]


# ── Task 7: System area ─────────────────────────────────────────────────────

import src.cli.menus._root as root_module


def _sys_cm(**api):
    base = {"url": "https://pce.test", "org_id": "1", "key": "k", "secret": "s",
            "verify_ssl": True, "deployment_type": "on_prem", "console_url": ""}
    base.update(api)
    saved = []
    cm = SimpleNamespace(
        load=lambda: None,
        config={"api": base, "rules": [], "settings": {}, "alerts": {"active": []}},
        models=SimpleNamespace(pce_cache=SimpleNamespace(db_path="/tmp/x.db")),
    )
    cm.save = lambda: saved.append(dict(cm.config["api"]))
    cm.saved = saved
    return cm


def _patch_pce_menu(monkeypatch, answers, flush=None, order=None):
    it = iter(answers)
    monkeypatch.setattr(root_module, "safe_input", lambda *a, **k: next(it))
    monkeypatch.setattr(root_module, "menu_screen", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(root_module, "draw_panel", lambda *a, **k: None)
    monkeypatch.setattr(root_module, "resolve_state_file", lambda: "/tmp/state.json")
    import src.pce_cache.flush as flush_mod
    def _flush(*a, **k):
        if order is not None:
            order.append("flush")
        if flush is not None:
            return flush(*a, **k)
    monkeypatch.setattr(flush_mod, "flush_pce_derived_state", _flush)


def test_pce_connection_merges_api_and_ssl(monkeypatch):
    """#29+#31: the SSL prompt joins the connection screen, no separate item."""
    cm = _sys_cm()
    # deployment, console, url (same), org (same), key, secret, ssl choice
    _patch_pce_menu(monkeypatch, ["on_prem", "", "https://pce.test", "1", "k", "s", 1])
    root_module._pce_connection_menu(cm)
    assert cm.saved, "an edit with no target change must still save"
    assert cm.config["api"]["verify_ssl"] is True


def test_pce_connection_cancel_saves_nothing(monkeypatch):
    """Third state: abandon the whole edit."""
    cm = _sys_cm()
    order = []
    _patch_pce_menu(monkeypatch, ["on_prem", "", "https://other.test", "1", "k", "s", 1, None],
                    order=order)
    root_module._pce_connection_menu(cm)
    assert cm.saved == []
    assert order == []
    assert cm.config["api"]["url"] == "https://pce.test"


def test_pce_connection_declining_flush_still_saves(monkeypatch):
    """The path a two-state confirm box would have folded away."""
    cm = _sys_cm()
    order = []
    _patch_pce_menu(monkeypatch, ["on_prem", "", "https://other.test", "1", "k", "s", 1, 2, ""],
                    order=order)
    root_module._pce_connection_menu(cm)
    assert order == [], "declining the flush must not clear the cache"
    assert cm.saved, "declining the flush must still save the new target"
    assert cm.config["api"]["url"] == "https://other.test"


def test_pce_connection_flushes_before_saving(monkeypatch):
    """Past the save the stored target names the new PCE and the guard never
    fires again — a flush ordered after it would leave the old cache forever."""
    cm = _sys_cm()
    order = []
    _patch_pce_menu(monkeypatch, ["on_prem", "", "https://other.test", "1", "k", "s", 1, 1, ""],
                    order=order)
    cm.save = lambda: order.append("save")
    root_module._pce_connection_menu(cm)
    assert order == ["flush", "save"]


def test_pce_connection_flush_failure_blocks_save(monkeypatch):
    """saved=False while cancelled=False — the state a single flag cannot hold."""
    cm = _sys_cm()
    order = []

    def _boom(*a, **k):
        raise RuntimeError("cache locked")

    _patch_pce_menu(monkeypatch, ["on_prem", "", "https://other.test", "1", "k", "s", 1, 1, ""],
                    flush=_boom, order=order)
    root_module._pce_connection_menu(cm)
    assert cm.saved == [], "a failed flush must not be followed by a save"


def test_system_menu_dispatch(monkeypatch):
    calls = []
    cm = _sys_cm()
    monkeypatch.setattr(root_module, "menu_screen", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(root_module, "draw_panel", lambda *a, **k: None)
    monkeypatch.setattr(root_module, "build_health_line", lambda _cm: "", raising=False)
    monkeypatch.setattr(root_module, "safe_input",
                        (lambda it: lambda *a, **k: next(it))(iter([2, 4, 7, None])))
    monkeypatch.setattr(root_module, "alert_settings_menu", lambda _cm: calls.append("alert"))
    monkeypatch.setattr(root_module, "web_gui_security_menu", lambda _cm: calls.append("wgs"))
    monkeypatch.setattr(root_module, "_view_logs_entry", lambda: calls.append("logs"), raising=False)
    root_module.system_menu(cm)
    assert calls == ["alert", "wgs", "logs"]


def test_system_menu_has_no_report_output_or_rule_scheduler_items():
    """RP-1 moved to Reports; AU-2's only home is rule_scheduler_cli."""
    import inspect
    src_text = inspect.getsource(root_module.system_menu)
    assert "settings_5" not in src_text
    assert "settings_6" not in src_text


def test_settings_menu_alias_still_resolves():
    """src/settings/__init__.py's shim imports this name."""
    assert root_module.settings_menu is root_module.system_menu


# ── Phase 3C Task 3: 主選單五區（與 GUI 同一組區域） ─────────────────────────

def _main_menu_render(monkeypatch):
    """跑一次主選單，回傳 (畫出來的行, safe_input 收到的可接受選項集合)。"""
    panels: list[list[str]] = []
    accepted: list = []

    def _draw(_title, lines, *a, **k):
        panels.append(list(lines))

    def _input(_prompt, _typ, choices, *a, **k):
        accepted.append(choices)
        return None

    monkeypatch.setattr(main_module, "setup_logger", lambda *a, **k: None)
    monkeypatch.setattr(main_module, "ConfigManager", lambda: _make_cm())
    monkeypatch.setitem(sys.modules, "src.module_log",
                        types.SimpleNamespace(ModuleLog=types.SimpleNamespace(init=lambda *a: None)))
    monkeypatch.setattr(main_module, "draw_panel", _draw)
    monkeypatch.setattr(main_module, "build_health_line", lambda cm: "")
    monkeypatch.setattr(main_module, "safe_input", _input)
    main_module.main_menu()
    return panels[0], accepted[0]


def test_the_area_keys_stop_at_five_in_both_catalogues():
    """第六區的鍵必須從兩份 i18n 都消失。

    直接讀 JSON 而不是問 `t()`：`t()` 對缺鍵回 `[MISSING:...]`，那既不是空字串
    也不是例外，用它判斷「鍵不存在」會寫出看起來對、其實在比對佔位字串的斷言。
    留著孤兒鍵的代價是下一個讀 i18n 的人以為還有第六區。
    """
    import json
    from pathlib import Path

    root = Path(__file__).parent.parent
    for name in ("src/i18n_en.json", "src/i18n_zh_TW.json"):
        data = json.loads((root / name).read_text(encoding="utf-8"))
        present = sorted(k for k in data if k.startswith("main_menu_area_"))
        assert present == [f"main_menu_area_{n}" for n in range(1, 6)], (
            f"{name} 的區域鍵是 {present}，應為 1-5")
        for dead in ("cli_area_alerting", "cli_area_automation", "cli_area_overview"):
            assert dead not in data, f"{name} 還留著 {dead}"
        assert "cli_area_policy" in data and "cli_area_home" in data


def test_the_main_menu_draws_five_areas_and_accepts_only_those(monkeypatch):
    lines, accepted = _main_menu_render(monkeypatch)
    from src import i18n
    area_lines = [l for l in lines
                  if any(l == i18n.t(f"main_menu_area_{n}") for n in range(1, 9))]
    assert len(area_lines) == 5, f"畫出來的區域列有 {len(area_lines)} 條，應為 5：{area_lines}"
    assert set(accepted) == {"1", "2", "3", "4", "5", "g", "G", "0"}, accepted


@pytest.mark.parametrize(("selection", "target"), [
    ("1", "overview_menu"),
    ("2", "investigate_menu"),
    ("3", "policy_menu"),
    ("4", "reports_menu"),
    ("5", "system_menu_entry"),
])
def test_main_menu_dispatches_five_areas(monkeypatch, selection, target):
    calls = []
    for name in ("overview_menu", "investigate_menu", "policy_menu",
                 "reports_menu", "system_menu_entry"):
        monkeypatch.setattr(main_module, name,
                            (lambda n: lambda _cm: calls.append(n))(name))
    _run_main_menu(monkeypatch, [selection, None])
    assert calls == [target]
