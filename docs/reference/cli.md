---
title: CLI Reference
audience: [operator, api, developer]
last_verified: 2026-05-15
verified_against:
  - src/cli/
  - src/cli/menus/
  - docs/cli-command-map.md (legacy, folded in)
  - python illumio-ops.py --help
  - python illumio-ops.py <subcmd> --help (each subcommand)
  - commit 060a32f
related_docs:
  - rest-api.md
  - glossary.md
  - ../user-guide/reports.md
  - ../user-guide/siem-integration.md
---

> **[English](cli.md)** | **[繁體中文](cli_zh.md)**
> 📍 [INDEX](../INDEX.md) › Reference › CLI
> 🔍 Last verified **2026-05-15** against commit `060a32f` — see frontmatter for sources

# CLI Reference

---

## Synopsis

```
illumio-ops [GLOBAL FLAGS] <subcommand> [ARGS...]
```

All credentials and PCE connection settings are read from `config/config.json`.
The CLI does **not** accept PCE credentials as flags — configure them in the file
(see [Environment variables](#environment-variables) for the one override that exists).

**Legacy argparse entrypoint** — flags such as `--monitor`, `--gui`, `--report`, etc.
remain supported for backward compatibility but are no longer the canonical interface.
Prefer the subcommand form shown throughout this document.

---

## Global flags

These flags may be placed before the subcommand:

```
illumio-ops [--json] [-q] [-v] <subcommand> [ARGS...]
```

| Flag | Short | Description |
|------|-------|-------------|
| `--json` | | Emit machine-readable JSON to stdout (one object per result). Errors still go to stderr as JSON. |
| `--quiet` | `-q` | Suppress non-essential output. Errors still go to stderr. |
| `--verbose` | `-v` | Verbose output, including debug-level details. |
| `--help` | `-h` | Show help message and exit. |

> **Note:** `--lang` is **not** a CLI flag. Language is set via `settings.language` in
> `config/config.json`. The env var `ILLUMIO_OPS_I18N_STRICT` (see
> [Environment variables](#environment-variables)) controls i18n strictness in report output only.

---

## Subcommands

### cache

PCE cache management — backfill, status, retention.

```
illumio-ops cache <subcommand> [OPTIONS]
```

#### cache backfill

Backfill the PCE cache from the API for a historical date range.

| Option | Description |
|--------|-------------|
| `-h, --help` | Show help and exit. |

```bash
illumio-ops cache backfill
illumio-ops --json cache backfill
```

#### cache status

Show cache row counts and last-sync timestamps.

| Option | Description |
|--------|-------------|
| `-h, --help` | Show help and exit. |

```bash
illumio-ops cache status
illumio-ops --json cache status
```

#### cache retention

Show configured cache retention policy, or run it immediately.

| Option | Description |
|--------|-------------|
| `-h, --help` | Show help and exit. |

```bash
illumio-ops cache retention
```

---

### completion

Manage shell completion installation (bash, zsh, fish).

```
illumio-ops completion <subcommand> [OPTIONS]
```

#### completion install

Print the `source`/`fpath` line to add to your shell rc.

```
illumio-ops completion install {bash|zsh|fish}
```

| Option | Description |
|--------|-------------|
| `-h, --help` | Show help and exit. |

```bash
# Print the line to add to ~/.bashrc:
illumio-ops completion install bash

# Print the line to add to ~/.zshrc:
illumio-ops completion install zsh
```

---

### config

Inspect and validate `config/config.json`.

```
illumio-ops config <subcommand> [OPTIONS]
```

#### config show

Print the current (validated) config as pretty JSON.

| Option | Description |
|--------|-------------|
| `--section TEXT` | Only show one section (e.g. `api`, `smtp`, `web_gui`). |
| `-h, --help` | Show help and exit. |

```bash
illumio-ops config show
illumio-ops config show --section api
illumio-ops --json config show --section siem
```

#### config validate

Validate `config.json` against the pydantic schema.

| Option | Description |
|--------|-------------|
| `--file PATH` | Path to config.json (default: `config/config.json`). |
| `-h, --help` | Show help and exit. |

```bash
illumio-ops config validate
illumio-ops config validate --file /etc/illumio/config.json
```

---

### gui

Launch the Web GUI (equivalent to the legacy `--gui` flag).

```
illumio-ops gui [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `-p, --port INTEGER` | HTTP port to listen on. |
| `-h, --host TEXT` | Bind address (default from config). |
| `--help` | Show help and exit. |

```bash
illumio-ops gui
illumio-ops gui --port 8443 --host 0.0.0.0
```

---

### monitor

Run the headless monitoring daemon (equivalent to the legacy `--monitor` flag).

```
illumio-ops monitor [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `-i, --interval INTEGER` | Minutes between cycles. |
| `-h, --help` | Show help and exit. |

```bash
illumio-ops monitor
illumio-ops monitor --interval 10
```

---

### monitor-gui

Run the headless monitor and Web GUI together (equivalent to the legacy `--monitor-gui` flag).

```
illumio-ops monitor-gui [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `-i, --interval INTEGER` | Minutes between monitor cycles. |
| `-p, --port INTEGER` | GUI port. |
| `--host TEXT` | GUI bind host. |
| `-h, --help` | Show help and exit. |

```bash
illumio-ops monitor-gui
illumio-ops monitor-gui --interval 15 --port 8443
```

---

### report

Generate reports. Nine subcommands: `traffic`, `security`, `inventory`, `audit`, `ven-status`, `policy-usage`, `app-summary`, `resolve`, `policy-diff`.

```
illumio-ops report <subcommand> [OPTIONS]
```

Canonical subcommand names match the WebUI button labels. The `generate-*` forms are aliases
(see [Subcommand aliases](#subcommand-aliases)).

#### report traffic

Generate a Traffic Flow Report.

| Option | Description |
|--------|-------------|
| `--source [api\|csv]` | Data source. |
| `--file PATH` | Input file path (when `--source csv`). |
| `--format [html\|csv\|pdf\|xlsx\|all]` | Output format. |
| `--output-dir PATH` | Directory to write the report. |
| `--email` | E-mail the report after generation. |
| `--profile [security_risk\|network_inventory]` | Traffic report profile. |
| `-h, --help` | Show help and exit. |

```bash
illumio-ops report traffic --format html --output-dir /tmp/reports
illumio-ops report traffic --source csv --file flows.csv --format xlsx
```

#### report security

Generate a Security Risk Report — B/L/R rule findings over PCE traffic flows, with an optional V-E vulnerability-exposure section (pass a scan CSV via `--vuln-csv`).

```bash
illumio-ops report security --format html --output-dir /tmp/reports
illumio-ops report security --vuln-csv qualys-export.csv --format xlsx
```

#### report inventory

Generate a Network & Traffic Inventory Report (Workloads, labels, and observed services).

```bash
illumio-ops report inventory --format xlsx
```

#### report audit

Generate an Audit Report.

| Option | Description |
|--------|-------------|
| `--start-date TEXT` | Start date in `YYYY-MM-DD`. |
| `--end-date TEXT` | End date in `YYYY-MM-DD`. |
| `--format [html\|csv\|pdf\|xlsx\|all]` | Output format. |
| `--output-dir PATH` | Directory to write the report. |
| `-h, --help` | Show help and exit. |

```bash
illumio-ops report audit --start-date 2026-05-01 --end-date 2026-05-15
illumio-ops report audit --format xlsx --output-dir /var/reports
```

#### report ven-status

Generate a VEN Status Report.

| Option | Description |
|--------|-------------|
| `--format [html\|csv\|pdf\|xlsx\|all]` | Output format. |
| `--output-dir PATH` | Directory to write the report. |
| `-h, --help` | Show help and exit. |

```bash
illumio-ops report ven-status --format html
illumio-ops --json report ven-status
```

#### report policy-usage

Generate a Policy Usage Report.

| Option | Description |
|--------|-------------|
| `--source [api\|csv]` | Data source. |
| `--file PATH` | Input file path (when `--source csv`). |
| `--start-date TEXT` | Start date in `YYYY-MM-DD`. |
| `--end-date TEXT` | End date in `YYYY-MM-DD`. |
| `--format [html\|csv\|pdf\|xlsx\|all]` | Output format. |
| `--output-dir PATH` | Directory to write the report. |
| `-h, --help` | Show help and exit. |

```bash
illumio-ops report policy-usage --start-date 2026-05-01 --format xlsx
illumio-ops report policy-usage --source csv --file rules.csv
```

#### report app-summary

Generate an App Summary Report for a single App Label (inbound / outbound view). `--app` is required; `--days` sets the traffic lookback window.

```bash
illumio-ops report app-summary --app payments --env prod --days 7
```

#### report resolve

Resolve ACTIVE label-based Policy into IP-level firewall rules. Output `--format` is `json`, `csv`, or `all`.

```bash
illumio-ops report resolve --format json
```

#### report policy-diff

Generate a Policy Diff Report (DRAFT vs ACTIVE, Ruleset / Rule scope). Output `--format` is `html`, `csv`, or `all`; `--attribution-days` sets the audit-event lookback for operator attribution.

```bash
illumio-ops report policy-diff --format html --attribution-days 30
```

---

### rule

Inspect and edit monitoring rules.

```
illumio-ops rule <subcommand> [OPTIONS]
```

#### rule list

List configured monitoring rules.

| Option | Description |
|--------|-------------|
| `--type [event\|traffic\|bandwidth\|volume\|system\|all]` | Filter by rule type. |
| `--enabled-only` | Show only enabled rules. |
| `-h, --help` | Show help and exit. |

```bash
illumio-ops rule list
illumio-ops rule list --type traffic --enabled-only
illumio-ops --json rule list
```

#### rule edit

Interactively edit a rule by its 1-based index.

```
illumio-ops rule edit [OPTIONS] RULE_ID
```

| Option | Description |
|--------|-------------|
| `--no-preview` | Skip the diff preview before save. |
| `-h, --help` | Show help and exit. |

```bash
illumio-ops rule edit 3
illumio-ops rule edit 3 --no-preview
```

---

### shell

Launch the interactive menu. This is the only path for features not exposed as CLI
subcommands: **TLS certificate management**, **PCE profile management**, and
**rule-scheduler configuration** are accessible only via the interactive shell.

```
illumio-ops shell
```

| Option | Description |
|--------|-------------|
| `-h, --help` | Show help and exit. |

```bash
illumio-ops shell
```

> **Note on unwired features:** `tls`, `pce` (profile management), and `rule-scheduler`
> are **not** wired as top-level CLI subcommands. They are interactive-shell-only paths,
> accessible by running `illumio-ops shell` and navigating the menu. Do not attempt
> to invoke them directly.

---

### siem

SIEM forwarder management.

```
illumio-ops siem <subcommand> [OPTIONS]
```

#### siem status

Show per-destination dispatch counts. The destination set is the union of configured
destinations and destinations observed in the `SiemDispatch` table — matching what the
WebUI integrations tab shows.

| Option | Description |
|--------|-------------|
| `-h, --help` | Show help and exit. |

```bash
illumio-ops siem status
illumio-ops --json siem status
```

#### siem test

Send a synthetic test event to a destination and report success/fail.

```
illumio-ops siem test [OPTIONS] DESTINATION
```

| Option | Description |
|--------|-------------|
| `-h, --help` | Show help and exit. |

```bash
illumio-ops siem test splunk-prod
```

#### siem dlq

List Dead Letter Queue (DLQ) entries for a destination.

| Option | Description |
|--------|-------------|
| `--dest TEXT` | Destination name. **Required.** |
| `--limit INTEGER` | Max entries to show (default: 50). |
| `-h, --help` | Show help and exit. |

```bash
illumio-ops siem dlq --dest splunk-prod
illumio-ops siem dlq --dest splunk-prod --limit 100
illumio-ops --json siem dlq --dest splunk-prod
```

#### siem replay

Requeue DLQ entries for a destination as pending dispatch rows.

| Option | Description |
|--------|-------------|
| `--dest TEXT` | Destination name. **Required.** |
| `--limit INTEGER` | Max DLQ entries to replay (default: 100). |
| `-h, --help` | Show help and exit. |

```bash
illumio-ops siem replay --dest splunk-prod
illumio-ops siem replay --dest splunk-prod --limit 200
```

#### siem purge

Delete DLQ entries for a destination older than N days.

| Option | Description |
|--------|-------------|
| `--dest TEXT` | Destination name. **Required.** |
| `--older-than INTEGER` | Purge entries older than N days (default: 30). |
| `-h, --help` | Show help and exit. |

```bash
illumio-ops siem purge --dest splunk-prod
illumio-ops siem purge --dest splunk-prod --older-than 7
```

---

### status

Show daemon / scheduler / config status.

```
illumio-ops status
```

| Option | Description |
|--------|-------------|
| `-h, --help` | Show help and exit. |

```bash
illumio-ops status
illumio-ops --json status
```

---

### version

Print the illumio-ops version.

```
illumio-ops version
```

```bash
illumio-ops version
# illumio-ops 4.1.0
```

---

### workload

Inspect PCE workloads.

```
illumio-ops workload <subcommand> [OPTIONS]
```

#### workload list

Fetch and display workloads from the PCE.

| Option | Description |
|--------|-------------|
| `--env TEXT` | Filter by env label value (e.g. `prod`). |
| `--limit INTEGER` | Max rows to display (must be ≥ 1). |
| `--enforcement [full\|selective\|visibility_only\|idle\|all]` | Filter by enforcement mode. |
| `--managed-only` | Show only VEN-managed workloads. |
| `-h, --help` | Show help and exit. |

```bash
illumio-ops workload list
illumio-ops workload list --env prod --managed-only
illumio-ops --json workload list --enforcement full --limit 500
```

---

## Subcommand aliases

The following aliases are folded in from `docs/cli-command-map.md`. Aliases produce
identical output to their canonical equivalents; the canonical forms are preferred.

| Alias | Canonical | Notes |
|-------|-----------|-------|
| `report generate-traffic` | `report traffic` | Displays `(alias of traffic)` in `--help` |
| `report generate-audit` | `report audit` | Displays `(alias of audit)` in `--help` |
| `report generate-ven-status` | `report ven-status` | Displays `(alias of ven-status)` in `--help` |
| `report generate-policy-usage` | `report policy-usage` | Displays `(alias of policy-usage)` in `--help` |
| `illumio-ops` (no args) | `illumio-ops shell` | Deprecated bare call; emits hint pointing to `shell` |
| `--monitor` (legacy flag) | `monitor` subcommand | Argparse back-compat; routed via legacy handler |
| `--monitor-gui` (legacy flag) | `monitor-gui` subcommand | Argparse back-compat |
| `--gui` (legacy flag) | `gui` subcommand | Argparse back-compat |
| `--report` (legacy flag) | `report traffic` | Argparse back-compat; `--report-type` selects variant |

**Entry point reference** (from `cli-command-map.md`):

| Entry | Status | Notes |
|-------|--------|-------|
| `illumio-ops <subcommand>` | **Canonical** | Single command tree, Click-based |
| `illumio-ops shell` | **Canonical** | Explicit interactive menu |
| `illumio-ops` (no args) | Deprecated | Emits hint pointing to `shell`; still launches menu |
| `illumio-ops --monitor` etc. | Back-compat | Routed to legacy argparse handler |
| `python -m src.pce_cache_cli` | Not an entry | Interactive helper invoked from `src/main.py`; not standalone |
| `python -m src.siem_cli` | Not an entry | Same as above |
| `python -m src.rule_scheduler_cli` | Not an entry | Same as above |

---

## Exit codes

Exit codes follow BSD `sysexits.h` conventions. Source: `src/cli/_exit_codes.py`.

| Code | Constant | Meaning |
|------|----------|---------|
| `0` | `EXIT_OK` | Success |
| `64` | `EXIT_USAGE` | Bad invocation (unknown flag, missing required argument) |
| `65` | `EXIT_DATAERR` | Input data invalid (malformed CSV, bad date format) |
| `66` | `EXIT_NOINPUT` | Input file missing or unreadable |
| `69` | `EXIT_UNAVAILABLE` | Service unreachable (PCE, mail server) |
| `70` | `EXIT_SOFTWARE` | Internal error (bug) |
| `71` | `EXIT_OSERR` | OS-level error (file permission, mkdir failure) |
| `78` | `EXIT_CONFIG` | Bad or missing `config.json` |
| `130` | `EXIT_INTERRUPT` | Process interrupted by Ctrl-C (SIGINT) |
| `143` | `EXIT_TERMINATED` | Process killed (SIGTERM) |

Shell pipeline example:

```bash
illumio-ops siem status
case $? in
  0)   echo "OK" ;;
  69)  echo "PCE unreachable — check network" ;;
  78)  echo "Bad config.json" ;;
  130) echo "Interrupted" ;;
  *)   echo "Error: $?" ;;
