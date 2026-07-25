#!/usr/bin/env python3
"""Illumio PCE Ops — Entry Point.

Two parsers coexist:
- click-based subcommands (preferred): illumio-ops monitor/gui/report/rule/workload/config/status/version
- legacy argparse flags (backwards-compatible): --monitor, --gui, --report, -i, -p

The dispatcher below routes to click when argv[1] is a help flag (-h/--help),
a click global flag (--json/--quiet/-v/...), or any non-dash positional (a
subcommand attempt — a bogus one errors inside click rather than falling
through). Otherwise the legacy argparse parser handles the classic flags.

Usage:
    python illumio_ops.py                       # interactive menu
    python illumio_ops.py monitor -i 5          # new subcommand style
    python illumio_ops.py --monitor -i 5        # legacy (still works)
    python illumio_ops.py report traffic        # new
    python illumio_ops.py --report              # legacy (still works)
"""
from __future__ import annotations

import sys

import os as _os

# Click root-level global flags. If argv starts with one of these, dispatcher
# should still route to click (rather than falling through to legacy argparse).
_CLICK_GLOBAL_FLAGS = {"--json", "--quiet", "-q", "--verbose", "-v"}

# Route to click for shell completion generation
_COMPLETION_ENV = _os.environ.get("_ILLUMIO_OPS_COMPLETE", "")


def _looks_like_click_invocation(argv: list[str]) -> bool:
    """True when argv looks like a click subcommand attempt.

    Routes to click when:
      - argv[1] is a help flag (`-h` / `--help`), or
      - argv[1] is a click global flag (`--json` / `--quiet` / `-v` / ...), or
      - argv[1] does NOT start with '-' (i.e. positional subcommand).

    Otherwise falls through to legacy argparse for `--monitor`, `--gui`, etc.
    """
    if len(argv) < 2:
        return False
    first = argv[1]
    if first in ("-h", "--help"):
        return True
    if first in _CLICK_GLOBAL_FLAGS:
        return True
    return not first.startswith("-")


def _bootstrap_logging() -> None:
    """Install the project's loguru sinks for the click entrypoint.

    只有 legacy argparse 路徑（src/main.py）會呼叫 setup_logger；click 子指令
    （monitor / monitor-gui / gui / report ...）以前完全沒做，後果是：
      - loguru 內建的 stderr sink（DEBUG、**無 redaction filter**）留著，
        api_key / password / token / Authorization / PCE href 原文直接進
        journal 與 NSSM 的 logs/service_stderr.log；
      - logs/illumio_ops.log（疑難排解文件叫操作者看的那個檔）從不建立，
        0640 權限與輪替壓縮也全部沒套用；
      - config.json 的 logging.level / json_sink 被無聲忽略；
      - ModuleLog 未 init，logs/modules/*.log 完全不產生。
    設定讀不到時仍要換掉預設 sink——留著沒有 redaction 的那個更危險。
    """
    root_dir = _os.path.dirname(_os.path.abspath(__file__))
    log_dir = _os.path.join(root_dir, "logs")
    level, json_sink = "INFO", False
    try:
        from src.config import ConfigManager
        _log_cfg = ConfigManager().config.get("logging", {}) or {}
        level = _log_cfg.get("level", "INFO")
        json_sink = bool(_log_cfg.get("json_sink", False))
    except Exception:
        pass  # intentional: 設定不可讀不該擋住 CLI；下面照樣安裝安全的 sink
    from src.utils import setup_logger
    setup_logger("src", _os.path.join(log_dir, "illumio_ops.log"),
                 level=level, json_sink=json_sink)
    from src.module_log import ModuleLog
    ModuleLog.init(log_dir)


if __name__ == "__main__":
    from src.runtime_checks import sqlite_version_error
    _sqlite_err = sqlite_version_error()
    if _sqlite_err:
        print(_sqlite_err, file=sys.stderr)
        sys.exit(1)
    from src.cli._errors import install_top_level_handler
    install_top_level_handler()
    try:
        if _COMPLETION_ENV or _looks_like_click_invocation(sys.argv):
            # shell completion 與純 --help 不需要（也不該）為了印說明去讀設定。
            if not _COMPLETION_ENV and sys.argv[1] not in ("-h", "--help"):
                _bootstrap_logging()
            from src.cli.root import cli
            cli(prog_name="illumio-ops")
        else:
            from src.main import main
            main()
    except ImportError as e:
        print(f"Error importing src package: {e}")
        print("Ensure you are running this script from the project root directory.")
        sys.exit(1)
