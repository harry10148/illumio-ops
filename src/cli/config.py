"""`illumio-ops config ...` subcommand group."""
from __future__ import annotations

import json
import os

import click
from rich.console import Console


@click.group("config")
def config_group() -> None:
    """Inspect and validate config.json."""


@config_group.command("validate")
@click.option("--file", "config_file", type=click.Path(), default=None,
              help="Path to config.json (default: config/config.json)")
def validate(config_file: str | None) -> None:
    """Validate config.json against the pydantic schema."""
    from pydantic import ValidationError
    from src.config_models import ConfigSchema

    if config_file is None:
        pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        root_dir = os.path.dirname(pkg_dir)
        config_file = os.path.join(root_dir, "config", "config.json")

    console = Console()
    if not os.path.exists(config_file):
        console.print(f"[red]Config file not found:[/red] {config_file}")
        raise click.Abort()

    with open(config_file, "r", encoding="utf-8") as f:
        try:
            raw = json.load(f)
        except json.JSONDecodeError as e:
            console.print(f"[red]Malformed JSON:[/red] {e}")
            raise click.Abort()

    try:
        ConfigSchema.model_validate(raw)
    except ValidationError as e:
        console.print(f"[red]Found {e.error_count()} validation error(s):[/red]")
        for err in e.errors():
            loc = ".".join(str(p) for p in err["loc"])
            console.print(f"  [yellow]{loc}[/yellow]: {err['msg']} "
                         f"(input: [magenta]{err.get('input')!r}[/magenta])")
        raise click.Abort()

    console.print("[green]config.json is valid[/green]")


@config_group.command("show")
@click.option("--section", type=str, default=None,
              help="Only show one section (e.g. api, smtp, web_gui)")
def show(section: str | None) -> None:
    """Print the current (validated) config as pretty JSON."""
    from src.config import ConfigManager
    console = Console()
    cm = ConfigManager()
    if section is None:
        data = cm.config
    elif section not in cm.config:
        console.print(f"[red]Unknown section:[/red] {section!r}. "
                      f"Valid sections: {', '.join(sorted(cm.config.keys()))}")
        raise click.Abort()
    else:
        data = cm.config[section]
    console.print_json(data=data)
