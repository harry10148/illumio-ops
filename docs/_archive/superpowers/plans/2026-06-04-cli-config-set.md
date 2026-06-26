# CLI Config Set & Login Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `config set <key> <value>` and `config login` sub-commands so operators can change PCE login credentials and any config field from the CLI without manually editing config.json.

**Architecture:** Two new sub-commands under the existing `config_group` in `src/cli/config.py`. A shared `_set_nested(d, dotpath, value)` helper navigates the in-memory config dict, pydantic validates the whole section after mutation, then `cm.save()` atomically writes config.json. `config login` wraps `config set` calls for the four api fields with interactive prompts + optional connection test.

**Tech Stack:** Click, Pydantic v2, existing `ConfigManager`, existing `_output.py` helpers, `click.testing.CliRunner` for tests.

---

## File Map

| Action | Path |
|--------|------|
| Modify | `src/cli/config.py` — add `set` and `login` commands |
| Modify | `tests/test_cli_config_cmd.py` — add new test cases |

---

### Task 1: `_set_nested` helper + `config set` command

The helper navigates a dot-path (`api.url`) into the live `cm.config` dict,
applies the typed value, validates the affected section via pydantic, then
persists with `cm.save()`.

**Files:**
- Modify: `src/cli/config.py`
- Modify: `tests/test_cli_config_cmd.py`

#### Settable keys (dot-path → section model)

| Dot-path | Section model |
|----------|--------------|
| `api.url` | `ApiSettings` |
| `api.key` | `ApiSettings` |
| `api.secret` | `ApiSettings` |
| `api.org_id` | `ApiSettings` |
| `api.verify_ssl` | `ApiSettings` |
| `api.profile` | `ApiSettings` |
| `smtp.host` | `SmtpSettings` |
| `smtp.port` | `SmtpSettings` |
| `smtp.user` | `SmtpSettings` |
| `smtp.password` | `SmtpSettings` |
| `smtp.enable_auth` | `SmtpSettings` |
| `smtp.enable_tls` | `SmtpSettings` |
| `settings.language` | `GeneralSettings` |
| `settings.theme` | `GeneralSettings` |
| `settings.timezone` | `GeneralSettings` |
| `web_gui.username` | `WebGuiSettings` |
| `web_gui.password` | `WebGuiSettings` |

- [ ] **Step 1: Write failing tests**

