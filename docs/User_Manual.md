# Illumio PCE Ops — User Manual

<!-- BEGIN:doc-map -->
| Document | EN | 中文 |
|---|---|---|
| README | [README.md](../README.md) | [README_zh.md](../README_zh.md) |
| User Manual | [User_Manual.md](./User_Manual.md) | [User_Manual_zh.md](./User_Manual_zh.md) |
| Architecture | [Architecture.md](./Architecture.md) | [Architecture_zh.md](./Architecture_zh.md) |
| Security Rules | [Security_Rules_Reference.md](./Security_Rules_Reference.md) | [Security_Rules_Reference_zh.md](./Security_Rules_Reference_zh.md) |
<!-- END:doc-map -->

---

## 1. Execution Modes

### 1.1 Interactive CLI

```bash
python illumio_ops.py
```

Launches a text-based menu for managing rules, settings, and running manual checks.

```text
╭── Illumio PCE Ops
│ API: https://pce.lab.local:8443 | Rules: 16
│ Shortcuts: Enter=default | 0=back | -1=cancel | h/?=help
├────────────────────────────────────────────────────
│  1. Alert Rules
│  2. Report Generation
│  3. Rule Scheduler
│  4. System Settings
│  5. Launch Web GUI
│  6. View System Logs
│  7. Web GUI Security
│  0. Exit
╰──��───────────────��─────────────────────────────────
```

Select **1. Alert Rules** to enter the sub-menu:

```text
│ 1. Add Event Rule
│ 2. Add Traffic Rule
│ 3. Add Bandwidth & Volume Rule
│ 4. Manage Rules
│ 5. Load Official Best Practices
│ 6. Send Test Alert
│ 7. Run Analysis & Send Alerts
│ 8. Rule Simulation & Debug Mode
│ 0. Back
```

Select **2. Report Generation** to enter the sub-menu:

```text
│ 1. Generate Traffic Flow Report
│ 2. Generate Audit Log Report
│ 3. Generate VEN Status Report
│ 4. Generate Policy Usage Report
│ 5. Report Schedule Management
│ 0. Back
```

Select **3. Rule Scheduler** to enter the sub-menu:

```text
│ 1. Schedule Management (Add/Delete)
│ 2. Run Schedule Check Now
│ 3. Scheduler Settings (Enable/Disable Daemon, Interval)
│ 0. Back
```

> **Note**: **4. System Settings**, **5. Launch Web GUI**, and **6. View System Logs** are single-step actions with no sub-menu.


### 1.2 Web GUI

```bash
python illumio_ops.py --gui
python illumio_ops.py --gui --port 8080    # Custom port
```

Opens a browser-based dashboard at `http://127.0.0.1:5001` with tabs for:

| Tab | Features |
|:---|:---|
| **Dashboard** | API connectivity, rule summary, PCE health check; Traffic Analyzer with Top-10 widgets (by bandwidth / volume / flow count); saved dashboard queries |
| **Rules** | Full CRUD for Event/Traffic/Bandwidth/Volume rules, bulk delete, inline edit |
| **Reports** | Generate Traffic, Audit, VEN Status, and **Policy Usage** reports; **Bulk-Delete** with multi-select; download HTML/CSV raw data ZIP; retention management |
| **Report Schedules** | Create/edit/toggle recurring schedules (daily/weekly/monthly) with email delivery; trigger on demand; view run history |
| **Rule Scheduler** | Browse all PCE rulesets; enable/disable individual rules with optional TTL; provision changes |
| **Workload Search** | Search by hostname/IP/label; apply Quarantine labels (single or bulk) |
| **Settings** | API credentials, alert channels, timezone, language/theme switching, **PCE profile management** |
| **Actions** | Run Monitor Once, Debug Mode, Test Alert, Load Best Practices |

### 1.3 Background Daemon

```bash
python illumio_ops.py --monitor                 # Default: every 10 minutes
python illumio_ops.py --monitor --interval 5     # Every 5 minutes
```

Runs unattended in the background. Handles `SIGINT`/`SIGTERM` gracefully for clean shutdowns.

### 1.4 Persistent Mode (Daemon + Web GUI)

```bash
python illumio_ops.py --monitor-gui --interval 10 --port 5001
```

