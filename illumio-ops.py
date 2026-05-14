#!/usr/bin/env python3
"""Illumio PCE Ops — Entry Point.

Two parsers coexist:
- click-based subcommands (preferred): illumio-ops monitor/gui/report/rule/workload/config/status/version
- legacy argparse flags (backwards-compatible): --monitor, --gui, --report, -i, -p

The dispatcher below picks which to use based on argv[1] — if it matches a
known click subcommand name we delegate to click, otherwise argparse handles
the classic flags.

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

# Known click subcommand names; anything else falls back to argparse.
_CLICK_SUBCOMMANDS = {"cache", "monitor", "monitor-gui", "gui", "report", "rule", "siem", "workload", "config", "status", "version", "shell", "completion", "-h", "--help"}

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


if __name__ == "__main__":
    from src.cli._errors import install_top_level_handler
    install_top_level_handler()
    try:
        if _COMPLETION_ENV or _looks_like_click_invocation(sys.argv):
            from src.cli.root import cli
            cli(prog_name="illumio-ops")
        else:
            from src.main import main
            main()
    except ImportError as e:
        print(f"Error importing src package: {e}")
        print("Ensure you are running this script from the project root directory.")
        sys.exit(1)
