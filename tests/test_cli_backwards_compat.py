"""Verify that all legacy argparse flags still work after click migration."""
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENTRY = REPO_ROOT / "illumio-ops.py"


def _run(args, timeout=10):
    return subprocess.run(
        [sys.executable, str(ENTRY), *args],
        capture_output=True, text=True, timeout=timeout,
    )


def test_legacy_monitor_flag_still_recognized():
    """The legacy `--monitor -i N` form is still accepted by the argparse layer.

    Asserted against the parser, NOT by spawning the daemon. The spawned
    version ran `illumio-ops.py --monitor -i 1` for three seconds in the repo
    root with no isolation, so it read the installed config/config.json and
    logs/state.json and completed a whole monitor cycle before terminate
    landed. On a configured host that meant a run of the test suite really
    dispatched alerts to the operator's LINE and mail — on 2026-09-12 it sent
    a critical PCE watchdog alert twice, and an hour went into hunting for the
    appliance that supposedly sent it. A test for an argument parser must ask
    the argument parser.
    """
    from src.main import build_legacy_parser

    args = build_legacy_parser().parse_args(["--monitor", "-i", "1"])
    assert args.monitor is True
    assert args.interval == 1


def test_the_legacy_flag_test_never_starts_a_daemon():
    """守著上面那支不要被改回去。

    真正危險的不是「跑了一個 daemon」，是「跑了一個**沒有隔離**的 daemon」：
    config 路徑由套件位置決定（src/config.py 的 ROOT_DIR），子行程無法用 cwd
    或環境變數改掉，所以任何在這個 checkout 裡起真 daemon 的測試都會用真的
    收件設定。
    """
    source = Path(__file__).read_text(encoding="utf-8")
    body = source[source.index("def test_legacy_monitor_flag_still_recognized"):
                  source.index("def test_the_legacy_flag_test_never_starts_a_daemon")]
    assert "Popen" not in body, "argparse 的問題要問 argparse，不要起真 daemon"
    assert "subprocess" not in body


def test_new_version_subcommand_works():
    result = _run(["version"])
    assert result.returncode == 0
    assert "illumio-ops" in result.stdout.lower()


def test_new_status_subcommand_works():
    result = _run(["status"])
    # status may exit non-zero if config missing, but it must not crash
    assert "illumio-ops status" in result.stdout.lower() or result.returncode in (0, 1)


def test_help_shows_subcommands():
    result = _run(["--help"])
    assert result.returncode == 0
    for sub in ("monitor", "gui", "report", "rule", "workload", "config", "status", "version"):
        assert sub in result.stdout


def test_legacy_help_lists_expected_flags():
    result = _run(["--help"])
    assert result.returncode == 0
    for flag in (
        "--monitor",
        "--monitor-gui",
        "--interval",
        "--gui",
        "--port",
        "--report",
        "--report-type",
        "--source",
        "--file",
        "--format",
        "--email",
        "--output-dir",
    ):
        assert flag in result.stdout
