# Upgrade Guide

> [English](UPGRADE.md) | [繁體中文](UPGRADE_zh.md)

This page documents how to upgrade an existing illumio-ops install in place. For a brand-new install, see `README.md` Quick Start.

## TL;DR

```bash
sudo ./install.sh                          # Linux
.\install.ps1 -Action install              # Windows
```

`install.sh` and `install.ps1` detect an existing install at `$INSTALL_ROOT` (default `/opt/illumio-ops` on Linux, `C:\illumio-ops` on Windows) and preserve operator-owned state. If you installed to a custom path, pass `--install-root /opt/custom` (Linux) or `-InstallRoot D:\custom` (Windows).

## What Gets Preserved on Upgrade

Detection: presence of `<INSTALL_ROOT>/config/config.json`. When present, `IS_UPGRADE=true` is logged in install output.

Preserved across upgrades:

| Path | Why |
|---|---|
| `config/config.json` | Operator-owned credentials + settings |
| `config/alerts.json` | Operator-owned alert/rules state |
| `config/rule_schedules.json` | Per-deployment schedule state |
| `logs/` | Operational history |
| `cache/` | PCE cache database (rebuilt incrementally if absent) |

Replaced on every upgrade:

| Path | Why |
|---|---|
| `python/` | Bundled Python runtime |
| `src/` | Application code |
| `requirements-offline.txt` + wheels | Pinned dependencies |
| `config/*.example` | Template files (diff against your live config to spot new keys) |

After install, `IS_UPGRADE=true` runs `pip install --no-index --find-links wheels` to refresh dependencies, then restarts the systemd service (Linux) or NSSM service (Windows).

## Per-Version Migration Steps

Migration scripts live in `scripts/`. They are idempotent — safe to re-run.

### 3.26.0 — i18n architecture

Rules in `config/alerts.json` previously stored rendered description / recommendation text. 3.26.0 moves them to `desc_key` / `rec_key` so language switching is instant. The installer does NOT auto-migrate; run once after upgrade:

```bash
# Linux
sudo -u illumio-ops /opt/illumio-ops/python/bin/python3 \
    /opt/illumio-ops/scripts/migrate_rules_to_keys.py \
    --config /opt/illumio-ops/config/config.json --write
```

```powershell
# Windows
& C:\illumio-ops\python\python.exe `
    C:\illumio-ops\scripts\migrate_rules_to_keys.py `
    --config C:\illumio-ops\config\config.json -Write
```

Existing rules without `desc_key` keep working — the loader falls back to a `[MISSING:*]` marker until migrated. Re-running the script is a no-op once all rules are converted.

### Earlier versions

No mandatory migrations.

## Rollback

The upgrade replaces `python/` and `src/` only. To roll back:

1. Stop the service: `sudo systemctl stop illumio-ops` (Linux) or `nssm stop illumio-ops` (Windows).
2. Restore `python/` and `src/` from the previous bundle (extract the older offline tarball/zip into `$INSTALL_ROOT`).
3. **Don't** restore `config/` — your post-upgrade `config.json` is forward-compatible with the older code (older code ignores unknown keys like `web_gui.session_lifetime_seconds`, added in 3.26.0+).
4. Restart the service.

If a migration script ran (e.g. `migrate_rules_to_keys.py`), it edits `config/alerts.json` in place. Older code reads the new `desc_key`/`rec_key` fields gracefully via a fallback path; no rollback step is required for migrated rules.

## Preflight Check

Before upgrading, run preflight against the offline bundle:

```bash
bash scripts/preflight.sh --install-root /opt/illumio-ops
```

It reports an explicit `UPGRADE` warning when an existing install is detected, plus disk space, glibc version, port 5001 availability, and bundle integrity.

## See also

- `CHANGELOG.md` — per-version user-visible changes
- `scripts/install.sh` / `scripts/install.ps1` — the actual installer logic
- `scripts/preflight.sh` — pre-upgrade environment check