This mode runs the **Background Daemon** and the **Web GUI** concurrently in a single process.
- The daemon runs in a background thread.
- The Flask Web GUI runs in the main thread.
- **Mandatory Security**: Authentication and IP filters are strictly enforced.
- **Restricted Actions**: The `/api/shutdown` endpoint is disabled in this mode to prevent accidental termination of the persistent service.

### 1.5 Command-Line Reference

```bash
python illumio_ops.py [OPTIONS]
```

| Flag | Default | Description |
|:---|:---|:---|
| `--monitor` | — | Run in headless daemon mode |
| `--monitor-gui` | — | Run daemon + Web GUI concurrently (Persistent Mode) |
| `-i` / `--interval N` | `10` | Monitoring interval in minutes |
| `--gui` | — | Launch the standalone Web GUI |
| `-p` / `--port N` | `5001` | Web GUI port |
| `--report` | — | Generate a report from the command line |
| `--report-type TYPE` | `traffic` | Report type: `traffic`, `audit`, `ven_status`, `policy_usage` |
| `--source api\|csv` | `api` | Report data source |
| `--file PATH` | — | CSV file path (used with `--source csv`) |
| `--format html\|csv\|all` | `html` | Report output format |
| `--email` | — | Send report by email after generation |
| `--output-dir PATH` | `reports/` | Output directory for report files |

**Examples:**

```bash
# Generate HTML traffic report for the last 7 days and email it
python illumio_ops.py --report --format html --email

# Generate audit report
python illumio_ops.py --report --report-type audit

# Generate VEN status report
python illumio_ops.py --report --report-type ven_status

# Generate policy usage report from CSV export
python illumio_ops.py --report --report-type policy_usage --source csv --file workloader_export.csv

# Generate report from CSV export and save both HTML + raw CSV
python illumio_ops.py --report --source csv --file traffic_export.csv --format all

# Web GUI on a custom port
python illumio_ops.py --gui --port 8080
```

#### `illumio-ops` click subcommands

The package also ships the `illumio-ops` entry-point CLI with the following subcommands:

| Subcommand | Synopsis | Example |
|---|---|---|
| `cache` | Manage the local PCE cache: backfill, status, retention | `illumio-ops cache backfill --source events --since 2026-01-01` |
| `monitor` | Run a single monitoring cycle (non-daemon) | `illumio-ops monitor` |
| `gui` | Start the standalone Web GUI | `illumio-ops gui --port 8080` |
| `report` | Generate a report from the CLI | `illumio-ops report --type traffic --format html` |
| `rule` | Inspect configured monitoring rules | `illumio-ops rule list --type traffic` |
| `siem` | Manage SIEM destinations: test, flush, status | `illumio-ops siem test splunk-hec` |
| `workload` | Fetch and display PCE workloads | `illumio-ops workload list --env prod --limit 100` |
| `config` | Validate or display `config.json` | `illumio-ops config validate` |
| `status` | Show daemon / scheduler / config status | `illumio-ops status` |
| `version` | Print the installed version | `illumio-ops version` |

> **Daemon mode note:** Use `--monitor-gui` to start the scheduler and Web GUI together (Persistent Mode, preferred for production). Use `--monitor` alone for a headless scheduler with no GUI.

> **SIEM operator commands:** `illumio-ops siem test`, `illumio-ops siem flush`, `illumio-ops siem status`.

#### `illumio-ops cache` subcommands

| Command | Options | Description |
|---|---|---|
| `cache backfill` | `--source events\|traffic`, `--since YYYY-MM-DD`, `--until YYYY-MM-DD` | Backfill the local SQLite cache from the PCE API for a historical date range |
| `cache status` | — | Show row counts and last-ingested timestamps for events, traffic_raw, and traffic_agg tables |
| `cache retention` | — | Display the configured retention policy (events, raw, aggregated) |

```bash
# Backfill the last 30 days of audit events
illumio-ops cache backfill --source events --since 2026-03-28

# Backfill traffic flows for a specific window
illumio-ops cache backfill --source traffic --since 2026-03-01 --until 2026-03-31

# Check cache health
illumio-ops cache status
```

The cache must be enabled in `config.json` (`pce_cache.enabled: true`) before backfill commands will succeed.

#### `illumio-ops siem` subcommands

