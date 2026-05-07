"""'illumio-ops completion install [shell]' — print the source line for the
user's shell rc, pointing at the bundled completion file.

Track C Task 4 (b8): closes §3.2.4 CLI rule 9 (--help discoverability).
"""
from __future__ import annotations

import pathlib

import click

from src.cli._output import echo_error
from src.cli._exit_codes import EXIT_USAGE


def _completions_dir() -> pathlib.Path:
    """Return absolute path to scripts/completions/ in this checkout."""
    here = pathlib.Path(__file__).resolve()
    project_root = here.parent.parent.parent
    return project_root / "scripts" / "completions"


_FILES = {
    "bash": "illumio-ops.bash",
    "zsh": "_illumio-ops",
    "fish": "illumio-ops.fish",
}


@click.group("completion")
def completion_group() -> None:
    """Manage shell completion installation (bash, zsh, fish)."""


@completion_group.command("install")
@click.argument("shell", type=click.Choice(["bash", "zsh", "fish"], case_sensitive=False))
@click.pass_context
def completion_install(ctx: click.Context, shell: str) -> None:
    """Print the source/fpath line to add to your shell rc.

    Supported shells: bash, zsh, fish.

    Example:

        $ illumio-ops completion install bash
        # Add this to ~/.bashrc:
        source /abs/path/to/scripts/completions/illumio-ops.bash
    """
    shell = shell.lower()
    if shell not in _FILES:
        echo_error(ctx, f"Unsupported shell: {shell}")
        ctx.exit(EXIT_USAGE)
    path = _completions_dir() / _FILES[shell]
    if not path.exists():
        echo_error(ctx, f"Completion file missing: {path}")
        ctx.exit(EXIT_USAGE)
    if shell == "bash":
        click.echo("# Add this to ~/.bashrc:")
        click.echo(f"source {path}")
    elif shell == "zsh":
        click.echo("# Add this to ~/.zshrc (before 'compinit'):")
        click.echo(f"# Completion file: {path}")
        click.echo(f"fpath=({path.parent} $fpath)")
        click.echo("# Then re-run: autoload -U compinit && compinit")
    elif shell == "fish":
        click.echo("# Copy or symlink into ~/.config/fish/completions/:")
        click.echo(f"cp {path} ~/.config/fish/completions/illumio-ops.fish")
