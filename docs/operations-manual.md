---
title: Operations Manual
audience: [operator]
version: 4.1.0
last_verified: 2026-06-26
verified_against:
  - scripts/install.sh
  - scripts/install.ps1
  - scripts/build_offline_bundle.sh
  - scripts/uninstall.sh
  - deploy/illumio-ops.service
  - deploy/install_service.ps1
  - config/config.json.example
  - src/cli/ (full Click subcommand audit)
  - src/gui/routes/ (~109 routes audited)
  - src/gui/__init__.py, src/gui/_helpers.py
  - src/alerts/plugins.py, src/alerts/metadata.py
  - src/templates/, src/static/js/
  - docs/getting-started.md, docs/user-guide/*, docs/reference/cli.md
  - 2026-06-26 full audit + live testing
related_docs:
  - getting-started.md
  - user-guide/dashboard.md
  - user-guide/troubleshooting.md
  - reference/cli.md
---

> Doc navigation: This page is the **core day-to-day operations guide for illumio-ops operators**, consolidating and updating the per-tab user manuals.
> Glossary terms (PCE, VEN, Workload, Service, Port, Policy, Ruleset, SIEM, DLQ, SMTP, etc.) are kept in English per project convention.

# illumio-ops Operations Manual (v4.1.0)

illumio-ops is an **agentless monitoring and automation platform** for Illumio PCE. It connects via the PCE REST API — with no agents installed on the PCE or Workloads, and no firewall changes — to provide an operator dashboard, scheduled reports, alert rules, SIEM forwarding, and Policy/Workload inspection and quarantine.

Manual chapters:

1. [Installation and First Launch](#1-installation-and-first-launch)
2. [Configuration](#2-configuration)
3. [Web GUI Operations Guide](#3-web-gui-operations-guide)
4. [CLI Usage](#4-cli-usage)
5. [Reports](#5-reports)
6. [Alerts](#6-alerts)
7. [SIEM Forwarding Configuration](#7-siem-forwarding-configuration)
8. [Operations](#8-operations)
9. [Troubleshooting](#9-troubleshooting)

---

## 1. Installation and First Launch

### 1.1 System Requirements

| Item | Requirement |
|---|---|
| Python | 3.10 or later (3.12 recommended). The offline bundle does not require a system Python — the bundle ships its own CPython 3.12.7. |
| PCE access | HTTPS reachability to the PCE (default port `8443`), plus a PCE API key (minimum `read_only` for monitoring; `owner` for quarantine operations). |
| Operating system | RHEL / Rocky Linux 8+, Ubuntu 22.04+, Debian 12+, Windows Server 2019+ / Windows 11. |

> **How to create a PCE API key**: PCE Web Console → top-right user menu → **My API Keys → Add**.

### 1.2 Standard Installation (Linux, canonical path /opt/illumio-ops)

The canonical install path for production is **`/opt/illumio-ops`**, deployed by `scripts/install.sh`, which registers a **hardened systemd unit**. The installer runs as root and will:

- Create the system user `illumio-ops` (`useradd --system --no-create-home --shell /sbin/nologin`).
- Create the runtime directories `logs/`, `data/`, `reports/`, `config/`, `config/tls/`.
- Set permissions: secrets `0600`, config files `0640`, sensitive directories `0750`.
- Generate and install the systemd unit from `deploy/illumio-ops.service`.

systemd unit highlights (`deploy/illumio-ops.service`):

```ini
ExecStart=/opt/illumio-ops/python/bin/python3 /opt/illumio-ops/illumio-ops.py --monitor-gui --interval 10
User=illumio-ops
Restart=on-failure
RestartSec=10
# Hardening: NoNewPrivileges, ProtectSystem=strict, ProtectHome=true, PrivateTmp,
#       SystemCallFilter=@system-service, CapabilityBoundingSet=(cleared), etc.
ReadWritePaths=/opt/illumio-ops/logs /opt/illumio-ops/config /opt/illumio-ops/data /opt/illumio-ops/reports
```

> **Security note**: the unit enables `ProtectHome=true` and `ProtectSystem=strict`, so the service can only write to the four directories listed in `ReadWritePaths`. If you move the database or configuration to a different path, you must add it to `ReadWritePaths` as well, or the service will fail to start because it cannot write.

Enable and start the service:

```bash
sudo systemctl enable --now illumio-ops
sudo systemctl status illumio-ops      # should show Active: active (running)
journalctl -u illumio-ops -f           # follow live logs
```

> Custom install root: `sudo ./install.sh --install-root /opt/custom` — the systemd unit is automatically rewritten to that path. Note: a custom path skips the automatic migration from the legacy `/opt/illumio_ops` (underscore).

### 1.3 Offline / Air-Gapped Bundle

For production or isolated-network hosts, the offline bundle is recommended. The bundle ships a portable CPython 3.12 and all pre-built wheels, so the target host needs **no network and no system Python**.

**Build the bundle** (on any internet-connected Linux/WSL host):

```bash
bash scripts/build_offline_bundle.sh
# Outputs:
#   dist/illumio-ops-<version>-offline-linux-x86_64.tar.gz
#   dist/illumio-ops-<version>-offline-windows-x86_64.zip
```

> The bundle **never contains** `config.json`, `alerts.json`, or `rule_schedules.json` (which hold secrets) — only the `*.example` templates. The build script verifies the downloaded CPython tarball against an in-tree SHA256 pin.

**First-time Linux install**:

```bash
tar xzf illumio-ops-<version>-offline-linux-x86_64.tar.gz
cd illumio-ops-<version>-offline-linux-x86_64
bash ./preflight.sh                    # any FAIL returns non-zero; safe to run first
sudo ./install.sh                      # installs to /opt/illumio-ops and registers systemd
sudo nano /opt/illumio-ops/config/config.json   # fill in PCE credentials
sudo systemctl enable --now illumio-ops
```

### 1.4 Windows (NSSM Service)

On Windows, the bundled **NSSM** (`deploy\nssm.exe`) registers a service named **`IllumioOps`**. The default install root is `C:\illumio-ops`.

```powershell
# Open PowerShell as Administrator
Expand-Archive illumio-ops-<version>-offline-windows-x86_64.zip -DestinationPath C:\
cd C:\illumio-ops-<version>-offline-windows-x86_64
.\preflight.ps1
.\install.ps1                          # installs to C:\illumio-ops and registers the IllumioOps service
notepad C:\illumio-ops\config\config.json
Get-Service IllumioOps                 # should show Running
```

> **Important difference (Linux vs Windows)**: Linux systemd starts with **`--monitor-gui`** by default (running the monitoring daemon + Web GUI together); the Windows NSSM service runs only **`--monitor`** by default (daemon only, **does not auto-start the Web GUI**). If you need the Web GUI on Windows, start it separately with `python\python.exe illumio-ops.py gui`, or use `nssm edit IllumioOps` to change `AppParameters` to `--monitor-gui`.
>
> NSSM service logs are written to `C:\illumio-ops\logs\service_stdout.log` and `service_stderr.log` (10 MB rotation), with automatic restart 10 seconds after a crash.

### 1.5 Install from Source (Development and Testing)

```bash
git clone <repo-url> && cd illumio-ops
cp config/config.json.example config/config.json
# Ubuntu/Debian are subject to PEP 668; use a venv:
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python3 illumio-ops.py gui             # start the Web GUI
```

> Re-run `source venv/bin/activate` in every new shell.

### 1.6 The Four Run Modes

| Mode | Subcommand | Legacy flag equivalent | Description |
|---|---|---|---|
| Monitoring daemon | `illumio-ops monitor` | `--monitor` | No GUI; polls the PCE and evaluates alerts in the background |
| Web GUI only | `illumio-ops gui` | `--gui` | Starts the web interface only |
| Monitoring + GUI | `illumio-ops monitor-gui` | `--monitor-gui` | Combined mode (**systemd default**) |
| Interactive CLI menu | `illumio-ops shell` | (bare `illumio-ops`, deprecated) | Text menu; TLS certificates, PCE profiles, the rule-scheduler, etc. are reachable only here |

The Web GUI is served over HTTPS by **cheroot**, bound to **`0.0.0.0:5001`** by default. Common flags:

```bash
illumio-ops gui --port 5001 --host 0.0.0.0     # -p/--port, -h/--host
illumio-ops monitor-gui --interval 10 --port 5001
```

`--host` controls the listening interface (default `0.0.0.0` means all interfaces; set `127.0.0.1` to expose only localhost). `--interval` is the monitoring cycle (in minutes, default 10).

### 1.7 First Login and Forced Password Change

- The default Web GUI user is **`illumio`** (changeable via `web_gui.username`). The initial password is generated and shown during install / first setup; passwords are stored hashed with **Argon2id**.
- The login page is at **`/login`**; the front-end SPA then calls the JSON API (`POST /api/login`).
- **Forced password change on first login**: when `web_gui.must_change_password` is true, the backend returns **HTTP 423** for every protected API until the password is changed — this cannot be bypassed. A password-change form appears immediately after login (the new password must be at least 8 characters and match the confirmation field); only then can you reach the dashboard.

> **Security note**: the first time you open `https://<host>:5001` in a browser, you will see a self-signed certificate warning (normal — see [8.6](#86-tls-certificate-rotation)). Change the password immediately after first login.

### 1.8 Update Procedure

**Source / development install**:

```bash
git pull
source venv/bin/activate
pip install -r requirements.txt
# Restart the service or process
```

**Offline bundle install** (the installer preserves your configuration):

```bash
# Linux
sudo systemctl stop illumio-ops
tar xzf illumio-ops-<new-version>-offline-linux-x86_64.tar.gz
cd illumio-ops-<new-version>-offline-linux-x86_64
sudo ./install.sh                      # preserves config.json / alerts.json / rule_schedules.json / logs / data
sudo systemctl restart illumio-ops
```

```powershell
# Windows
Stop-Service IllumioOps
.\install.ps1                          # likewise preserves operator-owned config files
Restart-Service IllumioOps
```

Files preserved across upgrades: `config/config.json`, `config/alerts.json`, `config/rule_schedules.json`, `logs/`, `data/pce_cache.sqlite`. After upgrading, compare against any newly added config keys:

```bash
diff /opt/illumio-ops/config/config.json.example /opt/illumio-ops/config/config.json
```

> On production hosts you can run `bash scripts/setup-prod-git.sh` once to enable `merge.autoStash`, so `git pull` automatically stashes local changes before fast-forwarding, avoiding interruption by "local changes would be overwritten".

### 1.9 Uninstall

```bash
sudo /opt/illumio-ops/uninstall.sh             # preserves config/ by default
sudo /opt/illumio-ops/uninstall.sh --purge     # also deletes the configuration
```

```powershell
.\install.ps1 -Action uninstall                # Windows: removes the IllumioOps service and install directory
```

---

## 2. Configuration

### 2.1 Configuration File Overview

All configuration files live in `config/` (all are listed in `.gitignore` because they contain secrets). Start from the templates:

```bash
cp config/config.json.example config/config.json
```

| File | Contents |
|---|---|
| `config.json` | Main configuration (see the per-section table below). |
| `alerts.json` | Alert rule definitions (event/traffic/bandwidth rules). Written atomically, permissions `0600`. |
| `report_config.yaml` | Report analysis parameters: ransomware risk-port tiers, lateral movement ports, B/L series thresholds, output `top_n`, etc. |
| `rule_schedules.json` | The Rule Scheduler's local schedule records (keyed by PCE rule/ruleset href). |

### 2.2 config.json Sections

| Section | Purpose |
|---|---|
| `api` | The currently active PCE connection (`url`, `org_id`, `key`, `secret`, `verify_ssl`). Activating a profile copies that profile into this section. |
| `pce_profiles` / `active_pce_id` | The list of multiple PCE profiles and the currently active profile id. |
| `alerts` | The list of enabled channels (`active`), plus the line/webhook/telegram/teams keys. |
| `email` / `smtp` | Mail sender and recipients; SMTP host/port/credentials/TLS. |
| `settings` | `language` (`en` / `zh_TW`), `theme`, `timezone`, `enable_health_check`, `dashboard_queries`. |
| `report` / `report_schedules` | Report defaults and the schedule list. |
| `rule_scheduler` | `enabled`, `check_interval_seconds` (default 300). |
| `scheduler` | `persist`, `db_path` — deprecated, no longer used (in-memory job store only; `persist=true` just logs a warning). |
| `web_gui` | `username`, `password` (Argon2id hash), `secret_key`, `allowed_ips`, `tls{...}`, `must_change_password`. |
| `logging` | `level`, `json_sink`, `rotation` (e.g. `10 MB`), `retention`. |
| `pce_cache` | Local SQLite cache settings (see [8.1](#81-pce-cache-and-retention-policy)). |
| `siem` | SIEM forwarding settings (see [Chapter 7](#7-siem-forwarding-configuration)). |

> **Security note**: `config.json` holds the PCE secret, the SMTP password, and LINE/Telegram/Teams tokens. Keep its permissions at `0600` and never commit it to version control. The SMTP password can also be overridden with the environment variable `ILLUMIO_SMTP_PASSWORD` to avoid storing it in plaintext on disk.

### 2.3 PCE Connection and Multi-PCE

The simplest approach is to edit the `api` section directly:

```json
"api": {
  "url": "https://pce.example.com:8443",
  "org_id": "1",
  "key": "api_xxxxxxxxxxxxxx",
  "secret": "your-api-secret-here",
  "verify_ssl": true
}
```

For multiple PCEs, add objects under `pce_profiles` and set `active_pce_id`. **Only one profile is active at a time**; every feature (monitoring, reports, rules, cache) targets that active profile. To switch:

- **Web GUI**: Settings → PCE, click **Activate** on the profile (not just Save). Activation copies the credentials into the `api` section; the daemon picks it up on the next polling cycle, with no restart needed.
- **Manual edit**: change `active_pce_id`, then restart the process.

> **Lab / self-signed PCE**: in a lab you can set `"verify_ssl": false` to skip PCE certificate verification. This is a **deliberate security trade-off** — in production, set `true` and install the PCE's CA certificate into the host system trust store (the PCE profile schema currently has no per-profile CA bundle field).

### 2.4 alerts.json (Rule Definitions)

Alert rules live in a separate `config/alerts.json` (not inside `config.json`). The key fields of each rule:

| Field | Description |
|---|---|
| `type` | `event`, `traffic`, `bandwidth` |
| `name_key` | i18n key; the display name is resolved at load time (the file stores only the key, not language strings) |
| `filter_value` | Comma-separated PCE event types (event rules) |
| `filter_status` / `filter_severity` | `all` / `success` / `failure`; `all` / `err` / `warning` / `info` |
| `threshold_type` | `immediate` (fires on first match) or `count` (N times within a window) |
| `throttle` | Rate-limit format `N/Tm`, e.g. `1/15m` means at most once every 15 minutes |
| `cooldown_minutes` | Cooldown period after firing |

Rules are best maintained through the Web GUI (the Rules tab) or the CLI (`illumio-ops rule list` / `rule edit`); the GUI's **Load Best Practices** can append or replace with the built-in best-practice rule set (17 event + 1 traffic) in one click.

### 2.5 report_config.yaml / rule_schedules.json

- `report_config.yaml` defines the report security-analysis parameters, e.g. ransomware risk ports (critical: RPC 135, SMB 445, RDP 3389, WinRM 5985/5986), lateral movement ports, and B/L series rule thresholds (such as `min_policy_coverage_pct: 30`, `exfil_bytes_threshold_mb: 100`). Most operators do not need to change it.
- `rule_schedules.json` is maintained automatically by the Rule Scheduler, keyed by PCE href, recording `type` (`recurring`/`expire`), `action` (`allow`/`block`), `days`, `start`, `end`, `timezone`, etc., and usually does not need manual editing.

### 2.6 Modifying Configuration via CLI

```bash
illumio-ops config show                       # print the full (validated) configuration
illumio-ops config show --section api          # view a single section
illumio-ops config validate                    # validate against the Pydantic schema
illumio-ops config set api.url https://pce.example.com:8443   # write a single key [persists to disk]
illumio-ops config login --url ... --key ... --secret ...      # set PCE credentials [persists to disk]
```

> **Side-effect note**: `config set` and `config login` validate and **overwrite** `config.json` on disk (secrets are masked in the output).

---

## 3. Web GUI Operations Guide

The GUI is a single-page application: after login you switch between top tabs, with content fetched by front-end JS modules from ~109 JSON APIs. The following walks through each tab and flags the actions that produce **real side effects**.

> **Global security note**: every route requires login except `/login`, `/api/login`, `/logout`, and `/api/csrf-token`. `web_gui.allowed_ips` provides an IP allowlist matched against the **direct connection source IP** (`request.remote_addr`); rejected connections are silently dropped with a TCP RST (to avoid detection by port scanners). All POST/PUT/DELETE requests require a CSRF token. See [8.7 Reverse Proxy and IP Allowlist](#87-reverse-proxy-and-ip-allowlist).

### 3.1 Header

- Left: the product logo.
- Center: the **PCE status chip** — a connection-health indicator (green ok / amber warn / red err / gray unknown), the PCE host, the Rules count, the Schedules count, and the config load time.
- Right: the **Operations** dropdown — Theme (Auto/Dark/Light), Density (Compact/Comfortable), **Logs** (opens the operations log window), **Stop** (stops the web service, **with a confirmation dialog**; available only in non-persistent mode).

### 3.2 Main Tabs

In order: **Dashboard｜Traffic & Workloads｜Event Viewer｜Rules｜Reports｜Rule Scheduler｜Integrations｜Settings**.

**1) Dashboard** — live overview. Shows the Security Posture score and Top Risk Findings, VEN health, Pipeline (cache ingestion) health, OS distribution, Enforcement modes, and the Health/Traffic/Risk status cards. The "auto-refresh 10m" checkbox and the **Refresh** button only **re-fetch** the latest snapshot (`GET /api/dashboard/*`); they do not regenerate the report snapshot.

**2) Traffic & Workloads** — traffic analysis and Workload search.

- *Traffic Analyzer*: filter by Policy Decision (Blocked/Potential/Allowed/All), label/IP/port/protocol; lists flows with pagination.
- *Workload Search*: look up Workloads by name/IP/hostname, showing online status, interfaces, labels, and managed state.
- **Isolate (quarantine)**: on a flow row or Workload row click Isolate → choose direction (source/destination/both) and severity (Mild/Moderate/Severe) → apply.
  - > **Real side effect (high-risk)**: `POST /api/quarantine/apply` or `bulk_apply` adds a `Quarantine` label to the Workload **on the PCE**, immediately changing its enforcement until removed manually. Bulk apply uses up to 5 parallel workers. The first use auto-creates the Quarantine labels (`/api/init_quarantine`).
- **Accelerate**: temporarily raises the flow-reporting frequency for a managed Workload (`POST /api/workloads/accelerate`, calling the PCE `set_flow_reporting_frequency`).
  - > **Real side effect**: changes the telemetry frequency of that Workload on the PCE (does not change enforcement). Available only for managed Workloads; continuous mode is re-sent by the front end every 10 minutes.

**3) Event Viewer** — PCE audit event viewer. Filter by time window, category/group/type, and keyword, with a list on the left and detail on the right (normalized + raw JSON). It also includes Shadow Compare (matching rules against actual events), Rule Test (testing a single rule), and the Event Catalog. All are **read-only** (they call the PCE API live to fetch events).

**4) Rules** — alert rule maintenance, with two sub-tabs:

- *Rules*: filter by type (Event/Traffic/Bandwidth/System Health), search, edit, delete, and bulk-delete. Adding a rule opens the corresponding modal. Saving/deleting **writes to `alerts.json`/config**.
- *Actions*:
  - **Send Test Alert (All) / Test [channel]**:
    - > **Real side effect**: `POST /api/actions/test-alert` **actually sends** a test message to the specified (or all) channels (email/LINE/webhook/Telegram/Teams). Do not click casually in production.
  - This tab also provides debugging actions such as manual analysis and reset-watermark (see [3.3](#33-high-risk-action-summary)).

**5) Reports** — report list and schedules, with two sub-tabs:

- *List*: browse generated reports, with View (HTML), Download, and Delete / bulk Delete (**deletes files, irreversible**), plus a **Generate** button for each report type (Traffic/Audit/VEN Status/Policy Usage/Policy Diff/Policy Resolver/App Summary).
  - > **Side effect**: generating a report queues a background thread on the server, queries the PCE live, and writes out files; it can take several minutes.
- *Schedules*: create / edit / enable-disable / Run Now / delete report schedules. Schedules only fire while the daemon keeps running; checking Email requires the mail channel to be configured first. See [Chapter 5](#5-reports).

**6) Rule Scheduler** — time-triggered enable/disable of Rulesets/Rules in PCE Draft policy, with three sub-tabs: Browse (browse rulesets/rules), Schedules (the schedule list), and Logs.

- Create a schedule: choose Recurring (weekday + start/end time + timezone) or One-time (expiry time); Action is `allow` (enabled within the window) or `disable`.
  - > **Real side effect**: `POST /api/rule_scheduler/schedules` writes an English schedule annotation into the PCE rule's description and enables/disables that rule on the PCE per the schedule. **Draft (unprovisioned) rules are blocked** — they must be provisioned on the PCE first. Deleting a schedule makes a best-effort attempt to clear the annotation on the PCE.
  - > **Note**: the scheduler **does not auto-provision rulesets** — it only toggles a rule's enabled flag in the Draft state; provisioning must be handled separately by the operator.

**7) Integrations** — four sub-tabs:

- *Overview*: pipeline health overview.
- *Cache*: the PCE cache status card and a settings form (retention days, polling intervals, traffic filter/sampling). Changes take effect only after **Restart Monitor** (`POST /api/daemon/restart`). You can manually **Backfill** (backfill history — **queries the PCE and writes to the cache DB**) or **Retention Now** (**permanently deletes expired rows**).
- *SIEM*: the destination list and KPIs (sent/failed/DLQ/success rate/latency). Add / edit / delete destinations, and **Test** (**actually sends a test event**). See [Chapter 7](#7-siem-forwarding-configuration).
- *DLQ*: the dead-letter queue viewer, with **Retry (replay)** (**re-sends failed events**) or **Clear / Purge** (**permanently deletes**).

**8) Settings** — four sub-tabs:

- *PCE*: the PCE profile list and Activate, plus the API connection fields (for multi-PCE, see [2.3](#23-pce-connection-and-multi-pce)).
- *Channels*: the enable toggles and fields for each alert channel (**mail, LINE, webhook, Telegram, Teams**).
- *Display*: timezone, language (English / Traditional Chinese), theme, and the report output directory / retention days.
- *Security*: the Web UI password (with a confirmation field, validated for consistency on the front end), the IP allowlist, and the **TLS/HTTPS** settings (enable/disable, self-signed vs bring-your-own certificate, Generate CSR, Import Certificate, Renew).
  - > **Real side effect**: TLS Renew/Import/Generate CSR generates or overwrites certificate/key files in `config/tls/`, and requires a **service restart** to take effect.

### 3.3 High-Risk Action Summary

The following actions modify external systems, databases, or files; confirm carefully before performing them:

| Action | Endpoint | Impact |
|---|---|---|
| Quarantine apply / bulk_apply | `/api/quarantine/apply`, `/bulk_apply` | **Adds a Quarantine label to the Workload on the PCE** |
| Accelerate workload | `/api/workloads/accelerate` | Changes the PCE telemetry frequency |
| Send Test Alert | `/api/actions/test-alert` | **Actually sends** a notification to email/LINE/webhook/Telegram/Teams |
| Manual analysis Run | `/api/actions/run` | Queries the PCE and **may actually fire alerts** |
| Reset watermark | `/api/actions/reset-watermark` | Clears the event watermark / alert history; the next run re-fetches all events and may re-fire alerts |
| Load Best Practices | `/api/actions/best-practices` | Overwrites / appends alert rules |
| Rule Scheduler create / delete | `/api/rule_scheduler/schedules*` | **Rewrites PCE rule annotations and toggles rule enablement** |
| Report generate / delete | `/api/reports/*`, `/api/*_report/generate` | Queries the PCE, writes / deletes files; checking Email sends mail |
| Cache backfill / retention | `/api/cache/backfill`, `/retention/run` | Queries the PCE and writes / permanently deletes cache rows |
| SIEM test / DLQ replay / purge | `/api/siem/*` | Sends a test event / re-sends / permanently deletes |
| TLS renew / import | `/api/tls/renew`, `/import-cert` | Overwrites certificate files; requires restart |
| Stop / Daemon restart | `/api/shutdown`, `/api/daemon/restart` | Stops / restarts the service (disabled in persistent mode) |

---

## 4. CLI Usage

Syntax: `illumio-ops [global flags] <subcommand> [args...]`. PCE credentials are always read from `config.json` and **cannot be passed as flags**.

**Global flags** (placed before the subcommand):

| Flag | Description |
|---|---|
| `--json` | Machine-readable JSON output |
| `-q, --quiet` | Suppress non-essential output (errors still go to stderr) |
| `-v, --verbose` | Verbose output (including debug) |

> `--quiet` and `--verbose` are mutually exclusive. The language is determined by `settings.language`; the CLI has no `--lang` flag.

**Subcommand overview**:

```bash
# Status and version
illumio-ops status                 # daemon/scheduler/config status (supports --json)
illumio-ops version

# Configuration (config set / login persist to disk)
illumio-ops config show [--section api]
illumio-ops config validate [--file PATH]
illumio-ops config set <KEY> <VALUE>           # e.g. config set smtp.host smtp.example.com
illumio-ops config login [--url --key --secret --org-id] [--no-interactive]

# PCE cache (backfill writes, retention --run deletes)
illumio-ops cache status
illumio-ops cache backfill --source events|traffic --since YYYY-MM-DD [--until YYYY-MM-DD] [--json]
illumio-ops cache retention [--run]

# Rules (rule edit persists to disk)
illumio-ops rule list [--type event|traffic|bandwidth|volume|system|all] [--enabled-only]
illumio-ops rule edit <RULE_ID> [--no-preview]

# SIEM (test sends events; replay/purge modify/delete the DB)
illumio-ops siem status
illumio-ops siem test <DESTINATION>
illumio-ops siem dlq    --dest <NAME> [--limit 50]
illumio-ops siem replay --dest <NAME> [--limit 100]
illumio-ops siem purge  --dest <NAME> [--older-than 30]

# Workload (read-only)
illumio-ops workload list [--env prod] [--limit 50] [--enforcement full|selective|visibility_only|idle|all] [--managed-only]

# Reports (see Chapter 5), interactive menu, shell completion
illumio-ops report <subcommand> [...]
illumio-ops shell
illumio-ops completion install bash|zsh|fish
```

> **Interactive-menu-only features**: TLS certificate management, PCE profile management, and Rule Scheduler configuration have **no** corresponding top-level CLI subcommand; they are reachable only through the `illumio-ops shell` menu (or the Web GUI).

**Exit codes** (per BSD `sysexits.h`):

| Code | Meaning |
|---|---|
| 0 | Success |
| 64 | Usage error |
| 65 | Invalid input data (CSV / date format) |
| 66 | Input file does not exist |
| 69 | Service unavailable (PCE / mail) |
| 70 | Internal error |
| 71 | OS-level error (permissions / mkdir) |
| 78 | Configuration file error |
| 130 / 143 | Interrupted by Ctrl-C (SIGINT) / kill (SIGTERM) |

---

## 5. Reports

illumio-ops generates several report types from live PCE data or the local cache, written to `reports/`.

**Report types and CLI subcommands**:

| Report | Subcommand | Purpose |
|---|---|---|
| Traffic Flow | `report traffic` | Plain traffic-facts report (overview, policy decision summary, app/env distribution, bandwidth, unmanaged overview); no security scoring |
| Security & Risk | `report security` | Comprehensive traffic security analysis (13 modules: policy decisions, ransomware exposure, lateral movement, enforcement readiness, etc.); rule findings and remediation actions are consolidated into one Findings & Actions chapter; the Lateral Movement chapter shows 4 summary tables (service view, fan-out sources, allowed lateral flows, attack paths) — host-level detail (IP talkers/pairs, bridge nodes, reachable nodes, app chains) is trimmed from HTML (detail retained at the analysis layer; will surface in the XLSX export once export unification ships); fixed security_risk orientation; can include vulnerability scans (Qualys/Tenable) via `--vuln-csv` |
| Network & Traffic Inventory | `report inventory` | Asset/label-governance report focused on 7 chapters (Executive Summary, Label Hygiene, Policy Decisions, Cross-Label Matrix, Unmanaged Hosts, Application Ringfence, Change Impact) — no traffic overview/distribution/bandwidth chapters (see `report traffic` for those); the Cross-Label Matrix chapter shows only the ENV/APP dimensions in HTML, with ROLE/LOC detail trimmed from HTML (retained at the analysis layer; will surface in the XLSX export's Cross-Label sheet once export unification ships); the Unmanaged Hosts chapter is 3 tables (top unmanaged sources, managed apps receiving unmanaged traffic, exposed ports merged with top unmanaged sources); the Change Impact chapter compares this run's posture KPIs against the last snapshot for the same profile — the first run shows a "no previous snapshot" note, subsequent runs render a delta table; fixed network_inventory orientation |
| Audit | `report audit` | Audit events and policy changes (supports `--start-date`/`--end-date`) |
| VEN Status | `report ven-status` | Inventory of VEN status (online / offline) plus unmanaged workloads (in Illumio, "Unmanaged" is a Workload state — an endpoint labeled by IP with no VEN installed — not a VEN status) |
| Policy Usage | `report policy-usage` | Per-rule hit analysis to find unused rules |
| App Summary | `report app-summary --app <APP> [--env --days]` | Inbound/outbound view of a single App label |
| Policy Resolve | `report resolve` | Resolves ACTIVE label-based policy into IP-level firewall rules |
| Policy Diff | `report policy-diff` | DRAFT vs ACTIVE differences (with operator attribution) |

> Earlier docs listed only four (traffic/audit/ven-status/policy-usage) — v4.1.0 has expanded to the nine in the table above. The `report traffic --profile security_risk|network_inventory` flag is **deprecated**; use the `report security` / `report inventory` subcommands instead. All report subcommands also have `generate-*` aliases (for backward compatibility).

**Output formats**: `--format html|csv|pdf|xlsx|all` (default `html`).

| Format | Output | Notes |
|---|---|---|
| `html` | Interactive report (with charts and a sidebar nav) | |
| `csv` | Raw traffic-data zip | Suitable for SIEM import |
| `xlsx` | Excel (one worksheet per module) | |
| `pdf` | **Print-ready HTML** (`@media print` A4 layout) | ReportLab PDF has been removed; use the browser's "Print to PDF" |

**Data source**: optionally `--data-source hybrid|live|cache-only` (default hybrid = cache + live gap-filling); `--source api|csv` (when `csv`, `--file` is required).

**Examples**:

```bash
illumio-ops report traffic --format html --output-dir /opt/illumio-ops/reports
illumio-ops report audit --start-date 2026-06-01 --end-date 2026-06-26 --format xlsx
illumio-ops report app-summary --app HRM --env production --days 14
illumio-ops report policy-diff --email          # generate and send [sends mail]
```

> **Side effect**: every `report *` writes files; with `--email` it sends via the configured SMTP (attaching the report HTML, with an executive summary in the body).

**Scheduled reports**: can be created in the Web GUI (Reports → Schedules) or the CLI interactive menu. Schedulable types cover traffic/audit/VEN-status/policy-usage; schedules fire while the daemon is running, against the currently active PCE profile.

> **Catch-up on upgrade**: after an upgrade, the first scheduler tick will run once for a schedule whose target time today has already passed and hasn't run yet today (catch-up semantics, limited to one run).

---

## 6. Alerts

### 6.1 Channels (5 Types)

| Channel | Plugin name | Required config keys |
|---|---|---|
| Email (SMTP) | `mail` | `email.sender`, `email.recipients`, `smtp.host`, `smtp.port` (optional `smtp.user`/`password`/`enable_tls`/`enable_auth`) |
| LINE Messaging API | `line` | `alerts.line_channel_access_token`, `alerts.line_target_id` |
| Webhook | `webhook` | `alerts.webhook_url` (POST JSON, expects 2xx) |
| Telegram Bot | `telegram` | `alerts.telegram_bot_token`, `alerts.telegram_chat_id` |
| Microsoft Teams | `teams` | `alerts.teams_webhook_url` (Power Automate Workflow webhook, sends an Adaptive Card) |

Which channels are enabled is determined by the `alerts.active` list (e.g. `["mail", "line"]`). Configure each channel and toggle it on under Web GUI **Settings → Channels**.

> Some older docs listed only three (mail/line/webhook) or wrongly listed "Slack" — v4.1.0 actually supports the **5** in the table above (no Slack). The Teams webhook embeds a live secret, which is automatically masked in logs.

### 6.2 Testing and Safety

```bash
# Web GUI: Rules → Actions → Send Test Alert (All) or Test [channel]
# Or call the running GUI directly (HTTPS :5001)
```

> **Side-effect note (replacing the incorrect example in older docs)**: "Test alert" **actually sends a message**. The Web GUI test-alert endpoint is `POST /api/actions/test-alert`, over **HTTPS on port 5001** (older docs mistakenly wrote `http://localhost:8443` — 8443 is the PCE port, not this service's port). Confirm recipients before testing in production to avoid disturbing on-call staff.

### 6.3 Rule Type Overview

- **Event rules**: map to PCE event types (such as `agent.tampering`, `user.sign_in` (failure), `sec_policy.create`, `workloads.unpair`, etc.). The built-in best practices include 16 event rules.
- **Traffic rules**: e.g. "high Blocked traffic" — fires on ≥ 25 blocked flows within a 10-minute window.
- **Bandwidth rules**: fire on a bandwidth (Mbps) or volume (MB) threshold.

Each rule can set `threshold_type` (immediate/count), `threshold_window`, `cooldown_minutes`, and `throttle` (`N/Tm`) to suppress alert storms.

> **Operational practice (Illumio recommendation)**: do **not** monitor Illumio Core events in isolation. Treat them as one input to your overall security tooling and correlate them with other sources for context. (Source: Illumio — Events Described.)

---

## 7. SIEM Forwarding Configuration

illumio-ops can forward PCE audit events and traffic records to any syslog-compatible SIEM, Splunk HEC, or a local JSON sink. Forwarding is durable: events first enter a local SQLite dispatch queue, failures are retried with backoff, and once the limit is exceeded they move into the **DLQ (dead-letter queue)**.

### 7.1 Transport and Format

| transport | Protocol | Default port |
|---|---|---|
| `udp` | Syslog UDP | 514 |
| `tcp` | Syslog TCP (auto-reconnect) | 514 |
| `tls` | Syslog TCP + TLS (1.2+, custom CA optional) | 6514 |
| `hec` | Splunk HTTP Event Collector (**HTTPS only**) | 8088 |

| format | Output | Suitable for |
|---|---|---|
| `cef` | ArcSight CEF 0.1 single line | ArcSight, QRadar |
| `syslog_cef` | CEF wrapped in an RFC5424 syslog header | syslog servers that need RFC5424 framing |
| `json` | Flat JSON (official Illumio field names) | Splunk HEC, Elastic, Logstash, file sinks |
| `syslog_json` | JSON wrapped in an RFC5424 header | rsyslog / syslog-ng (mmjsonparse) |

### 7.2 Configuring a Destination

Configure via the Web GUI (Integrations → SIEM → Add destination) or by editing `config.json › siem.destinations` directly:

```json
{
  "name": "splunk-prod",
  "transport": "hec",
  "format": "json",
  "host": "splunk.example.com",
  "port": 8088,
  "hec_token": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "tls_verify": true,
  "tls_ca_bundle": null,
  "batch_size": 100,
  "source_types": ["audit", "traffic"],
  "max_retries": 10
}
```

- `source_types`: `audit` (PCE audit events, source table `pce_events`), `traffic` (traffic summaries, source table `pce_traffic_flows_raw`), or both.
- The dispatcher runs every `siem.dispatch_tick_seconds` (default 5 seconds); after `max_retries` consecutive failures an entry moves into the DLQ (capped per destination by `siem.dlq_max_per_dest`, default 10000).
- TLS / lab: `tls_verify: false` is for development only; for a custom private CA, point `tls_ca_bundle` at the CA bundle path.

### 7.3 Testing, Status, and DLQ

```bash
illumio-ops siem test <destination>          # send a siem.test event and report latency [sends an event]
illumio-ops siem status                       # pending/sent/failed/DLQ per destination
illumio-ops siem dlq    --dest <name> [--limit N]
illumio-ops siem replay --dest <name> [--limit N]      # requeue DLQ entries back to pending [modifies DB]
illumio-ops siem purge  --dest <name> [--older-than 30]  # delete old DLQ entries (default 30 days) [deletes from DB]
```

> There is no `siem flush` subcommand — the dispatcher drains automatically on its tick interval.

---

## 8. Operations

### 8.1 PCE Cache and Retention Policy

The PCE cache is an **optional** local SQLite database (`data/pce_cache.sqlite`, WAL mode) that serves as a shared buffer for SIEM forwarding, reports, and alerts. It is **disabled by default** (`pce_cache.enabled = false`; when disabled, everything falls back to the live PCE API).

Key defaults once enabled (`config.json › pce_cache`):

| Setting | Default | Description |
|---|---|---|
| `events_poll_interval_seconds` | 300 | Event polling interval |
| `traffic_poll_interval_seconds` | 600 | Traffic polling interval (template value; some older docs wrongly listed 3600) |
| `events_retention_days` | 90 | Event retention |
| `traffic_raw_retention_days` | 7 | Raw traffic retention |
| `traffic_agg_retention_days` | 90 | Aggregated traffic retention |
| `rate_limit_per_minute` | 400 | PCE API rate limit |

Main tables: `pce_events`, `pce_traffic_flows_raw`, `pce_traffic_flows_agg`, `ingestion_watermarks`, `siem_dispatch`, `dead_letter`.

```bash
illumio-ops cache status                      # row counts per table and last sync time (no daemon required)
illumio-ops cache backfill --source events --since 2026-06-01    # backfill history
illumio-ops cache retention --run             # run retention cleanup immediately
```

> Polling is incremental and watermark-based; there is no "full refresh" mode. A daily APScheduler job clears expired rows per their TTL; a separate lag monitor checks ingestion lag every 60 seconds and logs WARNING/ERROR when it exceeds the threshold.

**Long-term archive export and long-lived flow growth:** the archiver (`ArchiveExporter`) incrementally exports `pce_events`/`pce_traffic_flows_raw` rows to per-day JSONL files, advancing a cursor by `ingested_at`. The ingestor's upsert now bumps `ingested_at` to the current ingest time whenever a re-pulled flow's volatile columns (`last_detected`/`bytes_in`/`bytes_out`/`flow_count`) change, so a long-lived flow that keeps growing in the live cache is picked up again by the next archive export instead of staying frozen behind the cursor. On the import side, `ArchiveImporter` upserts by `flow_hash` and merges `last_detected`/`bytes_in`/`bytes_out`/`flow_count` by MAX (`first_detected` by MIN, `raw_json`/`report_json` taken from whichever export has the newer `last_detected`), so re-importing a later export of the same flow only ever grows the reconstructed counts in the Archive Review DB, never freezes or shrinks them. Archive files written before this fix may still contain a frozen first-export snapshot for flows that were long-lived at the time; once such a flow is re-pulled and exported again, importing that later file self-heals the count via the MAX merge — no manual backfill needed. **Capacity sizing note:** every actively growing long-lived flow is now re-written to the current day's archive file on each change it picks up, so on a busy PCE the archive directory's growth rate is noticeably higher than one-line-per-flow — size the volume accordingly and rely on `archive_retention_days` pruning to bound it (the default `0` keeps files forever). See the `ArchiveExporter`/`ArchiveImporter` docstrings in `src/pce_cache/archive.py` / `archive_import.py` for details.

### 8.2 Updates

See [1.8 Update Procedure](#18-update-procedure). In short: for source installs use `git pull` + `pip install`; for offline bundles re-run `install.sh`/`install.ps1` (configuration is preserved), then restart the service.

### 8.3 Backup

```bash
# Configuration (contains secrets; store in a controlled location)
cp -a /opt/illumio-ops/config /secure-backup/illumio-config-$(date +%Y%m%d)

# PCE cache: hot backup via the SQLite backup API
sqlite3 /opt/illumio-ops/data/pce_cache.sqlite ".backup /backup/pce_cache_$(date +%Y%m%d).sqlite"
# Or stop the service and copy directly (avoids WAL tearing)
sudo systemctl stop illumio-ops && cp /opt/illumio-ops/data/pce_cache.sqlite /backup/ && sudo systemctl start illumio-ops
```

> The cache schema has no built-in upgrade-migration tool — if the table structure changes between versions, delete the database and rebuild it with backfill (read the release notes before upgrading).

### 8.4 Logs

| File / Source | Contents |
|---|---|
| `logs/illumio_ops.log` | Human-readable application log (default 10 MB × 10 rotations) |
| `logs/illumio_ops.json.log` | Structured JSON sink (enabled when `logging.json_sink: true`) |
| `journalctl -u illumio-ops` | systemd service output (Linux production) |
| `logs/service_stdout.log` / `service_stderr.log` | Windows NSSM service output |

Adjust the level: set `config.json › logging.level` to `ERROR`/`WARNING`/`INFO`/`DEBUG`.

```bash
sudo journalctl -u illumio-ops -f -n 100
tail -f /opt/illumio-ops/logs/illumio_ops.log
```

### 8.5 Service Management

```bash
sudo systemctl restart illumio-ops        # the most common way to apply config changes
sudo systemctl status illumio-ops -l
```

```powershell
Restart-Service IllumioOps
Get-Service IllumioOps
```

### 8.6 TLS Certificate Rotation

The Web GUI is served over **HTTPS** by default (`web_gui.tls.enabled: true`, `self_signed: true`). On first start, if no certificate exists, a self-signed certificate is generated in `config/tls/`:

| Item | Value |
|---|---|
| Certificate / key | `config/tls/self_signed.pem`, `self_signed_key.pem` |
| Validity | **397 days (about 13 months, the browser-acceptable maximum)** |
| Default algorithm | **ECDSA-P256** (falls back to RSA-2048 if the host lacks the `cryptography` package) |
| Auto-renewal | When `auto_renew: true`, checked on every start; when remaining days ≤ `auto_renew_days` (default 30) it is automatically re-issued |

> Older docs stated "5 years, RSA" — v4.1.0 is actually **397 days, ECDSA-P256**.

Procedure for obtaining a CA-signed certificate in production (Settings → Security → TLS): Generate CSR → submit to the CA → Import Certificate (paste the chained PEM) → **restart the service**. All certificate changes require a restart to take effect (there is no in-process reload).

### 8.7 Reverse Proxy and IP Allowlist

`web_gui.allowed_ips` is matched against the **direct peer IP** of the connection (`request.remote_addr`). The current code **does not apply ProxyFix** and does not trust `X-Forwarded-For`.

> **Important security note**: when the service sits behind a reverse proxy (nginx, HAProxy, etc.), the source of every request becomes the proxy's IP, so the built-in IP allowlist **only matches the proxy address and becomes ineffective**. Therefore choose one of:
> - Enforce source-IP restriction **at the reverse-proxy layer** (recommended), or
> - Ensure the proxy preserves the real client IP and add ProxyFix yourself (trusting 1 hop) before the WSGI app, then use `allowed_ips`.
>
> If unsure, the safest approach is to bind illumio-ops only to `127.0.0.1` (`--host 127.0.0.1`) and let the front-end proxy handle TLS and access control.

### 8.8 Dependency Watch List

Packages that still work today but need an eye kept on them for a future maintenance pass:

- **flask-talisman** (`requirements.txt` Phase 4, security headers): upstream project is **archived** (no further releases expected). Not an immediate problem — the package still functions — but plan an exit path before it becomes a real compatibility/CVE risk. Exit path if/when needed: replace with a self-written `after_request` hook (~100 lines) setting the same security headers (CSP, HSTS, X-Frame-Options, etc.) directly, dropping the dependency.

---

## 9. Troubleshooting

> This chapter consolidates `user-guide/troubleshooting.md` and corrects its outdated commands.

### 9.1 Installation / Startup

- **Ubuntu/Debian `externally-managed-environment`**: PEP 668 blocks system-level pip; use a venv (see [1.5](#15-install-from-source-development-and-testing)).
- **`ModuleNotFoundError` / service exits immediately on start**: run the dependency check with the correct interpreter:
  ```bash
  /opt/illumio-ops/python/bin/python3 /opt/illumio-ops/scripts/verify_deps.py
  ```
- **`TypeError: unsupported operand type(s) for |`**: the interpreter is below 3.10. The offline bundle uses its bundled CPython 3.12; in development, rebuild the venv.
- **systemd service fails to start**:
  ```bash
  sudo systemctl status illumio-ops -l
  sudo journalctl -u illumio-ops -n 100 --no-pager
  ```
  Common causes: `config.json` missing or with a syntax error (check with `python3 -m json.tool config.json`), `logs/`/`data/` permissions (`chown -R illumio-ops:illumio-ops`), or port 5001 already in use (`ss -tlnp | grep 5001`; switch ports with `gui --port`).
  > Correction: the "`settings.port`" mentioned in older docs does not exist — the port is controlled by the `--port` flag (or the systemd/NSSM startup arguments).

### 9.2 PCE Connection

- **401/403 auth failed**: wrong `api.key`/`secret`, or the key has been revoked. Re-issue the key in the PCE Console, update `config.json`, then `sudo systemctl restart illumio-ops`.
- **Connection refused / timeout**: check the network and port:
  ```bash
  curl -v --max-time 5 https://pce.example.com:8443/api/v2/health
  ```
- **`SSLCertVerificationError` on a lab PCE**: set `"verify_ssl": false` (a lab trade-off), or install the PCE CA into the system trust store.

### 9.3 TLS / Certificates

- **Browser `NET::ERR_CERT_AUTHORITY_INVALID`**: a self-signed certificate, normal for a fresh install. Accept the exception, switch to a CA certificate (Settings → Security → TLS), or deploy behind a TLS-terminating reverse proxy.
- **Certificate expired**: for self-signed, use **Settings → Security → Renew Certificate** (GUI), or the `illumio-ops shell` interactive menu, then restart the service.
  > Correction: there is **no** `illumio-ops tls renew` top-level CLI subcommand; TLS operations are only in the GUI or the interactive menu.

### 9.4 Reports

- **Empty report / no data**: no data within the cache window. First run `illumio-ops cache backfill --source events|traffic --since <earlier date>`, then regenerate with a wider date range.
  > Note: workloads in the **Idle** policy state have their traffic flow summaries excluded — the PCE does not export them to syslog — so Idle workloads are absent from traffic reports by design. (Source: Illumio Traffic Flow Summaries — Visibility Settings.)
- **Policy Usage hits are 0**: only provisioned (active) rules are queried; draft rules are excluded. Provision them on the PCE first.
- **Chinese shows as boxes in the PDF**: install a CJK font (`fonts-noto-cjk` / `google-noto-cjk-fonts`) and regenerate, or use `--format html`.

### 9.5 Dashboard Data Appears Stale

- The dashboard snapshot comes from the most recently completed report (`/api/dashboard/snapshot` reads `latest_snapshot.json` under `reports/`). The **Refresh** button only re-fetches; it does not regenerate the snapshot. To update the snapshot, actually **generate a Traffic (Security Posture) report**.
  > Correction: the `illumio-ops report run --format snapshot` mentioned in older docs **does not exist** — in v4.1.0 the report subcommands are `report traffic/security/inventory/audit/...` (see [Chapter 5](#5-reports)).

### 9.6 SIEM Not Receiving Events

```bash
illumio-ops siem test <destination>          # see the specific error
```

- `Connection refused`: wrong SIEM port or the listener is not up — verify with `nc -zv <host> <port>`.
- `SSL: CERTIFICATE_VERIFY_FAILED`: the TLS destination's CA is untrusted — set `tls_ca_bundle`, or in a lab temporarily set `tls_verify: false`.
- Silent UDP loss: UDP has no delivery guarantee; prefer `tcp` or `tls`.

### 9.7 `git pull` Conflicts During Upgrade

When a production host has modified version-controlled files in place, `git pull` aborts. One-time setup:

```bash
bash scripts/setup-prod-git.sh        # enable merge.autoStash / rebase.autoStash
# If it already failed:
git stash && git pull && git stash pop
```

### 9.8 What to Include When Reporting Issues

```bash
illumio-ops --version
git -C /opt/illumio-ops rev-parse HEAD
grep -n "ERROR\|Exception\|Traceback" /opt/illumio-ops/logs/illumio_ops.log | tail -30
```

> When attaching configuration, mask `api.key`/`api.secret` and all passwords/tokens; never leak them.

---

## Related Documents

- [Getting Started](getting-started.md)
- [CLI Reference](reference/cli.md)
- [Glossary](reference/glossary.md)
