# CLI Command Map

This document maps every `illumio-ops` command to its entry point(s):

- **CLI** — invokable via `illumio-ops <command>`
- **Menu** — reachable from the interactive menu (`illumio-ops shell`)
- **Deprecated alias** — older form that still works but emits a deprecation hint

## Top-level subcommands

| Subcommand | CLI | Menu path | Deprecated alias |
|------------|-----|-----------|------------------|
| `cache backfill` | ✓ | shell → 7 (Manage PCE Cache) → 5 | — |
| `cache status` | ✓ | shell → 7 → 1 | — |
| `cache retention` | ✓ | shell → 7 → 6 | — |
| `completion install <shell>` | ✓ | — | — |
| `config validate` | ✓ | — | — |
| `config show` | ✓ | shell → 4 (Settings) — view path | — |
| `gui` | ✓ | shell → 5 (Launch Web GUI) | `--gui` (legacy argparse) |
| `monitor` | ✓ | shell — runs implicitly via menu loop | `--monitor` (legacy argparse) |
| `report generate-traffic` | ✓ | shell → 2 (Reports) → 1 | `report traffic` |
| `report generate-audit` | ✓ | shell → 2 → 2 | `report audit` |
| `report generate-ven-status` | ✓ | shell → 2 → 3 | `report ven-status` |
| `report generate-policy-usage` | ✓ | shell → 2 → 4 | `report policy-usage` |
| `rule list` | ✓ | shell → 1 (Rule Management) — list | — |
| `rule edit` | ✓ | shell → 1 — edit | — |
| `shell` | ✓ | (this IS the menu) | bare `illumio-ops` (no args) |
| `siem test` | ✓ | shell → 8 (SIEM) — test | — |
| `siem status` | ✓ | shell → 8 → 1 | — |
| `siem replay` | ✓ | shell → 8 → DLQ submenu → replay | — |
| `siem purge` | ✓ | shell → 8 → DLQ submenu → purge | — |
| `siem dlq` | ✓ | shell → 8 → DLQ submenu → list | — |
| `status` | ✓ | shell — info shown in panel | — |
| `version` | ✓ | — | — |
| `workload list` | ✓ | — | — |

## Entry points

| Entry | Status | Notes |
|-------|--------|-------|
| `illumio-ops <subcommand>` | **Canonical** | Single command tree, click-based |
| `illumio-ops shell` | **Canonical** | Explicit interactive menu (Track C added) |
| `illumio-ops` (no args) | Deprecated | Emits hint pointing at `shell`; still launches menu |
| `illumio-ops --monitor` (and other legacy argparse flags) | Back-compat | Routed to legacy argparse handler in `illumio-ops.py` |
| `python -m src.pce_cache_cli` | **Not an entry** | Interactive helper module invoked from `src/main.py:main_menu`, not standalone executable. Do not call directly. |
| `python -m src.siem_cli` | **Not an entry** | Same as above. |
| `python -m src.rule_scheduler_cli` | **Not an entry** | Same as above. |

## Deprecation policy

A deprecated form continues to work for at least one major release. Each emits a one-line hint to stderr (via `echo_warning`) pointing at the canonical form.

Track C-introduced deprecations (2026-05-07):
- Bare `illumio-ops` no-args → use `illumio-ops shell` instead
- `report traffic` / `report audit` / `report ven-status` / `report policy-usage` → use `report generate-*` instead

## Adding a new subcommand

1. Implement the click command function in `src/cli/<group>.py` (use `@click.pass_context`, the `_output` helpers, and typed `EXIT_*` codes per Track B convention).
2. Register it on the parent group: `group.add_command(my_cmd)` or `@group.command(...)`.
3. If introducing a new top-level subcommand, also add the name to the `_CLICK_SUBCOMMANDS` set in `illumio-ops.py` so the dispatcher routes it correctly (otherwise it falls through to the legacy argparse handler).
4. Update this document.
