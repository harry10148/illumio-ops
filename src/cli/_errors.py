"""Structured CLI error formatting + did-you-mean (typo suggestion).

Phase 1 quick win for b4. Wrap raw exceptions / usage errors with:
- clear cause statement
- actionable recovery hint
- optional 'Did you mean: <closest>?' for typos
"""
from __future__ import annotations

import difflib
import sys


def format_error(cause: str, recovery: str | None = None,
                 did_you_mean: str | None = None) -> str:
    """Format a structured error message.

    Layout:
        Error: <cause>
        Did you mean: <suggestion>?      (optional)
        Try: <recovery hint>             (optional)
    """
    lines = [f"Error: {cause}"]
    if did_you_mean:
        lines.append(f"Did you mean: {did_you_mean}?")
    if recovery:
        lines.append(f"Try: {recovery}")
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
    """Wrap sys.excepthook so unhandled exceptions show structured error."""
    def handler(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.exit(130)
        cause = str(exc) or exc_type.__name__
        recovery = None
        if 'ConnectionError' in exc_type.__name__ or 'ConnectTimeout' in exc_type.__name__:
            recovery = f"Check network reachability and {app_name} config (PCE_HOST, PCE_PORT)."
        elif 'PermissionError' in exc_type.__name__:
            recovery = "Check file permissions for the path mentioned above."
        elif 'FileNotFoundError' in exc_type.__name__:
            recovery = "Verify the file path or run setup if this is the first run."
        else:
            recovery = "Re-run with --verbose for more detail."
        print(format_error(cause, recovery), file=sys.stderr)
        sys.exit(1)
    sys.excepthook = handler