esac
```

---

## Environment variables

All PCE credentials and connection settings are stored in `config/config.json` under the
`api` section (`url`, `org_id`, `key`, `secret`, `verify_ssl`). There is no supported
way to pass PCE credentials purely via environment variables.

The following environment variables are read by the CLI at runtime:

| Variable | Component | Description |
|----------|-----------|-------------|
| `NO_COLOR` | Renderer | Set to any value to disable ANSI colour output (follows [no-color.org](https://no-color.org/)). |
| `TERM=dumb` | Renderer | Also disables colour when terminal does not support it. |
| `ILLUMIO_SMTP_PASSWORD` | Alerts / SMTP | Overrides `smtp.password` from `config.json`. Use to avoid storing a plaintext password in the config file. |
| `ILLUMIO_OPS_I18N_STRICT` | Report i18n | When set, the report i18n layer raises an error for any missing translation key rather than silently falling back to English. Intended for CI translation coverage checks. |

> **PCE connectivity hint:** The error message for `EXIT_UNAVAILABLE` (69) advises
> checking `PCE_HOST` and `PCE_PORT`. These are **label names used in error text**, not
> environment variables — the actual values come from `config.json → api.url`.

---

## Related Docs

- [REST API](rest-api.md) — programmatic equivalents (B2 deliverable)
- [Glossary](glossary.md) — Illumio terminology
- [Reports User Guide](../_archive/user-guide/reports.md) — operator-level report usage
- [SIEM Integration](../_archive/user-guide/siem-integration.md) — operator-level SIEM config
