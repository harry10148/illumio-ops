---
title: Getting Started
audience: [operator]
last_verified: 2026-06-26
verified_against:
  - docs/Installation.md (legacy, audited)
  - docs/UPGRADE.md (legacy, audited)
  - requirements.txt
  - requirements-offline.txt
  - illumio-ops.py
  - deploy/illumio-ops.service
  - deploy/install_service.ps1
  - config/config.json.example
  - scripts/setup-prod-git.sh
  - python illumio-ops.py --help (output captured verbatim)
  - commit 31c1c48
related_docs:
  - INDEX.md
  - user-guide/dashboard.md
  - user-guide/multi-pce.md
  - user-guide/troubleshooting.md
---

> 🌐 **[English](getting-started.md)** | [繁體中文](getting-started_zh.md)
> 📍 [INDEX](INDEX.md) › Getting Started
> 🔍 Last verified **2026-05-15** against commit `31c1c48` — see frontmatter for sources

# Getting Started

## What is illumio-ops

illumio-ops is an agentless monitoring and automation platform for Illumio PCE.
It connects to one or more PCEs via the REST API — no agents, no firewall changes —
and provides an operator dashboard, scheduled reports, alert rules, SIEM forwarding,
and policy/workload inspection from a single self-hosted service.

## Prerequisites

| Requirement | Detail |
|---|---|
| **Python** | 3.10 or later (3.12 recommended). Not required for offline bundle deployments — the bundle ships its own CPython 3.12. |
| **PCE access** | HTTPS reachability to the PCE (default port `8443`) plus a PCE API key (minimum role: `read_only` for monitoring; `owner` for quarantine operations). |
| **Operating system** | RHEL / Rocky Linux 8+, Ubuntu 22.04+, Debian 12+, Windows Server 2019+ / Windows 11. |

> **How to create a PCE API key**: PCE Web Console → **User Menu → My API Keys → Add**.

## Installation

### From source (development)

Use this path on a workstation or a host with direct internet access to PyPI.

```bash
git clone <repo-url>
cd illumio-ops
cp config/config.json.example config/config.json
```

**Ubuntu 22.04+ / Debian 12+** — PEP 668 blocks direct `pip install`; use a venv:

```bash
sudo apt install python3-venv     # if not already present
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**RHEL / macOS / other**:

```bash
pip install -r requirements.txt
```

Start the web GUI:

```bash
python3 illumio-ops.py gui
```

> Re-activate the venv (`source venv/bin/activate`) each time you open a new shell.

### Offline bundle (RHEL / Ubuntu / Windows)

Use this path for production or air-gapped hosts. The bundle ships a portable
CPython 3.12 interpreter plus all pre-built wheels — no internet access or system
Python required on the target host.

**Build the bundle** (on any internet-connected Linux or WSL machine):

```bash
git clone <repo-url>
cd illumio-ops
bash scripts/build_offline_bundle.sh
# Outputs:
#   dist/illumio-ops-<version>-offline-linux-x86_64.tar.gz
#   dist/illumio-ops-<version>-offline-windows-x86_64.zip
```

> [!NOTE]
> The `dist/` directory in this repository does not ship pre-built bundles.
> Run `build_offline_bundle.sh` on a connected machine to produce them.

**Linux (RHEL / Ubuntu) — first-time install**:

```bash
tar xzf illumio-ops-<version>-offline-linux-x86_64.tar.gz
cd illumio-ops-<version>-offline-linux-x86_64

bash ./preflight.sh                   # exits 1 on any FAIL; safe to run first
sudo ./install.sh                     # installs to /opt/illumio-ops + registers systemd unit
sudo nano /opt/illumio-ops/config/config.json   # fill in PCE credentials

sudo systemctl enable --now illumio-ops
sudo systemctl status illumio-ops     # should show: Active: active (running)
```

After installation a CLI wrapper is available as `illumio-ops` (installed to
`/usr/local/bin/illumio-ops`). Always use the wrapper (or the bundled
interpreter at `/opt/illumio-ops/python/bin/python3`) for manual CLI
operations — the system `python3` on older distros links a SQLite that is too
old for this application (>= 3.35.0 required) and the app will refuse to start.
Run real operations with `sudo` — config files are readable only by the
service user, so an unprivileged wrapper call can do little beyond `--help`.

**Windows Server / Windows 11 — first-time install** (PowerShell as Administrator):

```powershell
Expand-Archive illumio-ops-<version>-offline-windows-x86_64.zip -DestinationPath C:\
cd C:\illumio-ops-<version>-offline-windows-x86_64

.\preflight.ps1                       # exits 1 on any FAIL
.\install.ps1                         # installs to C:\illumio-ops + registers IllumioOps service
notepad C:\illumio-ops\config\config.json       # fill in PCE credentials

Get-Service IllumioOps                # should show: Running
```

`install.ps1` verifies the installation before registering the service —
every production dependency must import (`scripts\verify_deps.py
--offline-bundle`); a pip or verification failure aborts the install with a
non-zero exit code.

### systemd / NSSM service

The service definitions live in `deploy/`:

| File | Purpose |
|---|---|
| `deploy/illumio-ops.service` | systemd unit for Linux (installs to `/opt/illumio-ops`) |
| `deploy/install_service.ps1` | NSSM-based installer for Windows (`IllumioOps` service) |

The offline `install.sh` / `install.ps1` scripts copy and configure these
automatically. For a custom install root, pass `--install-root <path>` to
`install.sh` — the systemd unit is updated to reference that path.

The systemd unit runs:

```text
ExecStart=/opt/illumio-ops/python/bin/python3 /opt/illumio-ops/illumio-ops.py \
          --monitor-gui --interval 10