| Command | Options | Description |
|---|---|---|
| `siem test <name>` | destination name argument | Send a synthetic `siem.test` event to the named destination; reports latency on success |
| `siem status` | — | Show per-destination pending / sent / failed counts and DLQ depth |
| `siem dlq --dest <name>` | `--limit N` (default 50) | List dead-letter queue entries for a destination |
| `siem replay --dest <name>` | `--limit N` (default 100) | Requeue DLQ entries as pending dispatch rows |
| `siem purge --dest <name>` | `--older-than N` (default 30 days) | Delete DLQ entries older than N days |

```bash
# Test a Splunk HEC destination
illumio-ops siem test splunk-hec

# Check dispatch health
illumio-ops siem status

# Inspect the DLQ
illumio-ops siem dlq --dest splunk-hec --limit 20

# Replay up to 500 entries after fixing the root cause
illumio-ops siem replay --dest splunk-hec --limit 500

# Clean up entries older than 7 days
illumio-ops siem purge --dest splunk-hec --older-than 7
```

#### `illumio-ops rule` subcommands

| Command | Options | Description |
|---|---|---|
| `rule list` | `--type event\|traffic\|bandwidth\|volume\|system\|all`, `--enabled-only` | List all configured monitoring rules, optionally filtered by type |

```bash
# List all rules
illumio-ops rule list

# List only traffic rules
illumio-ops rule list --type traffic

# List only enabled traffic rules
illumio-ops rule list --type traffic --enabled-only
```

#### `illumio-ops workload` subcommands

| Command | Options | Description |
|---|---|---|
| `workload list` | `--env <value>`, `--limit N` (default 50), `--enforcement full\|selective\|visibility_only\|idle\|all`, `--managed-only` | Fetch and display workloads from the PCE with optional filtering |

```bash
# List production workloads
illumio-ops workload list --env prod

# List all VEN-managed workloads in full enforcement
illumio-ops workload list --enforcement full --managed-only --limit 200
```

#### `illumio-ops config` subcommands

| Command | Options | Description |
|---|---|---|
| `config validate` | `--file <path>` | Validate `config.json` against the Pydantic schema; exits 0 on success, prints errors on failure |
| `config show` | `--section <name>` | Pretty-print current config (or one section: `api`, `smtp`, `web_gui`, etc.) |

```bash
# Validate the default config.json
illumio-ops config validate

# Validate a specific file
illumio-ops config validate --file /opt/illumio_ops/config/config.json

# Show only the web_gui section
illumio-ops config show --section web_gui
```

---

## 2. Rule Types & Configuration

### 2.1 Event Rules

Monitor PCE audit events (e.g., `agent.tampering`, `user.sign_in`).

| Parameter | Description | Example |
|:---|:---|:---|
| **Event Type** | PCE event identifier | `agent.tampering` |
| **Threshold Type** | `immediate` (alert on first occurrence) or `count` (cumulative) | `count` |
| **Threshold Count** | How many occurrences before alerting | `5` |
| **Time Window** | Rolling window in minutes | `10` |
| **Cooldown** | Minimum interval between repeated alerts | `30` |

**Built-in Event Catalog** (accessible via CLI/GUI):

| Category | Events |
|:---|:---|
| Agent Health | `agent_missed_heartbeats`, `agent_offline`, `agent_tampering` |
| Authentication | `login_failed`, `authentication_failed` |
| Policy Changes | `ruleset_create/update`, `rule_create/delete`, `policy_provision` |
| Workloads | `workload_create`, `workload_delete` |

> **Login failure alerts** include the username and source IP address in the alert body for rapid triage.

### 2.2 Traffic Rules

Detect connection anomalies by counting matching traffic flows.

| Parameter | Description |
|:---|:---|
| **Policy Decision** | `Blocked (2)`, `Potentially Blocked (1)`, `Allowed (0)`, or `All (3)` |
| **Port / Protocol** | Filter by destination port (e.g., `443`) or IP protocol number (e.g., `6` for TCP) |
| **Source/Dest Label** | Exact label match in `key=value` format (e.g., `role=Web`) |
| **Source/Dest IP** | IP address or CIDR range (e.g., `10.0.0.0/24`) |
| **Filter Direction** | `src_and_dst` (default, both must match) or `src_or_dst` (either side matches) |
| **Excludes** | Negative filters for Label (`ex_src_labels`, `ex_dst_labels`), IP (`ex_src_ip`, `ex_dst_ip`), or Port |

**Filter Direction Options:**

