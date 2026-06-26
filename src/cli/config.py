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

    # Drop keys removed in newer versions before validating, so `config validate`
    # matches what ConfigManager.load() actually accepts at runtime (it strips
    # the same deprecated keys). Without this, a deployed config that loads fine
    # would be falsely reported invalid (e.g. web_gui.tls.http_redirect_port).
    from src.config import _strip_deprecated_keys
    _strip_deprecated_keys(raw)

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


# ---------------------------------------------------------------------------
# config set
# ---------------------------------------------------------------------------

_SETTABLE_SECTIONS = {"api", "smtp", "settings", "web_gui"}

_BOOL_VALUES = {"true": True, "false": False, "1": True, "0": False, "yes": True, "no": False}

_SECTION_MODELS = {
    "api": "ApiSettings",
    "smtp": "SmtpSettings",
    "settings": "GeneralSettings",
    "web_gui": "WebGuiSettings",
}

_SECRET_TOKENS = {"key", "secret", "password", "token"}


def _coerce_value(raw: str, current) -> object:
    """Coerce raw string to the type of the current field value."""
    if isinstance(current, bool):
        v = raw.lower()
        if v not in _BOOL_VALUES:
            raise ValueError(f"Expected true/false, got {raw!r}")
        return _BOOL_VALUES[v]
    if isinstance(current, int):
        return int(raw)
    if isinstance(current, float):
        return float(raw)
    return raw


@config_group.command("set")
@click.argument("key")
@click.argument("value")
@click.pass_context
def set_cmd(ctx: click.Context, key: str, value: str) -> None:
    """Set a config value by dot-path KEY (e.g. api.url, api.key, smtp.host).

    Changes are validated against the pydantic schema before saving.
    Secrets (key, secret, password, token) are redacted from output.
    """
    from pydantic import ValidationError
    from src.config import ConfigManager
    from src import config_models

    # Parse KEY into section.field
    parts = key.split(".", 1)
    if len(parts) != 2:
        echo_error(ctx, f"Key must be in section.field format (got: {key!r}). "
                        f"Example: api.url")
        ctx.exit(EXIT_USAGE)
        return

    section, field = parts

    if section not in _SETTABLE_SECTIONS:
        echo_error(ctx, f"Unknown section {section!r}. "
                        f"Settable sections: {', '.join(sorted(_SETTABLE_SECTIONS))}")
        ctx.exit(EXIT_USAGE)
        return

    cm = ConfigManager()
    section_dict = cm.config.get(section, {})

    if field not in section_dict:
        echo_error(ctx, f"Unknown field {field!r} in section {section!r}. "
                        f"Available: {', '.join(sorted(section_dict.keys()))}")
        ctx.exit(EXIT_USAGE)
        return

    # Type coercion
    try:
        typed_value = _coerce_value(value, section_dict[field])
    except (ValueError, TypeError) as e:
        echo_error(ctx, f"Invalid value for {key}: {e}")
        ctx.exit(EXIT_DATAERR)
        return

    # Apply to in-memory dict
    cm.config[section][field] = typed_value

    # Validate the affected section via pydantic
    try:
        model_cls = getattr(config_models, _SECTION_MODELS[section])
        model_cls.model_validate(cm.config[section])
    except ValidationError as e:
        errors = [f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
                  for err in e.errors()]
        echo_error(ctx, f"Validation failed: {'; '.join(errors)}")
        ctx.exit(EXIT_CONFIG)
        return

    # Persist
    cm.save()

    display_value = "[REDACTED]" if any(t in field.lower() for t in _SECRET_TOKENS) else value

    if is_json(ctx):
        echo_json(ctx, {"key": key, "value": display_value, "saved": True})
    elif not is_quiet(ctx):
        click.echo(f"Set {key} = {display_value}")


# ---------------------------------------------------------------------------
# config login
# ---------------------------------------------------------------------------

@config_group.command("login")
@click.option("--url", default=None, help="PCE URL (e.g. https://pce.example.com:8443)")
@click.option("--key", default=None, help="API key")
@click.option("--secret", default=None, help="API secret", hide_input=True)
@click.option("--org-id", "org_id", default=None, help="Organisation ID (default: 1)")
@click.option("--no-interactive", "no_interactive", is_flag=True, default=False,
              help="Skip prompts; require --url, --key, --secret via options.")
@click.pass_context
def login_cmd(ctx: click.Context, url, key, secret, org_id, no_interactive) -> None:
    """Set PCE API credentials (url, key, secret, org-id).

    Without --no-interactive, prompts for any value not supplied via options.
    With --no-interactive, --url, --key, and --secret are required.
    """
    from pydantic import ValidationError
    from src.config import ConfigManager
    from src import config_models

    if no_interactive:
        missing = [f for f, v in [("--url", url), ("--key", key), ("--secret", secret)]
                   if v is None]
        if missing:
            echo_error(ctx, f"--no-interactive requires: {', '.join(missing)}")
            ctx.exit(EXIT_USAGE)
            return
    else:
        cm = ConfigManager()
        current = cm.config.get("api", {})
        if url is None:
            url = click.prompt("PCE URL", default=current.get("url", "https://pce.example.com:8443"))
        if key is None:
            key = click.prompt("API key", default=current.get("key", ""), show_default=False)
        if secret is None:
            # Blank input keeps the stored secret (mirrors url/key/org_id above);
            # default="" used to silently wipe it when an operator pressed Enter.
            secret = click.prompt("API secret", default=current.get("secret", ""),
                                  hide_input=True, show_default=False)
        if org_id is None:
            org_id = click.prompt("Org ID", default=current.get("org_id", "1"))

    if org_id is None:
        org_id = "1"

    if no_interactive:
        cm = ConfigManager()
    cm.config["api"]["url"] = url
    cm.config["api"]["key"] = key
    cm.config["api"]["secret"] = secret
    cm.config["api"]["org_id"] = str(org_id)

    try:
        config_models.ApiSettings.model_validate(cm.config["api"])
    except ValidationError as e:
        errors = [f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
                  for err in e.errors()]
        echo_error(ctx, f"Validation failed: {'; '.join(errors)}")
        ctx.exit(EXIT_CONFIG)
        return

    cm.save()

    if is_json(ctx):
        echo_json(ctx, {"url": url, "org_id": str(org_id), "saved": True})
    elif not is_quiet(ctx):
        click.echo(f"PCE login saved: {url} (org {org_id})")
