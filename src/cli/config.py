"""`illumio-ops config ...` subcommand group."""
from __future__ import annotations

import json
import os

import click
from rich.console import Console

from src.cli._output import is_json, is_quiet, echo_error, echo_json, echo_warning
from src.cli._exit_codes import EXIT_NOINPUT, EXIT_DATAERR, EXIT_CONFIG, EXIT_USAGE
from src.i18n import t

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
        echo_error(ctx, t("cli_config_file_not_found", path=config_file))
        if is_json(ctx):
            echo_json(ctx, {"valid": False, "errors": ["Config file not found"]})
        ctx.exit(EXIT_NOINPUT)
        return

    with open(config_file, "r", encoding="utf-8") as f:
        try:
            raw = json.load(f)
        except json.JSONDecodeError as e:
            echo_error(ctx, t("cli_config_malformed_json", error=e))
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
            echo_error(ctx, t("cli_config_found_errors", count=e.error_count()))
            console = Console(stderr=True)
            for err in e.errors():
                loc = ".".join(str(p) for p in err["loc"])
                console.print(t("cli_config_validate_error_row", loc=loc,
                                msg=err["msg"], input=repr(err.get("input"))))
        ctx.exit(EXIT_CONFIG)
        return

    if is_json(ctx):
        echo_json(ctx, {"valid": True})
    elif not is_quiet(ctx):
        click.echo(t("cli_config_valid"))

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
        echo_error(ctx, t("cli_config_unknown_section_show", section=repr(section),
                          valid=', '.join(sorted(cm.config.keys()))))
        ctx.exit(EXIT_USAGE)
        return
    else:
        data = cm.config[section]
    echo_json(ctx, _mask_secrets(data))


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