| Mode | Behaviour |
|:---|:---|
| **Src AND Dst** (default) | Both source and destination labels/IPs must match their respective filters |
| **Src only** | Only specify source filters — destination is unfiltered |
| **Dst only** | Only specify destination filters — source is unfiltered |
| **Src OR Dst** | Match if the specified label appears on either source or destination side |

### 2.3 Bandwidth & Volume Rules

Detect data exfiltration patterns.

| Type | Metric | Unit | Calculation |
|:---|:---|:---|:---|
| **Bandwidth** | Peak transmission rate | Auto-scaled (bps/Kbps/Mbps/Gbps) | Max of all matching flows |
| **Volume** | Cumulative data transfer | Auto-scaled (B/KB/MB/GB) | Sum of all matching flows |

> **Hybrid Calculation**: The system prioritizes "Delta interval" metrics. For long-lived connections without measurable deltas, it falls back to "Lifetime total" to prevent exfiltration from slipping unnoticed.

> **Auto-scale Units**: Bandwidth and volume values are automatically formatted with the most appropriate unit (e.g., 1500 bps → "1.5 Kbps", 2048 MB → "2.0 GB").

---

## 3. Web GUI Security

All Web GUI modes REQUIRE authentication and support source IP restrictions.

### First Login

Default credentials: **username `illumio`** / **password `illumio`**.

1. Log in with the default credentials.
2. **Change your password immediately** in the **Settings → Security** page.
3. Configure **IP Allowlisting** to restrict access to trusted networks.

> **Password Reset**: If you lose your password, edit `web_gui.password` in `config/config.json` to a new value (or remove it entirely to fall back to the default `illumio`). The value is plaintext.

### 3.1 Authentication