User=illumio-ops
Restart=always
```

On Windows, NSSM is bundled at `deploy\nssm.exe` and picked up automatically by `install.ps1`.

## First PCE Connection

Edit `config/config.json` (or `/opt/illumio-ops/config/config.json` for service installs)
and fill in the `api` block:

```json
"api": {
    "url": "https://pce.example.com:8443",
    "org_id": "1",
    "key": "api_xxxxxxxxxxxxxx",
    "secret": "your-api-secret-here",
    "verify_ssl": true
}
```

If you have multiple PCEs, add entries to `pce_profiles` and set `active_pce_id`.
See the [Operations Manual](operations-manual_zh.md) for the full multi-PCE workflow (繁體中文).

**Verify connectivity** by running the status command:

```bash
python3 illumio-ops.py status
```

A successful connection shows PCE reachability and daemon status.

## First Login (security)

On first start, sign in with the built-in default credentials:

```text
username: illumio   password: illumio
```

The default username is `illumio` (configurable via `web_gui.username` in
`config.json`). The `must_change_password` gate is enforced: the GUI returns
HTTP 423 on every authenticated request until the password is changed, so you
cannot skip this step.

Change the password immediately after first login via **Settings → Security**.

## Upgrade

**Source / development installs**:

```bash
# (Optional, recommended for production deployment boxes)
bash scripts/setup-prod-git.sh      # run once; enables merge.autoStash

git pull
source venv/bin/activate            # if using venv
pip install -r requirements.txt
# Restart the process / service
```

`scripts/setup-prod-git.sh` enables `merge.autoStash` for the local repo so
`git pull` auto-stashes any in-place edits instead of aborting with
"would be overwritten by merge". Run it once per deployment box after the
initial clone.

**Offline bundle installs** — the installer preserves your config on upgrade:

```bash
# Linux
sudo systemctl stop illumio-ops
tar xzf illumio-ops-<new-version>-offline-linux-x86_64.tar.gz
cd illumio-ops-<new-version>-offline-linux-x86_64
sudo ./install.sh                   # config.json, alerts.json, rule_schedules.json preserved
sudo systemctl start illumio-ops
```

```powershell
# Windows
Stop-Service IllumioOps
Expand-Archive illumio-ops-<new-version>-offline-windows-x86_64.zip -DestinationPath C:\
cd C:\illumio-ops-<new-version>-offline-windows-x86_64
.\install.ps1
Get-Service IllumioOps
```

Files preserved across upgrades: `config/config.json`, `config/alerts.json`,
`config/rule_schedules.json`, `logs/`, `data/pce_cache.sqlite`.

**What the installer does on upgrade** (`install.sh` built-in guards):

1. Refuses to install a bundle older than the installed version
   (db schema migrations are forward-only). Override with
   `sudo ./install.sh --allow-downgrade` only if you know what you are doing.
2. Stops the service automatically if it is running (you restart it after
   reviewing the output).
3. Restores a pristine bundled Python runtime and reinstalls the exact wheel
   set shipped in the bundle — dependency versions on the box always match
   the bundle after an upgrade, and files removed in the new release are
   cleaned up.
4. Verifies the installation before finishing: every production dependency
   must import (`scripts/verify_deps.py --offline-bundle`) and the app must
   answer `illumio-ops.py --help`. A failed check aborts the install with a
   non-zero exit code.

**Uninstall** keeps `config/` and `data/` (the cache DB) unless you ask for
a full wipe; a later reinstall picks both up automatically.

```bash
# Linux
sudo /opt/illumio-ops/uninstall.sh            # preserves config/ and data/
sudo /opt/illumio-ops/uninstall.sh --purge    # removes everything
```

```powershell
# Windows
.\install.ps1 -Action uninstall               # preserves config\ and data\
.\install.ps1 -Action uninstall -Purge        # removes everything
```

**Per-version migration scripts** — some releases ship a one-shot script under
`scripts/migrate_*.py` that rewrites operator-owned state (e.g. alerts.json
keys in v3.26.0). Run after the upgrade installer finishes; the scripts are
idempotent. See
[Release Process — Per-version migration scripts](contributing/release-process.md)
for exact invocations.

## Verify it worked

Open the dashboard in a browser:

```text
https://localhost:5001
```

The GUI serves HTTPS by default (self-signed certificate generated on first run).
Accept the certificate warning on first access.

Check the daemon and PCE connection status:

```bash
python3 illumio-ops.py status
```

Application logs are written to `logs/` inside the install root:
- Source installs: `<project-dir>/logs/`
- Offline bundle: `/opt/illumio-ops/logs/` (Linux) or `C:\illumio-ops\logs\` (Windows)

For systemd service log output:

```bash
journalctl -u illumio-ops -f
```

> [!NOTE]
> There is no dedicated `/health` HTTP endpoint. PCE connectivity health is
> surfaced in the dashboard at `/api/status` and shown on the dashboard KPI card.

## Where to go next

- [Operations Manual](operations-manual_zh.md) — dashboard, multi-PCE, and troubleshooting, plus day-2 operations (繁體中文)

---
## Related Docs
- [INDEX](INDEX.md) — full doc map
- [Operations Manual](operations-manual_zh.md) — dashboard, multi-PCE, and troubleshooting after install (繁體中文)
