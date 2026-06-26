"""Compatibility matrix tests for click subcommands and legacy argparse flags."""
from __future__ import annotations

import sys
import types

import pytest
from click.testing import CliRunner


def _install_main_test_env(monkeypatch, main_module):
    class _FakeConfigManager:
        def __init__(self):
            self.config = {"logging": {}, "report": {}, "api": {"url": "https://pce.test"}}

    class _FakeModuleLog:
        @staticmethod
        def init(*_args, **_kwargs):
            return None

    monkeypatch.setattr(main_module, "setup_logger", lambda *a, **kw: None)
    monkeypatch.setattr(main_module, "ConfigManager", _FakeConfigManager)
    monkeypatch.setitem(sys.modules, "pandas", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "src.module_log", types.SimpleNamespace(ModuleLog=_FakeModuleLog))


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["illumio_ops.py", "monitor"], True),
        (["illumio_ops.py", "gui"], True),
        (["illumio_ops.py", "report"], True),
        (["illumio_ops.py", "rule"], True),
        (["illumio_ops.py", "workload"], True),
        (["illumio_ops.py", "config"], True),
        (["illumio_ops.py", "status"], True),
        (["illumio_ops.py", "version"], True),
        (["illumio_ops.py", "--help"], True),
        (["illumio_ops.py", "--monitor"], False),
        (["illumio_ops.py", "--gui"], False),
        (["illumio_ops.py", "--report"], False),
        (["illumio_ops.py"], False),
        # A typo'd / unknown positional still routes to click (which then reports
        # the error); it does NOT fall through to legacy argparse.
        (["illumio_ops.py", "montior"], True),
    ],
)
def test_entrypoint_click_detection_matrix(argv, expected):
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "illumio_ops",
        Path(__file__).resolve().parent.parent / "illumio-ops.py",
    )
    illumio_ops = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(illumio_ops)

    assert illumio_ops._looks_like_click_invocation(argv) is expected


def test_entrypoint_has_no_dead_click_subcommands_constant():
    """The unused _CLICK_SUBCOMMANDS set was dead code that contradicted the real
    dispatch rule (_looks_like_click_invocation never consulted it). Guard against
    it being reintroduced."""
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "illumio_ops",
        Path(__file__).resolve().parent.parent / "illumio-ops.py",
    )
    illumio_ops = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(illumio_ops)

    assert not hasattr(illumio_ops, "_CLICK_SUBCOMMANDS")


@pytest.mark.parametrize(
    ("args", "target_name", "expected_kwargs"),
    [
        (
            ["--report", "--report-type", "traffic", "--source", "csv", "--file", "flows.csv", "--format", "xlsx", "--email", "--output-dir", "out"],
            "generate_traffic_report",
            {
                "source": "csv",
                "file_path": "flows.csv",
                "fmt": "xlsx",
                "output_dir": "out",
                "email": True,
                "traffic_report_profile": "security_risk",
            },
        ),
        (
            ["--report", "--report-type", "audit", "--format", "csv", "--output-dir", "out"],
            "generate_audit_report",
            {
                "fmt": "csv",
                "output_dir": "out",
            },
        ),
        (
            ["--report", "--report-type", "ven_status", "--format", "xlsx", "--output-dir", "out"],
            "generate_ven_status_report",
            {
                "fmt": "xlsx",
                "output_dir": "out",
            },
        ),
        (
            ["--report", "--report-type", "policy_usage", "--source", "csv", "--file", "workloader.csv", "--format", "html", "--output-dir", "out"],
            "generate_policy_usage_report",
            {
                "source": "csv",
                "file_path": "workloader.csv",
                "fmt": "html",
                "output_dir": "out",
            },
        ),
    ],
)
def test_legacy_report_dispatch_matrix(monkeypatch, args, target_name, expected_kwargs):
    import src.main as main_module

    calls = {}
    _install_main_test_env(monkeypatch, main_module)

    def _make_handler(name):
        def _handler(**kwargs):
            calls["name"] = name
            calls["kwargs"] = kwargs
            return [f"/tmp/{name}.out"]

        return _handler

    monkeypatch.setattr("src.cli.report.generate_traffic_report", _make_handler("generate_traffic_report"))
    monkeypatch.setattr("src.cli.report.generate_audit_report", _make_handler("generate_audit_report"))
    monkeypatch.setattr("src.cli.report.generate_ven_status_report", _make_handler("generate_ven_status_report"))
    monkeypatch.setattr("src.cli.report.generate_policy_usage_report", _make_handler("generate_policy_usage_report"))
    monkeypatch.setattr(sys, "argv", ["illumio_ops.py", *args])

    with pytest.raises(SystemExit) as exc:
        main_module.main()

    assert exc.value.code == 0
    assert calls["name"] == target_name
    assert calls["kwargs"] == expected_kwargs