- **Password storage**: plaintext in `config.json` `web_gui.password`. Rationale: illumio_ops is designed for offline-isolated PCE management networks where all other config secrets (PCE API key/secret, LINE/SMTP/webhook tokens) are already plaintext; encrypting only the GUI password provides no real defense. Always change the default `illumio` on first login.
- **Login rate limiting**: 5 attempts per IP per minute (HTTP 429 on excess) via flask-limiter.
- **CSRF protection**: flask-wtf CSRFProtect — token delivered via `X-CSRF-Token` response header and `<meta>` tag; validated on all state-changing requests (POST/PUT/DELETE).
- **Security headers**: flask-talisman sets `Content-Security-Policy`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`. HSTS activates automatically when TLS is enabled.
- **Session Management**: flask-login session protection (`strong` mode); secure signed cookies (secret key auto-generated in `config.json`).
- **Configuration**: Change credentials via **CLI Menu 7. Web GUI Security** or Web GUI **Settings** page.
- **SMTP credentials**: Set `ILLUMIO_SMTP_PASSWORD` environment variable to avoid storing passwords in config file

### 3.2 IP Allowlisting

Restrict access to specific administrative workstations or subnets.
- **Format**: Supports individual IPs (e.g., `192.168.1.50`) or CIDR blocks (e.g., `10.0.0.0/24`).
- **Default**: If the list is empty, all IPs are allowed (provided they authenticate).
- **Enforcement**: Middleware checks the `X-Forwarded-For` or remote address on every request.

---

## 4. Alert Channels

Three channels operate concurrently. Activate them in `config.json` → `alerts.active`:

```json
{
    "alerts": {
        "active": ["mail", "line", "webhook"]
    }
}
```

### 4.1 Email (SMTP)

```json
{
    "email": { "sender": "monitor@company.com", "recipients": ["soc@company.com"] },
    "smtp": { "host": "smtp.company.com", "port": 587, "user": "", "password": "", "enable_auth": true, "enable_tls": true }
}
```

### 4.2 LINE Messaging API

```json
{
    "alerts": {
        "line_channel_access_token": "YOUR_TOKEN",
        "line_target_id": "USER_OR_GROUP_ID"
    }
}
```

### 4.3 Webhook

```json
{
    "alerts": {
        "webhook_url": "https://hooks.slack.com/services/xxx/yyy/zzz"
    }
}
```

Sends a standardized JSON payload containing `health_alerts`, `event_alerts`, `traffic_alerts`, and `metric_alerts` arrays. Compatible with Slack, Microsoft Teams, custom SOAR endpoints.

---

## 5. Quarantine (Workload Isolation)

The Quarantine feature enables you to tag compromised workloads with severity labels, which can then be used in Illumio policy rules to restrict their network access.

### Workflow

1. **Search** for the target workload(s) (by hostname, IP, or label) via Web GUI → **Workload Search**
2. **Select** one or more workloads, then choose a Quarantine level: `Mild`, `Moderate`, or `Severe`
3. The system **automatically creates** the Quarantine label type in the PCE if it doesn't exist
4. The system **appends** the Quarantine label to each workload's existing labels (preserving all others)

**Single vs. bulk apply**: Select a single workload and click **Apply Quarantine** for individual isolation. Check multiple workloads and click **Bulk Quarantine** to isolate them in parallel (up to 5 concurrent API calls).

> **Important**: Quarantine labels alone do not block traffic. You must create corresponding **Enforcement Boundaries** or **Deny Rules** in the PCE that reference the `Quarantine` label key to actually restrict traffic.

---

## 6. Multi-PCE Profile Management

The system supports monitoring multiple PCE instances through profile management.

### 6.1 Overview

Profiles store PCE connection credentials (URL, org ID, API key, secret) and can be switched at runtime without restarting the application.

### 6.2 Configuration

Manage profiles via:
- **Web GUI**: Settings → PCE Profiles section (add, edit, delete, activate)
- **CLI**: System Settings menu
- **config.json**: Direct editing of `pce_profiles` array and `active_pce_id`

```json
{
    "active_pce_id": "production",
    "pce_profiles": [
        {
            "name": "production",
            "url": "https://pce-prod.company.com:8443",
            "org_id": "1",
            "key": "api_xxx",
            "secret": "xxx"
        },
        {
            "name": "lab",
            "url": "https://pce-lab.company.com:8443",
            "org_id": "1",
            "key": "api_yyy",
            "secret": "yyy"
        }
    ]
}
```

### 6.3 Profile Switching

When you activate a profile, the system:
1. Copies the profile's credentials into the top-level `api` section
2. Reinitializes the `ApiClient` with the new credentials
3. All subsequent API calls use the new PCE connection

> **Note**: All rules and report schedules apply to the currently active PCE profile. Switching profiles does not reset existing rules.

---

## 7. Advanced Deployment

### 7.1 Windows Service (NSSM)

```powershell
nssm install IllumioOps "C:\Python312\python.exe" "C:\illumio_ops\illumio_ops.py" --monitor --interval 5
nssm set IllumioOps AppDirectory "C:\illumio_ops"
nssm start IllumioOps
```

### 7.2 Linux systemd

> **Preferred daemon flag:** Use `--monitor-gui` to run the scheduler and Web GUI together in a single process (Persistent Mode). Use `--monitor` only when you want a headless daemon with no GUI.

#### RHEL / CentOS (system Python)

```ini
# /etc/systemd/system/illumio-ops.service
[Unit]
Description=Illumio PCE Ops
After=network.target

[Service]
Type=simple
User=illumio
WorkingDirectory=/opt/illumio_ops
ExecStart=/usr/bin/python3 illumio_ops.py --monitor-gui --interval 5
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

#### Ubuntu / Debian (venv)

Create the venv first, then point `ExecStart` at the venv interpreter:

```bash
cd /opt/illumio_ops
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

```ini
# /etc/systemd/system/illumio-ops.service
[Unit]
Description=Illumio PCE Ops
After=network.target

