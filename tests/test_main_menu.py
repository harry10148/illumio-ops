from types import SimpleNamespace

import pytest

from src import i18n
from src import main as main_module


def _prepare_menu(monkeypatch, selection):
    answers = iter([selection, 0])

    monkeypatch.setattr(main_module.os, "system", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main_module, "draw_panel", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main_module, "safe_input", lambda *_args, **_kwargs: next(answers))
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: "")


@pytest.mark.parametrize(
    ("selection", "attr_name"),
    [
        (2, "add_traffic_menu"),
        (3, "add_bandwidth_volume_menu"),
        (9, "add_system_health_menu"),
    ],
)
def test_rule_management_menu_dispatches_submenus(monkeypatch, selection, attr_name):
    calls = []
    cm = SimpleNamespace(load=lambda: None, load_best_practices=lambda: None)

    _prepare_menu(monkeypatch, selection)

    monkeypatch.setattr(main_module, "add_event_menu", lambda _cm: calls.append("event"))
    monkeypatch.setattr(main_module, "add_traffic_menu", lambda _cm: calls.append("traffic"))
    monkeypatch.setattr(main_module, "add_bandwidth_volume_menu", lambda _cm: calls.append("bandwidth"))
    monkeypatch.setattr(main_module, "add_system_health_menu", lambda _cm: calls.append("system_health"))
    monkeypatch.setattr(main_module, "manage_rules_menu", lambda _cm: calls.append("manage"))

    main_module.rule_management_menu(cm)

    expected = {
        "add_traffic_menu": "traffic",
        "add_bandwidth_volume_menu": "bandwidth",
        "add_system_health_menu": "system_health",
    }[attr_name]
    assert calls == [expected]


def test_rule_management_menu_option_7_runs_analysis_and_sends_alerts(monkeypatch):
    calls = []
    cm = SimpleNamespace(load=lambda: None, load_best_practices=lambda: None)

    _prepare_menu(monkeypatch, 7)

    class FakeApiClient:
        def __init__(self, _cm):
            calls.append("api")

    class FakeReporter:
        def __init__(self, _cm):
            calls.append("reporter")

        def send_alerts(self, force_test=False):
            calls.append(("send_alerts", force_test))

    class FakeAnalyzer:
        def __init__(self, _cm, _api, _rep):
            calls.append("analyzer")

        def run_analysis(self):
            calls.append("run_analysis")

        def run_debug_mode(self):
            calls.append("run_debug_mode")

    monkeypatch.setattr(main_module, "ApiClient", FakeApiClient)
    monkeypatch.setattr(main_module, "Reporter", FakeReporter)
    monkeypatch.setattr(main_module, "Analyzer", FakeAnalyzer)

    main_module.rule_management_menu(cm)

    assert "run_analysis" in calls
    assert "run_debug_mode" not in calls
    assert ("send_alerts", False) in calls


def test_rule_management_menu_option_8_runs_debug_mode(monkeypatch):
    calls = []
    cm = SimpleNamespace(load=lambda: None, load_best_practices=lambda: None)

    _prepare_menu(monkeypatch, 8)

    class FakeApiClient:
        def __init__(self, _cm):
            calls.append("api")

    class FakeReporter:
        def __init__(self, _cm):
            calls.append("reporter")

        def send_alerts(self, force_test=False):
            calls.append(("send_alerts", force_test))

    class FakeAnalyzer:
        def __init__(self, _cm, _api, _rep):
            calls.append("analyzer")

        def run_analysis(self):
            calls.append("run_analysis")

        def run_debug_mode(self):
            calls.append("run_debug_mode")

    monkeypatch.setattr(main_module, "ApiClient", FakeApiClient)
    monkeypatch.setattr(main_module, "Reporter", FakeReporter)
    monkeypatch.setattr(main_module, "Analyzer", FakeAnalyzer)

    main_module.rule_management_menu(cm)

    assert "run_debug_mode" in calls
    assert "run_analysis" not in calls
    assert ("send_alerts", False) not in calls


def test_zh_tw_main_menu_13_has_system_health_label():
    previous = i18n.get_language()
    i18n.set_language("zh_TW")
    try:
        assert i18n.t("main_menu_13") == " 9. 新增系統健康規則"
    finally:
        i18n.set_language(previous)
