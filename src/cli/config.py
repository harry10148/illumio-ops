"""`illumio-ops config ...` subcommand group."""
from __future__ import annotations

import json
import os

import click
from rich.console import Console

from src.cli._output import is_json, is_quiet, echo_error, echo_json
from src.cli._exit_codes import EXIT_NOINPUT, EXIT_DATAERR, EXIT_CONFIG, EXIT_USAGE

@click.group("config")
def config_group() -> None:
    """Inspect and validate config.json."""

@config_group.command("validate")
@click.option("--file", "config_file", type=click.Path(), default=None,
              help="Path to config.json (default: config/config.json)")
@click.pass_context
def validate(ctx: click.Context, config_file: str | None) -> None:
    """Validate config.json against the pydantic schema."""
    from pydantic import ValidationError
    from src.config_models import ConfigSchema

    if config_file is None:
        pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        root_dir = os.path.dirname(pkg_dir)
        config_file = os.path.join(root_dir, "config", "config.json")

    if not os.path.exists(config_file):
        echo_error(ctx, f"Config file not found: {config_file}")
        if is_json(ctx):
            echo_json(ctx, {"valid": False, "errors": ["Config file not found"]})
        ctx.exit(EXIT_NOINPUT)
        return

    with open(config_file, "r", encoding="utf-8") as f:
        try:
            raw = json.load(f)
        except json.JSONDecodeError as e:
            echo_error(ctx, f"Malformed JSON: {e}")
            if is_json(ctx):
                echo_json(ctx, {"valid": False, "errors": [str(e)]})
            ctx.exit(EXIT_DATAERR)
            return

    try:
        ConfigSchema.model_validate(raw)
    except ValidationError as e:
        error_list = [
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
            for err in e.errors()
        ]
        if is_json(ctx):
            echo_json(ctx, {"valid": False, "errors": error_list})
        else:
            echo_error(ctx, f"Found {e.error_count()} validation error(s):")
            console = Console(stderr=True)
            for err in e.errors():
                loc = ".".join(str(p) for p in err["loc"])
                console.print(f"  [yellow]{loc}[/yellow]: {err['msg']} "
                             f"(input: [magenta]{err.get('input')!r}[/magenta])")
        ctx.exit(EXIT_CONFIG)
        return

    if is_json(ctx):
        echo_json(ctx, {"valid": True})
    elif not is_quiet(ctx):
        click.echo("config.json is valid")

@config_group.command("show")
@click.option("--section", type=str, default=None,
              help="Only show one section (e.g. api, smtp, web_gui)")
@click.pass_context
def show(ctx: click.Context, section: str | None) -> None:
    """Print the current (validated) config as pretty JSON."""
    from src.config import ConfigManager
    cm = ConfigManager()
    if section is None:
        data = cm.config
    elif section not in cm.config:
        echo_error(ctx, f"Unknown section: {section!r}. "
                   f"Valid sections: {', '.join(sorted(cm.config.keys()))}")
        ctx.exit(EXIT_USAGE)
        return
    else:
        data = cm.config[section]
    echo_json(ctx, data)