[Service]
Type=simple
User=illumio
WorkingDirectory=/opt/illumio_ops
ExecStart=/opt/illumio_ops/venv/bin/python illumio_ops.py --monitor-gui --interval 5
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now illumio-ops
```


---

## 8. Rule Scheduler

The Rule Scheduler automatically enables or disables PCE security rules (Rule or Ruleset) based on time windows. Use cases include maintenance windows, business-hours-only access policies, and temporary allow rules with automatic expiry.

### 8.1 Schedule Types

| Type | Description | Example |
|:---|:---|:---|
| **Recurring** | Repeats on specified days within a time window | Mon–Fri 09:00–17:00 |
| **One-time** | Active until a specific expiration datetime, then auto-reverts | Expires 2026-04-10 18:00 |

> **Midnight wraparound**: Recurring schedules support time windows that cross midnight (e.g., 22:00–06:00). The system correctly evaluates whether "now" falls within the wrapped window.

### 8.2 CLI

Access via CLI main menu **3. Rule Scheduler**:
- **1. Schedule Management** — Browse all Rulesets/Rules and add/remove schedules
- **2. Run Schedule Check Now** — Manually trigger the scheduling engine
- **3. Scheduler Settings** — Enable/disable the background daemon and set the check interval

### 8.3 Web GUI

Access via the **Rule Scheduler** tab:
- Browse all Rulesets and expand individual Rules
- Quick-search Rulesets by name
- Create **Recurring** (time-window based) or **One-time** (auto-expiry) schedules
- View real-time schedule logs under the **Logs** sub-tab

### 8.4 Draft Policy Protection

> **Important**: Illumio PCE's Provision operation deploys **all draft policy changes at once**. If a schedule Provision runs while a rule is in a Draft state (meaning someone is actively editing it), **all incomplete draft changes in that policy version will be deployed** — a potentially critical security risk.

The system implements **multi-layer Draft state protection**:

| Protection Layer | Where | Behaviour |
|:---|:---|:---|
| **CLI — Add Schedule** | `rule_scheduler_cli.py` | Blocks scheduling if the rule **or its parent Ruleset** is in Draft; shows error message |
| **Web GUI — Add Schedule** | `gui.py` API | Same check; rejects POST with `Unprovisioned rules cannot be scheduled` |
| **Scheduler Engine — At Runtime** | `rule_scheduler.py` | If a scheduled rule is found in Draft state at execution time, skips Provision and writes a `[SKIP]` log |
| **API Client Layer** | `api_client.has_draft_changes()` | Central helper: checks the rule itself **and** its parent Ruleset for pending Draft changes |

#### Detection Logic (parent Ruleset takes priority)

```
1. Fetch the rule's Draft version → if update_type is non-empty → DRAFT (stop)
2. If it's a child rule (href contains /sec_rules/) → fetch parent Ruleset's Draft version
   → if parent Ruleset's update_type is non-empty → DRAFT (stop)