@pytest.mark.parametrize(
    ("args", "expected_message"),
    [
        (["--report", "--report-type", "audit", "--source", "csv"], "--source csv is not supported for audit reports"),
        (["--report", "--report-type", "ven_status", "--email"], "--email is only supported for traffic reports"),
    ],
)
def test_legacy_report_rejects_invalid_option_combinations(monkeypatch, capsys, args, expected_message):
    import src.main as main_module

    _install_main_test_env(monkeypatch, main_module)
    monkeypatch.setattr(sys, "argv", ["illumio_ops.py", *args])

    with pytest.raises(SystemExit) as exc:
        main_module.main()

    assert exc.value.code == 1
    assert expected_message in capsys.readouterr().out


def test_legacy_monitor_gui_dispatches_expected_args(monkeypatch):
    import src.main as main_module

    calls = {}
    _install_main_test_env(monkeypatch, main_module)
    monkeypatch.setattr(main_module, "run_daemon_with_gui", lambda interval, port: calls.update(interval=interval, port=port))
    monkeypatch.setattr(sys, "argv", ["illumio_ops.py", "--monitor-gui", "-i", "7", "--port", "9443"])

    with pytest.raises(SystemExit) as exc:
        main_module.main()

    assert exc.value.code == 0
    assert calls == {"interval": 7, "port": 9443}


def test_legacy_gui_dispatches_launch_gui_with_port(monkeypatch):
    import src.main as main_module

    calls = {}
    _install_main_test_env(monkeypatch, main_module)
    fake_gui = types.SimpleNamespace(
        launch_gui=lambda cm, host, port: calls.update(port=port, host=host, has_config=bool(cm)),
        HAS_FLASK=True,
        FLASK_IMPORT_ERROR=None,
    )
    monkeypatch.setitem(sys.modules, "src.gui", fake_gui)
    monkeypatch.setattr(sys, "argv", ["illumio_ops.py", "--gui", "--port", "8123"])

    main_module.main()

    # host is forwarded through run_gui_only → launch_gui (legacy path keeps the 0.0.0.0 default)
    assert calls == {"port": 8123, "host": "0.0.0.0", "has_config": True}


@pytest.mark.parametrize(
    ("argv", "helper_name", "expected_kwargs"),
    [
        (
            ["report", "traffic", "--source", "csv", "--file", "flows.csv", "--format", "all", "--output-dir", "out", "--email"],
            "generate_traffic_report",
            {
                "source": "csv",
                "file_path": "flows.csv",
                "fmt": "all",
                "output_dir": "out",
                "email": True,
                "traffic_report_profile": "security_risk",
                "use_cache": True,
                "data_source": None,
            },
        ),
        (
            ["report", "audit", "--start-date", "2026-04-01", "--end-date", "2026-04-02", "--format", "csv", "--output-dir", "out"],
            "generate_audit_report",
            {
                "start_date": "2026-04-01",
                "end_date": "2026-04-02",
                "fmt": "csv",
                "output_dir": "out",
            },
        ),
        (
            ["report", "ven-status", "--format", "xlsx", "--output-dir", "out"],
            "generate_ven_status_report",
            {
                "fmt": "xlsx",
                "output_dir": "out",
            },
        ),
        (
            ["report", "policy-usage", "--source", "csv", "--file", "workloader.csv", "--start-date", "2026-04-01", "--end-date", "2026-04-30", "--format", "xlsx", "--output-dir", "out"],
            "generate_policy_usage_report",
            {
                "source": "csv",
                "file_path": "workloader.csv",
                "start_date": "2026-04-01",
                "end_date": "2026-04-30",
                "fmt": "xlsx",
                "output_dir": "out",
            },
        ),
    ],
)
def test_click_report_subcommand_matrix(argv, helper_name, expected_kwargs):
    from src.cli.root import cli

    runner = CliRunner()
    calls = {}

    def _make_handler(name):
        def _handler(**kwargs):
            calls["name"] = name
            calls["kwargs"] = kwargs
            return [f"/tmp/{name}.out"]

        return _handler

    with pytest.MonkeyPatch.context() as mp, runner.isolated_filesystem():
        if "file_path" in expected_kwargs and expected_kwargs["file_path"]:
            with open(expected_kwargs["file_path"], "w", encoding="utf-8") as fh:
                fh.write("dummy")
        mp.setattr("src.cli.report.generate_traffic_report", _make_handler("generate_traffic_report"))
        mp.setattr("src.cli.report.generate_audit_report", _make_handler("generate_audit_report"))
        mp.setattr("src.cli.report.generate_ven_status_report", _make_handler("generate_ven_status_report"))
        mp.setattr("src.cli.report.generate_policy_usage_report", _make_handler("generate_policy_usage_report"))
        result = runner.invoke(cli, argv)

    assert result.exit_code == 0
    assert calls["name"] == helper_name
    assert calls["kwargs"] == expected_kwargs
