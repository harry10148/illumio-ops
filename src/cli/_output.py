"""Centralized CLI output helpers.

Track B Task 2: replaces ad-hoc click.echo / print / console.print
with semantic functions that:
- Honor --json / --quiet / --verbose from _global_flags
- Route info to stdout, warning/error to stderr (composability)
- Provide structured JSON emission

Migration target: all 24 commands across src/cli/ + 3 standalone CLIs.
"""
from __future__ import annotations

import json as _json
import sys
from typing import Any

import click

from src.cli._global_flags import get_global_flags
from src.i18n import t


def echo_info(ctx: click.Context, message: str) -> None:
    """Print informational message to stdout. Suppressed in --quiet."""
    flags = get_global_flags(ctx)
    if flags.get('quiet'):
        return
    click.echo(message, err=False)


def echo_verbose(ctx: click.Context, message: str) -> None:
    """Print debug-level message to stderr. Only shown with --verbose."""
    flags = get_global_flags(ctx)
    if not flags.get('verbose'):
        return
    click.echo(message, err=True)


def echo_warning(ctx: click.Context, message: str) -> None:
    """Print warning to stderr. Always shown (even in --quiet)."""
    click.echo(f"{t('cli_warning_prefix', default='warning: ')}{message}", err=True)


def echo_error(ctx: click.Context, message: str) -> None:
    """Print error to stderr. Always shown."""
    click.echo(f"{t('cli_error_prefix', default='error: ')}{message}", err=True)


def echo_json(ctx: click.Context, data: Any, *, indent: int | None = None) -> None:
    """Emit data as JSON to stdout. Use only when --json is set, but no
    explicit gate here — caller decides path: rich-table vs json.

    Always uses ensure_ascii=False (safe for terminal UTF-8).
    """
    click.echo(_json.dumps(data, ensure_ascii=False, indent=indent))


def is_json(ctx: click.Context) -> bool:
    """Convenience: True if caller asked for --json output."""
    return get_global_flags(ctx).get('json', False)


def is_quiet(ctx: click.Context) -> bool:
    return get_global_flags(ctx).get('quiet', False)


def is_verbose(ctx: click.Context) -> bool:
    return get_global_flags(ctx).get('verbose', False)