```python
# tests/test_cli_config_cmd.py  — append after existing tests

import json
from unittest.mock import MagicMock, patch, call
from click.testing import CliRunner
from src.cli.config import config_group
from src.cli._exit_codes import EXIT_USAGE, EXIT_DATAERR, EXIT_CONFIG


def _make_cm(api_url="https://pce.test:8443"):
    """Return a minimal mock ConfigManager whose .config is a real dict."""
    cm = MagicMock()
    cm.config = {
        "api": {"url": api_url, "org_id": "1", "key": "", "secret": "",
                "profile": "production", "verify_ssl": True},
        "smtp": {"host": "localhost", "port": 25, "user": "", "password": "",
                 "enable_auth": False, "enable_tls": False},
        "settings": {"language": "en", "theme": "light", "timezone": "local",
                     "enable_health_check": True, "dashboard_queries": []},
        "web_gui": {"username": "illumio", "password": "", "secret_key": "",
                    "allowed_ips": [], "must_change_password": False,
                    "tls": {"enabled": True, "cert_file": "", "key_file": "",
                            "self_signed": True, "auto_renew": True,
                            "auto_renew_days": 30, "min_version": "TLSv1.2",
                            "ciphers": None, "key_algorithm": "ecdsa-p256",
                            "validity_days": 397}},
    }
    cm.config_file = "/fake/config.json"
    return cm


def test_config_set_api_url(runner):
    cm = _make_cm()
    with patch("src.config.ConfigManager", return_value=cm):
        result = runner.invoke(config_group, ["set", "api.url", "https://new.pce:8443"])
    assert result.exit_code == 0
    cm.save.assert_called_once()
    assert cm.config["api"]["url"] == "https://new.pce:8443"


def test_config_set_unknown_key_exits_usage(runner):
    cm = _make_cm()
    with patch("src.config.ConfigManager", return_value=cm):
        result = runner.invoke(config_group, ["set", "no_such_section.field", "x"])
    assert result.exit_code == EXIT_USAGE


def test_config_set_invalid_url_exits_config(runner):
    cm = _make_cm()
    with patch("src.config.ConfigManager", return_value=cm):
        result = runner.invoke(config_group, ["set", "api.url", "ftp://bad"])
    assert result.exit_code == EXIT_CONFIG


def test_config_set_invalid_field_exits_usage(runner):
    cm = _make_cm()
    with patch("src.config.ConfigManager", return_value=cm):
        result = runner.invoke(config_group, ["set", "api.nonexistent", "x"])
    assert result.exit_code == EXIT_USAGE


def test_config_set_bool_coercion(runner):
    cm = _make_cm()
    with patch("src.config.ConfigManager", return_value=cm):
        result = runner.invoke(config_group, ["set", "smtp.enable_auth", "true"])
    assert result.exit_code == 0
    assert cm.config["smtp"]["enable_auth"] is True


def test_config_set_json_output(runner):
    cm = _make_cm()
    with patch("src.config.ConfigManager", return_value=cm):
        result = runner.invoke(config_group, ["--json", "set", "api.org_id", "5"])
    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert parsed["key"] == "api.org_id"
    assert parsed["value"] == "5"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_cli_config_cmd.py -k "config_set" -v 2>&1 | tail -20
```
Expected: FAIL — `config set` command not found.

- [ ] **Step 3: Implement `_set_nested` and `config set` in `src/cli/config.py`**

Add after the existing `show` command:

```python
# Allowed sections and their pydantic model imports
_SETTABLE_SECTIONS = {
    "api", "smtp", "settings", "web_gui",
}

_BOOL_VALUES = {"true": True, "false": False, "1": True, "0": False, "yes": True, "no": False}


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
    Secrets (key, secret, password) are redacted from output.
    """
    from pydantic import ValidationError
    from src.config import ConfigManager

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
    _SECTION_MODELS = {
        "api": "ApiSettings",
        "smtp": "SmtpSettings",
        "settings": "GeneralSettings",
        "web_gui": "WebGuiSettings",
    }
    try:
        from src import config_models
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

    _SECRET_TOKENS = {"key", "secret", "password", "token"}
    display_value = "[REDACTED]" if any(t in field.lower() for t in _SECRET_TOKENS) else value

    if is_json(ctx):
        echo_json(ctx, {"key": key, "value": display_value, "saved": True})
    elif not is_quiet(ctx):
        click.echo(f"Set {key} = {display_value}")
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_cli_config_cmd.py -k "config_set" -v 2>&1 | tail -20
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cli/config.py tests/test_cli_config_cmd.py
git commit -m "feat(cli): add config set command with pydantic validation"
```

---

### Task 2: `config login` interactive wizard

Convenience wrapper around `config set` for the four PCE API credentials.
Prompts interactively; `--no-interactive` accepts values as options for
scripted use.

**Files:**
- Modify: `src/cli/config.py`
- Modify: `tests/test_cli_config_cmd.py`

- [ ] **Step 1: Write failing tests**