3. Neither has Draft changes → safe to proceed
```

#### Log Output

- Draft blocks a schedule **configuration attempt** → error shown on screen only, no log file entry
- Draft blocks a schedule **execution** → `WARNING` level log entry for audit trail

```
[SKIP] CoreServices_Rule_1499 (ID:1499) is in DRAFT state. Operation aborted.
```

---

## 9. Settings Reference

### 9.1 Timezone

The timezone setting controls how timestamps are displayed in reports and schedule input fields. Configure it in Web GUI → **Settings → Timezone**, or directly in `config.json`:

```json
{
    "settings": {
        "timezone": "UTC+8"
    }
}
```

Supported formats: `local` (system timezone), `UTC`, `UTC+8`, `UTC-5`, `UTC+5.5`

> Schedule times are always **stored as UTC** internally. The CLI wizard and Web GUI schedule modal automatically convert to/from your configured timezone for display.

### 9.2 Dashboard Queries

The Dashboard tab supports saving custom traffic queries for repeated use. Each saved query stores filter parameters (policy decision, port, label, IP range, filter direction) and can be run on demand from the Dashboard to populate the Top-10 widgets.

Queries are stored in `config.json` → `settings.dashboard_queries` and are managed entirely through the Web GUI.

### 9.3 Report Output

Controls where reports are saved and how long they are kept.

| Setting | Default | Description |
|:---|:---|:---|
| `report.output_dir` | `reports/` | Directory for generated reports (relative to project root, or absolute path) |
| `report.retention_days` | `30` | Auto-delete `.html`/`.zip` reports older than this many days after each scheduled run. Set to `0` to disable. |

**Configure from Web GUI**: Settings → **Report Output** fieldset
**Configure from CLI**: System Settings menu → **4. System Settings**
**Configure from `config.json`**:
```json
{
    "report": {
        "output_dir": "reports/",
        "retention_days": 30
    }
}
```

### 9.4 Web GUI

The `web_gui` block in `config.json` controls authentication and the web server bind settings.

| Key | Type | Default | Description |
|---|---|---|---|
| `web_gui.username` | string | `illumio` | Login username for the single-admin account |
| `web_gui.password` | string | `illumio` | **Plaintext.** Default `illumio`; **change on first login**. The GUI compares this string directly against the form input — no hashing. |
| `web_gui.allowed_ips` | list | `[]` | IP allowlist — empty list permits all sources |
| `web_gui.tls.enabled` | bool | `false` | Enable HTTPS (requires `cert_file` + `key_file` or `self_signed: true`) |

**Port:** the GUI port is set on the command line via `--port N` (default `5001`); it is not persisted in `config.json`.

**Bind host:** the GUI bind address is set on the command line via `--host` (default `127.0.0.1`); it is not persisted in `config.json`.

> **Security note:** The default credentials `illumio` / `illumio` are documented in `config.json.example`. Change them immediately after first login via Web GUI → **Settings → Web GUI Security**.

### 9.5 Report Intelligence

These keys live under the `report` block in `config.json` and control advanced report behaviour.

| Key | Type | Default | Description |
|---|---|---|---|
| `report.snapshot_retention_days` | int | `90` | How long Change Impact (`mod_change_impact`) KPI snapshots are retained before auto-pruning |
| `report.threat_intel_csv_path` | string | `null` | Absolute path to an optional CSV of known-bad IPs, consumed by `mod_exfiltration_intel` for threat-match enrichment |
| `report.draft_actions_enabled` | bool | `true` | Whether `mod_draft_actions` produces per-flow remediation suggestions in the Traffic Report |

Example `config.json` fragment:

```json
{
    "report": {
        "snapshot_retention_days": 90,
        "threat_intel_csv_path": "/opt/illumio_ops/data/threat_intel.csv",
        "draft_actions_enabled": true
    }
}
```

### 9.6 PCE Cache

The `pce_cache` block controls the local SQLite cache that stores events and traffic flows for fast offline analysis.

| Key | Type | Default | Description |
|---|---|---|---|
| `pce_cache.enabled` | bool | `false` | Enable background ingestion from the PCE |
| `pce_cache.db_path` | string | `data/pce_cache.sqlite` | Path to the SQLite database file (relative to project root or absolute) |
| `pce_cache.events_retention_days` | int | `90` | Keep audit events for this many days |
| `pce_cache.traffic_raw_retention_days` | int | `7` | Keep raw per-flow records for this many days |
| `pce_cache.traffic_agg_retention_days` | int | `90` | Keep hourly-aggregated traffic for this many days |
| `pce_cache.events_poll_interval_seconds` | int | `300` | How often (in seconds) the events poller fetches new events from the PCE |
| `pce_cache.traffic_poll_interval_seconds` | int | `3600` | How often (in seconds) the traffic poller runs an async query |
| `pce_cache.rate_limit_per_minute` | int | `400` | Maximum PCE API calls per minute (max 500) |

**Enabling the cache:**

```json
{
    "pce_cache": {
        "enabled": true,
        "db_path": "data/pce_cache.sqlite",
        "events_retention_days": 90,
        "traffic_raw_retention_days": 7,
        "traffic_agg_retention_days": 90,
        "events_poll_interval_seconds": 300,
        "traffic_poll_interval_seconds": 3600,
        "rate_limit_per_minute": 400
    }
}
```

> **SIEM dependency:** The SIEM forwarder requires the PCE cache to be enabled. Traffic and event data is ingested into `pce_cache.sqlite` first, then dispatched to SIEM destinations from the `siem_dispatch` table.

> **Disk sizing:** Raw traffic rows are kept for only 7 days by default. For a typical PCE with 200,000 flows/day, expect approximately 1 GB per 7-day window. Aggregated traffic (hourly summaries) uses ~5 % of raw storage.

### 9.7 Alert Channels Reference

| Channel | Config keys | Auth requirement |
|---|---|---|
| Email (SMTP) | `smtp.host`, `smtp.port`, `smtp.user`, `smtp.password`, `smtp.enable_tls` | Depends on server; `smtp.enable_auth: false` for unauthenticated relay |
| LINE Messaging API | `alerts.line_channel_access_token`, `alerts.line_target_id` | LINE Developer Console: Channel Access Token + User/Group ID |
| Webhook | `alerts.webhook_url` | Caller provides full URL including any auth token |

Activate a channel by adding its identifier to `alerts.active`:

```json
{
    "alerts": {
        "active": ["mail", "line", "webhook"]
    }
}
```

Channels not listed in `alerts.active` are silently skipped even if their credentials are populated.

**Alert body fields** (included in every alert regardless of channel):

| Field | Description |
|---|---|
| `rule_name` | Name of the triggered rule |
| `rule_type` | `event`, `traffic`, `bandwidth`, or `volume` |
| `trigger_value` | The measured value that caused the alert |
| `threshold` | The configured threshold that was exceeded |
| `timestamp` | UTC ISO-8601 timestamp of the triggering event |
| `pce_url` | Active PCE profile URL for context |

> **Login failure alerts** include the source IP and username from the PCE audit event, enabling rapid triage without needing to query the PCE Console separately.

> **Cooldown:** Each rule has a configurable cooldown period (in minutes). Alerts will not re-fire for the same rule until the cooldown expires, preventing alert storms from repeated identical events.

> **Test alert:** Use CLI option **1. Alert Rules → 6. Send Test Alert** or `illumio-ops` Web GUI → **Actions → Test Alert** to verify your alert channel is configured and reachable before relying on it in production.

---

## 10. Troubleshooting

| Symptom | Cause | Solution |
|:---|:---|:---|
| `Connection refused` | PCE unreachable | Verify `api.url` and network connectivity |
| `401 Unauthorized` | Invalid API credentials | Regenerate API Key in PCE Console |
| `410 Gone` | Async query expired | The traffic query result was cleaned up; re-run the query |
| `429 Too Many Requests` | API rate limiting | The system auto-retries with backoff; reduce query frequency if persistent |
| Web GUI won't start | Dependencies not installed | **Ubuntu/Debian**: use venv — `venv/bin/pip install -r requirements.txt`. **RHEL**: `python3 -m venv venv && venv/bin/pip install -r requirements.txt` |
| `externally-managed-environment` pip error | Ubuntu/Debian PEP 668 | Create a venv: `python3 -m venv venv && venv/bin/pip install -r requirements.txt` |
| No alerts received | Channel not activated | Ensure `alerts.active` array includes your channel(s) |
| Report shows all VENs as online | Old cached state | Ensure `hours_since_last_heartbeat` is returned by your PCE version; check PCE API response for `agent.status` fields |
| Rule Scheduler shows `[SKIP]` log | Rule or parent Ruleset in Draft | Complete and Provision the policy edits in PCE Console; the schedule will resume automatically |
| PCE profile switch has no effect | ApiClient not reinitialized | Use the GUI "Activate" button or CLI profile switch, which triggers reinitialization |
| Policy Usage report shows 0 hits | Rules are draft-only | Only active (provisioned) rules are queried; provision draft rules first |
| `PDF export is not available in this build` | Offline bundle excludes reportlab (pure Python; no WeasyPrint/Pango/Cairo/GTK required) | Use `--format html` or `--format xlsx` instead |
| After upgrade: old config loaded | `config.json` preserved as-is | Compare with `config.json.example` and add any new fields |
| Windows: `nssm.exe not found` | NSSM not in PATH or bundle deploy\ | Add `nssm.exe` to PATH or place it in the bundle `deploy\` folder |
| `Cache database not configured` | `pce_cache.enabled` is false or `db_path` is wrong | Set `pce_cache.enabled: true` and verify the `db_path` is writable |
| SIEM test event fails with `Destination not found` | Destination name mismatch or `enabled: false` | Check `siem.destinations[].name` matches the argument; ensure `enabled: true` |
| `mod_change_impact` shows `skipped: no_previous_snapshot` | First report run or snapshot pruned | Generate a second report after the first; snapshots persist for `report.snapshot_retention_days` days |
| `config validate` exits non-zero with pydantic errors | Unknown key or wrong type in `config.json` | Fix the reported field; compare against `config.json.example` for reference |
| Web GUI login fails after uninstall + reinstall | Old `config.json` with stale plaintext `web_gui.password` was preserved | The plaintext password persists across upgrades; log in with the same password you used previously, or edit `web_gui.password` to a new value. |
| `--purge` accidentally removes config | Ran `uninstall.sh --purge` | The `--purge` flag is documented as destructive; restore from backup. Without `--purge`, config is always preserved. |


## See also

- [Installation](./Installation.md) — System requirements, platform-specific install, config.json
- [Report Modules](./Report_Modules.md) — Traffic reports, security findings, R3 intelligence, policy usage
- [SIEM Integration](./SIEM_Integration.md) — SIEM forwarder configuration, DLQ, transport selection
- [Security Rules Reference](./Security_Rules_Reference.md) — R-Series rules and `compute_draft` behaviour
