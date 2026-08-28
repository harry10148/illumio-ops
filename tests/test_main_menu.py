import os
from types import SimpleNamespace

import pytest

from src import i18n
from src import main as main_module

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _spy_on_file_lock(monkeypatch):
    """Record the path option 6/7 hands to the cross-process lock.

    The call site imports ``file_lock`` inside the ``elif`` branch, so there is
    no module-level ``main_module.file_lock`` to patch — patching the attribute
    on src.file_lock is what actually reaches it, because a function-local
    import resolves the module attribute at call time.
    """
    import src.file_lock as file_lock_mod

    seen = {}
    real = file_lock_mod.file_lock

    def _spy(path, *args, **kwargs):
        seen["path"] = path
        return real(path, *args, **kwargs)

    monkeypatch.setattr(file_lock_mod, "file_lock", _spy)
    return seen


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
    seen = _spy_on_file_lock(monkeypatch)

    class FakeApiClient:
        def __init__(self, _cm):
            calls.append("api")

    class FakeReporter:
        def __init__(self, _cm):
            calls.append("reporter")

        def send_alerts(self, force_test=False):
            calls.append(("send_alerts", force_test))

    class FakeAnalyzer:
        def __init__(self, _cm, _api, _rep, **kwargs):
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

    # Option 7 takes a REAL cross-process flock. Without tests/conftest.py's
    # _isolate_analysis_lock fixture that lock lands on <repo>/logs/analysis.lock,
    # i.e. on the working checkout, where a running --monitor-gui service or a
    # second pytest holds it and this test blocks for the full 5s timeout and
    # then silently takes the TimeoutError branch.
    assert seen.get("path") == main_module.analysis_lock_path()
    assert not os.path.abspath(seen["path"]).startswith(ROOT_DIR + os.sep), \
        f"option 7 locked inside the working checkout: {seen['path']}"


def test_analysis_lock_path_defaults_to_the_repo_logs_dir(monkeypatch):
    """Production behaviour is unchanged when the override env is absent/empty."""
    monkeypatch.delenv("ILLUMIO_OPS_ANALYSIS_LOCK", raising=False)
    assert main_module.analysis_lock_path() == os.path.join(ROOT_DIR, "logs", "analysis.lock")

    monkeypatch.setenv("ILLUMIO_OPS_ANALYSIS_LOCK", "")
    assert main_module.analysis_lock_path() == os.path.join(ROOT_DIR, "logs", "analysis.lock")


def test_analysis_lock_path_honours_the_env_override(monkeypatch, tmp_path):
    override = str(tmp_path / "elsewhere.lock")
    monkeypatch.setenv("ILLUMIO_OPS_ANALYSIS_LOCK", override)
    assert main_module.analysis_lock_path() == override


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
        def __init__(self, _cm, _api, _rep, **kwargs):
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