```python
# append to tests/test_cli_config_cmd.py

def test_config_login_non_interactive_sets_all_fields(runner):
    """--no-interactive with all options sets api fields and saves."""
    cm = _make_cm()
    with patch("src.config.ConfigManager", return_value=cm):
        result = runner.invoke(config_group, [
            "login",
            "--url", "https://pce.prod:8443",
            "--key", "mykey",
            "--secret", "mysecret",
            "--org-id", "3",
            "--no-interactive",
        ])
    assert result.exit_code == 0
    assert cm.config["api"]["url"] == "https://pce.prod:8443"
    assert cm.config["api"]["key"] == "mykey"
    assert cm.config["api"]["secret"] == "mysecret"
    assert cm.config["api"]["org_id"] == "3"
    cm.save.assert_called_once()


def test_config_login_invalid_url_exits_config(runner):
    """--url with bad scheme should exit EXIT_CONFIG."""
    cm = _make_cm()
    with patch("src.config.ConfigManager", return_value=cm):
        result = runner.invoke(config_group, [
            "login",
            "--url", "ftp://bad",
            "--key", "k",
            "--secret", "s",
            "--no-interactive",
        ])
    assert result.exit_code == EXIT_CONFIG


def test_config_login_json_output(runner):
    cm = _make_cm()
    with patch("src.config.ConfigManager", return_value=cm):
        result = runner.invoke(config_group, [
            "--json", "login",
            "--url", "https://pce.test:8443",
            "--key", "k",
            "--secret", "s",
            "--no-interactive",
        ])
    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert parsed["saved"] is True
    assert parsed["url"] == "https://pce.test:8443"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_cli_config_cmd.py -k "config_login" -v 2>&1 | tail -20
```
Expected: FAIL — `login` command not found.

- [ ] **Step 3: Implement `config login` in `src/cli/config.py`**

Add after the `set_cmd` command:

```python
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
        cm_tmp = ConfigManager()
        current = cm_tmp.config.get("api", {})
        if url is None:
            url = click.prompt("PCE URL", default=current.get("url", "https://pce.example.com:8443"))
        if key is None:
            key = click.prompt("API key", default=current.get("key", ""), show_default=False)
        if secret is None:
            secret = click.prompt("API secret", default="", hide_input=True, show_default=False)
        if org_id is None:
            org_id = click.prompt("Org ID", default=current.get("org_id", "1"))

    if org_id is None:
        org_id = "1"

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
```

- [ ] **Step 4: Run all config CLI tests**

```bash
pytest tests/test_cli_config_cmd.py -v 2>&1 | tail -30
```
Expected: all PASS.

- [ ] **Step 5: Manual smoke test**

```bash
python3 -c "from src.cli.root import cli; cli(['config', '--help'], standalone_mode=False)" 2>&1
```
Expected output includes: `login`, `set`, `show`, `validate`

```bash
python3 -c "from src.cli.root import cli; cli(['config', 'set', '--help'], standalone_mode=False)" 2>&1
```
Expected: shows KEY and VALUE args with docstring.

```bash
python3 -c "from src.cli.root import cli; cli(['config', 'login', '--help'], standalone_mode=False)" 2>&1
```
Expected: shows `--url`, `--key`, `--secret`, `--org-id`, `--no-interactive`.

- [ ] **Step 6: Commit**

```bash
git add src/cli/config.py tests/test_cli_config_cmd.py
git commit -m "feat(cli): add config login wizard"
```

---

## Self-Review

### Spec Coverage
- [x] `config set api.url` / `api.key` / `api.secret` — Task 1
- [x] Pydantic validation before save — Task 1 `_coerce_value` + `model_validate`
- [x] Secret redaction in output — Task 1 `display_value`
- [x] Interactive login wizard — Task 2
- [x] Non-interactive / scripted login — Task 2 `--no-interactive`
- [x] `--json` output for both — both tasks
- [x] Exit code consistency — `EXIT_USAGE` / `EXIT_CONFIG` / `EXIT_DATAERR`

### Placeholder Scan
None found — all steps contain complete code.

### Type Consistency
- `_make_cm()` fixture produces a dict matching `ApiSettings` / `SmtpSettings` / `GeneralSettings` / `WebGuiSettings` field names
- `_SECTION_MODELS` maps section key → class name; `getattr(config_models, ...)` resolves at runtime so renaming the model will surface loudly
- `_coerce_value` returns `bool` / `int` / `float` / `str` matching pydantic field types