def _mask_secrets(obj):
    """Recursively redact secret-named fields so `config show` never prints
    credentials in plaintext. Empty values are preserved so an unset secret
    stays visible as such."""
    if isinstance(obj, dict):
        return {
            k: ("[REDACTED]"
                if (isinstance(v, str) and v
                    and any(tok in k.lower() for tok in _SECRET_TOKENS))
                else _mask_secrets(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_mask_secrets(x) for x in obj]
    return obj


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
        echo_error(ctx, t("cli_config_key_format", name=repr(key)))
        ctx.exit(EXIT_USAGE)
        return

    section, field = parts

    if section not in _SETTABLE_SECTIONS:
        echo_error(ctx, t("cli_config_unknown_section_set", section=repr(section),
                          settable=', '.join(sorted(_SETTABLE_SECTIONS))))
        ctx.exit(EXIT_USAGE)
        return

    cm = ConfigManager()
    section_dict = cm.config.get(section, {})

    if field not in section_dict:
        echo_error(ctx, t("cli_config_unknown_field", field=repr(field),
                          section=repr(section),
                          available=', '.join(sorted(section_dict.keys()))))
        ctx.exit(EXIT_USAGE)
        return

    # Type coercion
    try:
        typed_value = _coerce_value(value, section_dict[field])
    except (ValueError, TypeError) as e:
        echo_error(ctx, t("cli_config_invalid_value", name=key, error=e))
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
        echo_error(ctx, t("cli_config_validation_failed", errors='; '.join(errors)))
        ctx.exit(EXIT_CONFIG)
        return

    # Persist
    cm.save()

    display_value = "[REDACTED]" if any(t in field.lower() for t in _SECRET_TOKENS) else value

    if is_json(ctx):
        echo_json(ctx, {"key": key, "value": display_value, "saved": True})
    elif not is_quiet(ctx):
        click.echo(t("cli_config_set", name=key, value=display_value))


# ---------------------------------------------------------------------------
# config login
# ---------------------------------------------------------------------------

@config_group.command("login")
@click.option("--url", default=None, help="PCE URL (e.g. https://pce.example.com:8443)")
@click.option("--key", default=None, help="API key")
@click.option("--secret", default=None, help="API secret", hide_input=True)
@click.option("--org-id", "org_id", default=None, help="Organisation ID (default: 1)")
@click.option("--deployment-type", "deployment_type",
              type=click.Choice(["saas", "on_prem"]), default=None,
              help=t("cli_config_login_deployment_type_help"))
@click.option("--console-url", "console_url", default=None,
              help=t("cli_config_login_console_url_help"))
@click.option("--no-interactive", "no_interactive", is_flag=True, default=False,
              help="Skip prompts; require --url, --key, --secret via options.")
@click.option("--pce-target-change", "pce_target_change",
              type=click.Choice(["flush", "same-pce"]), default=None,
              help="Required (with --no-interactive) when --url/--org-id name a "
                   "different PCE than the one currently configured: 'flush' "
                   "clears the cached data that belonged to the old one, "
                   "'same-pce' keeps it (same PCE, new address).")
@click.pass_context
def login_cmd(ctx: click.Context, url, key, secret, org_id, deployment_type,
              console_url, no_interactive, pce_target_change) -> None:
    """Set PCE API credentials (url, key, secret, org-id).

    Without --no-interactive, prompts for any value not supplied via options.
    With --no-interactive, --url, --key, and --secret are required.
    """
    from pydantic import ValidationError
    from src.config import ConfigManager
    from src import config_models
    from src.pce_target import normalize_org_id, normalize_pce_url, pce_target_changed

    if secret is not None and not is_json(ctx):
        # --secret on the command line lands in `ps` output and shell history.
        # Suppress in --json mode so machine-readable stdout stays clean.
        echo_warning(ctx, t("cli_config_secret_cli_warning"))

    # Read the current api block before anything below can mutate it — this
    # is the baseline the "did the target change" decision compares against,
    # and (for --no-interactive with no decision made) config must come out
    # of this command exactly as it went in.
    cm = ConfigManager()
    old_api = dict(cm.config.get("api", {}))

    if no_interactive:
        missing = [f for f, v in [("--url", url), ("--key", key), ("--secret", secret)]
                   if v is None]
        if missing:
            echo_error(ctx, t("cli_config_no_interactive_requires", missing=', '.join(missing)))
            ctx.exit(EXIT_USAGE)
            return
    else:
        current = old_api
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

    # An absent --org-id means "unchanged", exactly as it does on the other two
    # paths: the GUI passes None for a field the request omitted and the
    # settings menu keeps the stored value. This used to manufacture "1" and
    # hand it to the predicate, which turned a plain credential rotation on an
    # org-5 appliance into a target change; answering "same-pce" — the honest
    # answer for a rotation — then silently moved the appliance onto org 1
    # while keeping org 5's cache.
    stored_url = normalize_pce_url(url) if url is not None else old_api.get("url", "")
    stored_org_id = (normalize_org_id(org_id) if org_id is not None
                     else normalize_org_id(old_api.get("org_id", "1")))

    # Changing which PCE this appliance talks to is not an edit — the cache,
    # the ingestion positions, the archive files and the alert cooldowns all
    # carry the previous PCE's data with no marker saying so. Same predicate
    # POST /api/settings uses (src/pce_target.py), so the two paths agree.
    target_changed = pce_target_changed(old_api, url, org_id)
    if target_changed and pce_target_change is None:
        if no_interactive:
            # This is the path automation calls with nobody watching — default
            # to proceeding would be the same silent contamination the whole
            # guard exists to prevent, just with extra steps. Fail loud, write
            # nothing.
            echo_error(ctx, t("cli_config_login_pce_target_needs_choice"))
            ctx.exit(EXIT_USAGE)
            return
        pce_target_change = click.prompt(
            t("cli_config_login_pce_target_change_prompt"),
            type=click.Choice(["flush", "same-pce"]),
        )

    new_api = dict(old_api)
    new_api["url"] = stored_url
    new_api["key"] = key
    new_api["secret"] = secret
    new_api["org_id"] = stored_org_id
    if deployment_type is not None:
        new_api["deployment_type"] = deployment_type
    if console_url is not None:
        new_api["console_url"] = console_url

    try:
        validated_api = config_models.ApiSettings.model_validate(new_api)
    except ValidationError as e:
        errors = [f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
                  for err in e.errors()]
        echo_error(ctx, t("cli_config_validation_failed", errors='; '.join(errors)))
        ctx.exit(EXIT_CONFIG)
        return

    validated_api_dict = validated_api.model_dump()
    runtime_connection_changed = any(
        value is not None
        and old_api.get(field, validated_api_dict[field]) != validated_api_dict[field]
        for field, value in (
            ("deployment_type", deployment_type),
            ("console_url", console_url),
        )
    )
    restart_required = target_changed or runtime_connection_changed

    if target_changed and pce_target_change == "flush":
        # Before cm.save(), the same order POST /api/settings uses: past this
        # line the stored connection names the new PCE, so the guard never
        # fires for this edit again and nothing would ever come back to finish
        # an interrupted clear — the old PCE's cache and fetch positions would
        # stay, permanently and silently, exactly the contamination this
        # guard exists to prevent. Failing here instead costs a re-run, whose
        # clear is idempotent.
        from src.pce_cache.flush import flush_pce_derived_state
        from src.config import resolve_state_file
        try:
            flush_pce_derived_state(cm.models.pce_cache.db_path, resolve_state_file())
        except Exception as exc:
            echo_error(ctx, t("cli_config_login_pce_flush_failed", error=str(exc)[:200]))
            ctx.exit(EXIT_CONFIG)
            return

    cm.config["api"] = validated_api_dict
    cm.save()

    if target_changed and pce_target_change == "same-pce":
        # AFTER cm.save(), unlike the flush above, and for the opposite reason.
        # The flush must precede the save so an interrupted clear leaves the old
        # connection stored and the operator is made to finish it. Here there is
        # nothing to lose: the rows stay either way, and rebinding to a target
        # that had not been saved yet would name a PCE the appliance is not using.
        #
        # Without this the binding keeps the old address while the config holds
        # the new one, and every ingest afterwards refuses to write — a supported
        # answer would silently stop monitoring.
        from src.pce_cache.provenance import rebind
        try:
            rebind(cm.models.pce_cache.db_path, validated_api_dict)
        except Exception as exc:  # noqa: BLE001
            # Not fatal: the connection is saved and correct. A stale binding
            # surfaces as a loud, actionable ingest refusal rather than as
            # silent contamination, so reporting beats rolling back a good save.
            echo_warning(ctx, t("cli_config_login_pce_rebind_failed",
                                error=str(exc)[:200]))

    if restart_required and not is_json(ctx) and not is_quiet(ctx):
        # Nothing here reaches a running monitor service: it holds its own
        # ConfigManager for the life of the process and never reloads it.
        warning_key = ("cli_config_login_pce_restart_required" if target_changed
                       else "cli_config_login_connection_restart_required")
        echo_warning(ctx, t(warning_key))

    if is_json(ctx):
        echo_json(ctx, {"url": stored_url, "org_id": stored_org_id, "saved": True,
                        "restart_required": restart_required})
    elif not is_quiet(ctx):
        click.echo(t("cli_config_login_saved", url=stored_url, org_id=stored_org_id))
