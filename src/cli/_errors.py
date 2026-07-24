"""Structured CLI error formatting + did-you-mean (typo suggestion).

Phase 1 quick win for b4. Wrap raw exceptions / usage errors with:
- clear cause statement
- actionable recovery hint
- optional 'Did you mean: <closest>?' for typos
"""
from __future__ import annotations

import difflib
import signal
import sys

from src.i18n import t

from src.cli._exit_codes import (
    EXIT_INTERRUPT,
    EXIT_SOFTWARE,
    EXIT_TERMINATED,
    exit_for_exception,
)


def format_error(cause: str, recovery: str | None = None,
                 did_you_mean: str | None = None) -> str:
    """Format a structured error message.

    Layout:
        Error: <cause>
        Did you mean: <suggestion>?      (optional)
        Try: <recovery hint>             (optional)
    """
    lines = [f"{t('cli_err_label', default='Error')}: {cause}"]
    if did_you_mean:
        lines.append(f"{t('cli_err_did_you_mean', default='Did you mean')}: {did_you_mean}?")
    if recovery:
        lines.append(f"{t('cli_err_try', default='Try')}: {recovery}")
    return "\n".join(lines)


def suggest_command(typed: str, candidates: list[str], cutoff: float = 0.6) -> str | None:
    """Return closest candidate to `typed`, or None if nothing close enough."""
    matches = difflib.get_close_matches(typed, candidates, n=1, cutoff=cutoff)
    return matches[0] if matches else None


def print_error(cause: str, recovery: str | None = None,
                did_you_mean: str | None = None, exit_code: int = 1) -> None:
    """Print formatted error to stderr and exit with given code."""
    print(format_error(cause, recovery, did_you_mean), file=sys.stderr)
    sys.exit(exit_code)


def install_top_level_handler(app_name: str = "illumio-ops") -> None:
    """Wrap sys.excepthook + install SIGTERM handler.

    On unhandled exception: structured error to stderr + typed exit code.
    On SIGINT: exit 130. On SIGTERM: exit 143.
    """
    def excepthook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.exit(EXIT_INTERRUPT)
        cause = str(exc) or exc_type.__name__
        recovery = _recovery_for(exc_type, app_name)
        print(format_error(cause, recovery), file=sys.stderr)
        sys.exit(exit_for_exception(exc) or EXIT_SOFTWARE)

    def sigterm_handler(signum, frame):
        sys.exit(EXIT_TERMINATED)

    sys.excepthook = excepthook
    signal.signal(signal.SIGTERM, sigterm_handler)


def _recovery_for(exc_type, app_name: str = "illumio-ops") -> str:
    name = exc_type.__name__
    if 'ConnectionError' in name or 'ConnectTimeout' in name:
        return f"Check network reachability and {app_name} config (PCE_HOST, PCE_PORT)."
    if 'PermissionError' in name:
        return "Check file permissions for the path mentioned above."
    if 'FileNotFoundError' in name:
        return "Verify the file path or run setup if this is the first run."
    return "Re-run with --verbose for more detail."
