"""Global CLI flags: --json, --quiet, --verbose.

Phase 1 quick win for b3 (composability). Provides a decorator to
inject these flags at group level and a getter for downstream commands.
"""
from __future__ import annotations

import functools

import click


def inject_global_flags(group_callback):
    """Decorator to add --json/--quiet/--verbose to a Click group."""
    @click.option('--json', 'json_output', is_flag=True, default=False,
                  help='Emit machine-readable JSON to stdout (one object per result).')
    @click.option('--quiet', '-q', is_flag=True, default=False,
                  help='Suppress non-essential output. Errors still go to stderr.')
    @click.option('--verbose', '-v', is_flag=True, default=False,
                  help='Verbose output, including debug-level details.')
    @click.pass_context
    @functools.wraps(group_callback)
    def wrapper(ctx, json_output, quiet, verbose, *args, **kwargs):
        if quiet and verbose:
            raise click.UsageError("--quiet and --verbose are mutually exclusive.")
        ctx.ensure_object(dict)
        ctx.obj['_global_flags'] = {
            'json': json_output,
            'quiet': quiet,
            'verbose': verbose,
        }
        return group_callback(*args, **kwargs)
    return wrapper


def get_global_flags(ctx: click.Context) -> dict:
    """Read the global flags dict from the click context.

    Walks parents until found; returns defaults if not present.
    """
    cur = ctx
    while cur is not None:
        if cur.obj and isinstance(cur.obj, dict) and '_global_flags' in cur.obj:
            return cur.obj['_global_flags']
        cur = cur.parent
    return {'json': False, 'quiet': False, 'verbose': False}
