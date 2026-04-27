# Illumio PCE Ops — Comprehensive User Manual

---

## 1. Installation & Prerequisites

### 1.1 System Requirements
- **Python 3.8+** (tested up to 3.12)
- **Network Access** to Illumio PCE (HTTPS, default port `8443`)
- **(Optional)** `pip install flask` — required only for Web GUI mode

### 1.2 Installation

#### Red Hat / CentOS (RHEL 8+)

```bash
git clone <repo-url>
cd illumio_ops
cp config/config.json.example config/config.json

# Install optional dependencies from AppStream (no EPEL required)
sudo dnf install python3-flask python3-pandas python3-pyyaml
```

#### Red Hat / CentOS — Offline Bundle (air-gapped install)

Use this method when the target host has no internet access and cannot reach PyPI
or any package mirror. The bundle includes a portable CPython 3.12 interpreter and
all pre-built Python wheels — no `dnf`, no `python3`, no network required on the
target host.

> **Note:** PDF reports (`--format pdf`) are not available in the offline bundle.
> PDF export uses ReportLab (pure Python) and does not require WeasyPrint, Pango, Cairo, GTK, or GDK-PixBuf,
> but the ReportLab wheel is excluded from the air-gapped bundle to keep bundle size small.
> All other formats (HTML, XLSX, CSV) work normally.

##### Build the bundle (on any internet-connected Linux or WSL machine)

```bash
git clone <repo-url>
cd illumio_ops
bash scripts/build_offline_bundle.sh
# Output: dist/illumio_ops-<version>-offline-linux-x86_64.tar.gz
```

Transfer the `.tar.gz` to the air-gapped RHEL host (USB, SCP to a jump host, etc.).

##### First-time installation

```bash
tar xzf illumio_ops-<version>-offline-linux-x86_64.tar.gz
cd illumio_ops-<version>

# Validate the host environment before installing (exits 1 on any FAIL)
bash ./preflight.sh

# Install to /opt/illumio_ops, register systemd unit
sudo ./install.sh

# Fill in PCE API credentials (config.json was created from the example template)
sudo nano /opt/illumio_ops/config/config.json

# Enable and start the service
sudo systemctl enable --now illumio-ops
sudo systemctl status illumio-ops      # should show Active: active (running)
```

##### Upgrading to a new version

`install.sh` detects an existing installation and **never overwrites**:
- `config/config.json` — your PCE API credentials
- `config/rule_schedules.json` — your custom rule schedules

```bash
# 1. Stop the running service
sudo systemctl stop illumio-ops

# 2. Extract the new bundle (alongside the old one is fine)
tar xzf illumio_ops-<new-version>-offline-linux-x86_64.tar.gz
cd illumio_ops-<new-version>

# 3. Run install.sh — config.json and rule_schedules.json are preserved
sudo ./install.sh

# 4. Restart
sudo systemctl start illumio-ops
sudo systemctl status illumio-ops

# 5. Verify the new version
/opt/illumio_ops/python/bin/python3 /opt/illumio_ops/illumio_ops.py --version
```

> **If `report_config.yaml` was customised:** the upgrade replaces it with the
> bundled version (which may add new analysis parameters). Back it up before
> upgrading and re-apply your changes afterwards:
> ```bash
> sudo cp /opt/illumio_ops/config/report_config.yaml \
>         /opt/illumio_ops/config/report_config.yaml.bak
> # then run sudo ./install.sh, then merge your changes back
> ```

##### Verify offline build integrity

```bash
# Confirm reportlab is absent (offline bundle) and all other packages imported successfully
/opt/illumio_ops/python/bin/python3 \
    /opt/illumio_ops/scripts/verify_deps.py --offline-bundle
```

#### Windows — Offline Bundle (air-gapped install)

**Prerequisites:** NSSM (Non-Sucking Service Manager) — download from https://nssm.cc/download
and place `nssm.exe` in your system PATH or in the bundle's `deploy\` directory.

> **Note:** PDF reports (`--format pdf`) are not available in the offline bundle.
> PDF export uses ReportLab (pure Python) and does not require WeasyPrint, Pango, Cairo, GTK, or GDK-PixBuf,
> but the ReportLab wheel is excluded from the air-gapped bundle to keep bundle size small.
> All other formats (HTML, XLSX, CSV) work normally.

##### Build the bundle (on any internet-connected Linux or WSL machine)

```bash
git clone <repo-url>
cd illumio_ops
bash scripts/build_offline_bundle.sh
# Output: dist/illumio_ops-<version>-offline-windows-x86_64.zip
```

Transfer the `.zip` to the air-gapped Windows host.

##### First-time installation (run PowerShell as Administrator)

```powershell
# Extract the bundle (built-in Windows 11 / Server 2019+)
Expand-Archive illumio_ops-<version>-offline-windows-x86_64.zip -DestinationPath C:\

# Validate the host environment before installing (exits 1 on any FAIL)
cd C:\illumio_ops-<version>
.\preflight.ps1

# Install to C:\illumio_ops, register IllumioOps Windows service
.\install.ps1

# Fill in PCE API credentials
notepad C:\illumio_ops\config\config.json

# Verify the service is running
Get-Service IllumioOps
```

##### Upgrading to a new version (PowerShell as Administrator)

`install.ps1` detects an existing installation and **never overwrites**
`config\config.json` or `config\rule_schedules.json`.

```powershell
# 1. Stop the service
Stop-Service IllumioOps

# 2. Extract new bundle
Expand-Archive illumio_ops-<new-version>-offline-windows-x86_64.zip -DestinationPath C:\

# 3. Run install.ps1 — config preserved automatically
cd C:\illumio_ops-<new-version>
.\install.ps1

# 4. Verify
Get-Service IllumioOps   # should show Running
```

> **If `report_config.yaml` was customised:** back it up before upgrading:
> ```powershell
> Copy-Item C:\illumio_ops\config\report_config.yaml `
>           C:\illumio_ops\config\report_config.yaml.bak
> # then run .\install.ps1, then merge changes back
> ```

#### Ubuntu / Debian

Modern Ubuntu (22.04+) and Debian (12+) enforce **PEP 668** — direct `pip install` is blocked to protect the system Python. Use a virtual environment:

```bash
# Install venv support if not already present
sudo apt install python3-venv

git clone <repo-url>
cd illumio_ops
cp config/config.json.example config/config.json

# Create and activate a virtual environment inside the project directory
python3 -m venv venv
source venv/bin/activate          # bash/zsh
# source venv/bin/activate.fish   # Fish shell

pip install -r requirements.txt
```

> **Note**: You must re-activate the venv (`source venv/bin/activate`) each time you open a new terminal session before running the application.

#### macOS / Other (pip)

```bash
git clone <repo-url>
cd illumio_ops
pip install -r requirements.txt
```

#### Custom install root

`install.sh` accepts `--install-root` to deploy to a non-default path:

```bash
sudo ./install.sh --install-root /opt/custom_path
```

The systemd unit file is updated automatically to reference the chosen path.

#### Config preservation on upgrade

On upgrade, `install.sh` detects `config/config.json` and skips the entire `config/` tree (comment in source: *"Preserve all of config/ on upgrade — never overwrite operator-owned files"*). Only `*.example` templates are updated so operators can diff for new keys:

```bash
diff /opt/illumio_ops/config/config.json.example \
     /opt/illumio_ops/config/config.json
```

#### Uninstall

The installer places `uninstall.sh` inside the install root so removal is self-contained.

```bash
# Preserve config/ (default — safe for re-install)
sudo /opt/illumio_ops/uninstall.sh

# Remove everything, including config/ (--purge)
sudo /opt/illumio_ops/uninstall.sh --purge

# When running from a bundle directory, or with a custom install root
sudo ./uninstall.sh --install-root /opt/custom_path
```

Both variants stop and disable the `illumio-ops` systemd unit, remove the service file, and delete the `illumio_ops` system user. The default (no `--purge`) preserves `config/` in place — run `sudo rm -rf /opt/illumio_ops` afterwards to complete a full removal.

### 1.3 Configuration (`config.json`)

Copy the example config and fill in your PCE API credentials:

```bash
cp config/config.json.example config/config.json
```

| Field | Description | Example |
|:---|:---|:---|
| `api.url` | PCE hostname with port | `https://pce.lab.local:8443` |
| `api.org_id` | Organization ID | `"1"` |
| `api.key` | API Key username | `"api_1a2b3c4d5e6f"` |
| `api.secret` | API Key secret | `"your-secret-here"` |
| `api.verify_ssl` | SSL certificate verification | `true` or `false` |

> **How to obtain an API Key**: In the PCE Web Console, navigate to **User Menu → My API Keys → Add**. Select the appropriate role (minimum: `read_only` for monitoring, `owner` for quarantine operations).

---

## 2. Execution Modes

### 2.1 Interactive CLI

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


### 2.2 Web GUI

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

### 2.3 Background Daemon

```bash
python illumio_ops.py --monitor                 # Default: every 10 minutes
python illumio_ops.py --monitor --interval 5     # Every 5 minutes
```

Runs unattended in the background. Handles `SIGINT`/`SIGTERM` gracefully for clean shutdowns.

### 2.4 Persistent Mode (Daemon + Web GUI)

```bash
python illumio_ops.py --monitor-gui --interval 10 --port 5001
```

This mode runs the **Background Daemon** and the **Web GUI** concurrently in a single process.
- The daemon runs in a background thread.
- The Flask Web GUI runs in the main thread.
- **Mandatory Security**: Authentication and IP filters are strictly enforced.
- **Restricted Actions**: The `/api/shutdown` endpoint is disabled in this mode to prevent accidental termination of the persistent service.

### 2.5 Command-Line Reference

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

---

## 3. Rule Types & Configuration

### 3.1 Event Rules

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

### 3.2 Traffic Rules

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

### 3.3 Bandwidth & Volume Rules

Detect data exfiltration patterns.

| Type | Metric | Unit | Calculation |
|:---|:---|:---|:---|
| **Bandwidth** | Peak transmission rate | Auto-scaled (bps/Kbps/Mbps/Gbps) | Max of all matching flows |
| **Volume** | Cumulative data transfer | Auto-scaled (B/KB/MB/GB) | Sum of all matching flows |

> **Hybrid Calculation**: The system prioritizes "Delta interval" metrics. For long-lived connections without measurable deltas, it falls back to "Lifetime total" to prevent exfiltration from slipping unnoticed.

> **Auto-scale Units**: Bandwidth and volume values are automatically formatted with the most appropriate unit (e.g., 1500 bps → "1.5 Kbps", 2048 MB → "2.0 GB").

---

## 4. Web GUI Security

All Web GUI modes REQUIRE authentication and support source IP restrictions.

### First Login

Default credentials: **username `illumio`** / **password `illumio`**.

1. Log in with the default credentials.
2. **Change your password immediately** in the **Settings → Security** page.
3. Configure **IP Allowlisting** to restrict access to trusted networks.

> **Password Reset**: If you lose your password, delete the `password_hash` and `password_salt` keys from the `web_gui` section in `config/config.json` to reset to defaults.

### 4.1 Authentication

- **Password hashing**: argon2id via argon2-cffi (memory-hard, OWASP-recommended). Legacy PBKDF2 hashes automatically upgrade to argon2id on next successful login — no manual action needed.
- **Login rate limiting**: 5 attempts per IP per minute (HTTP 429 on excess) via flask-limiter.
- **CSRF protection**: flask-wtf CSRFProtect — token delivered via `X-CSRF-Token` response header and `<meta>` tag; validated on all state-changing requests (POST/PUT/DELETE).
- **Security headers**: flask-talisman sets `Content-Security-Policy`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`. HSTS activates automatically when TLS is enabled.
- **Session Management**: flask-login session protection (`strong` mode); secure signed cookies (secret key auto-generated in `config.json`).
- **Configuration**: Change credentials via **CLI Menu 7. Web GUI Security** or Web GUI **Settings** page.
- **SMTP credentials**: Set `ILLUMIO_SMTP_PASSWORD` environment variable to avoid storing passwords in config file

### 4.2 IP Allowlisting

Restrict access to specific administrative workstations or subnets.
- **Format**: Supports individual IPs (e.g., `192.168.1.50`) or CIDR blocks (e.g., `10.0.0.0/24`).
- **Default**: If the list is empty, all IPs are allowed (provided they authenticate).
- **Enforcement**: Middleware checks the `X-Forwarded-For` or remote address on every request.

---

## 5. Alert Channels

Three channels operate concurrently. Activate them in `config.json` → `alerts.active`:

```json
{
    "alerts": {
        "active": ["mail", "line", "webhook"]
    }
}
```

### 5.1 Email (SMTP)

```json
{
    "email": { "sender": "monitor@company.com", "recipients": ["soc@company.com"] },
    "smtp": { "host": "smtp.company.com", "port": 587, "user": "", "password": "", "enable_auth": true, "enable_tls": true }
}
```

### 5.2 LINE Messaging API

```json
{
    "alerts": {
        "line_channel_access_token": "YOUR_TOKEN",
        "line_target_id": "USER_OR_GROUP_ID"
    }
}
```

### 5.3 Webhook

```json
{
    "alerts": {
        "webhook_url": "https://hooks.slack.com/services/xxx/yyy/zzz"
    }
}
```

Sends a standardized JSON payload containing `health_alerts`, `event_alerts`, `traffic_alerts`, and `metric_alerts` arrays. Compatible with Slack, Microsoft Teams, custom SOAR endpoints.

---

## 6. Quarantine (Workload Isolation)

The Quarantine feature enables you to tag compromised workloads with severity labels, which can then be used in Illumio policy rules to restrict their network access.

### Workflow

1. **Search** for the target workload(s) (by hostname, IP, or label) via Web GUI → **Workload Search**
2. **Select** one or more workloads, then choose a Quarantine level: `Mild`, `Moderate`, or `Severe`
3. The system **automatically creates** the Quarantine label type in the PCE if it doesn't exist
4. The system **appends** the Quarantine label to each workload's existing labels (preserving all others)

**Single vs. bulk apply**: Select a single workload and click **Apply Quarantine** for individual isolation. Check multiple workloads and click **Bulk Quarantine** to isolate them in parallel (up to 5 concurrent API calls).

> **Important**: Quarantine labels alone do not block traffic. You must create corresponding **Enforcement Boundaries** or **Deny Rules** in the PCE that reference the `Quarantine` label key to actually restrict traffic.

---

## 7. Multi-PCE Profile Management

The system supports monitoring multiple PCE instances through profile management.

### 7.1 Overview

Profiles store PCE connection credentials (URL, org ID, API key, secret) and can be switched at runtime without restarting the application.

### 7.2 Configuration

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

### 7.3 Profile Switching

When you activate a profile, the system:
1. Copies the profile's credentials into the top-level `api` section
2. Reinitializes the `ApiClient` with the new credentials
3. All subsequent API calls use the new PCE connection

> **Note**: All rules and report schedules apply to the currently active PCE profile. Switching profiles does not reset existing rules.

---

## 8. Advanced Deployment

### 8.1 Windows Service (NSSM)

```powershell
nssm install IllumioOps "C:\Python312\python.exe" "C:\illumio_ops\illumio_ops.py" --monitor --interval 5
nssm set IllumioOps AppDirectory "C:\illumio_ops"
nssm start IllumioOps
```

### 8.2 Linux systemd

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

## 9. Traffic Reports & Security Findings

### 9.1 Generating Reports

Reports can be triggered from three places:

| Location | How |
|:---|:---|
| Web GUI → Reports tab | Click **Traffic Report**, **Audit Summary**, **VEN Status**, or **Policy Usage** |
| CLI → **2. Report Generation** sub-menu items 1–4 | Select report type and date range |
| Daemon mode | Configure via CLI **2. Report Generation → 5. Report Schedule Management** — reports run automatically and can be emailed |
| Command line | `python illumio_ops.py --report --report-type traffic\|audit\|ven_status\|policy_usage` |

Reports are saved to the `reports/` directory as `.html` (formatted report) and/or `_raw.zip` (CSV raw data) depending on your format setting.

**Dependencies required:**
```bash
pip install pandas pyyaml
```

### Reporting from cached PCE data

When `pce_cache.enabled = true` in `config.json`, Audit and Traffic reports automatically read from the local SQLite cache when the requested date range falls within the retention window. This reduces PCE API load and speeds up report generation.

If the requested range is outside the retention window, the report falls back to the live PCE API transparently.

To import historical data outside the retention window, use the backfill command:

```bash
illumio-ops cache backfill --source events --since YYYY-MM-DD --until YYYY-MM-DD
```

See `docs/PCE_Cache.md` for full details.

### 9.2 Report Types Overview

| Report Type | Data Source | Modules | Description |
|:---|:---|:---|:---|
| **Traffic** | PCE async traffic query or CSV | 15 modules + 19 Security Findings | Comprehensive traffic security analysis |
| **Audit** | PCE events API | 4 modules | System health, user activity, policy changes |
| **VEN Status** | PCE workloads API | Single generator | VEN inventory with online/offline classification |
| **Policy Usage** | PCE rulesets + traffic queries, or Workloader CSV | 4 modules | Per-rule traffic hit analysis |

### 9.3 Report Sections (Traffic Report)

A traffic report contains **15 analytical modules** plus the Security Findings section:

| Section | Description |
|:---|:---|
| Executive Summary | KPI cards: total flows, policy coverage %, top findings |
| 1 - Traffic Overview | Total flows, allowed/blocked/PB breakdown, top ports |
| 2 - Policy Decisions | Per-decision breakdown with inbound/outbound split and per-port coverage % |
| 3 - Uncovered Flows | Flows without an allow rule; port gap ranking; uncovered services (app+port) |
| 4 - Ransomware Exposure | **Investigation targets** (destination hosts with ALLOWED traffic on critical/high ports) prominently highlighted; per-port detail; host exposure ranking |
| 5 - Remote Access | SSH/RDP/VNC/TeamViewer traffic analysis |
| 6 - User & Process | User accounts and processes appearing in flow records |
| 7 - Cross-Label Matrix | Traffic matrix between environment/app/role label combinations |
| 8 - Unmanaged Hosts | Traffic from/to non-PCE-managed hosts; per-app and per-port detail |
| 9 - Traffic Distribution | Port and protocol distribution |
| 10 - Allowed Traffic | Top allowed flows; audit flags |
| 11 - Bandwidth & Volume | Top flows by bytes + Bandwidth (auto-scaled units); Max/Avg/P95 stat cards; anomaly detection (P95 of multi-connection flows) |
| 13 - Enforcement Readiness | Score 0–100 with factor breakdown and remediation recommendations |
| 14 - Infrastructure Scoring | Node centrality scoring to identify critical services (in-degree, out-degree, betweenness) |
| 15 - Lateral Movement Risk | Lateral movement pattern analysis and high-risk paths |
| **Security Findings** | **Automated rule evaluation — see Section 9.5** |

### 9.4 Security Findings Rules

The Security Findings section runs **19 automated detection rules** against every traffic dataset and groups results by severity (CRITICAL → INFO) and category.

**Rule series overview:**

| Series | Rules | Focus |
|:---|:---|:---|
| **B-series** | B001–B009 | Ransomware exposure, policy coverage gaps, behavioural anomalies |
| **L-series** | L001–L010 | Lateral movement, credential theft, blast-radius paths, data exfiltration |

**Quick reference:**

| Rule | Severity | What it detects |
|:---|:---|:---|
| B001 | CRITICAL | Ransomware ports (SMB/RDP/WinRM/RPC) not blocked |
| B002 | HIGH | Remote-access tools (TeamViewer/VNC/NetBIOS) allowed |
| B003 | MEDIUM | Ransomware ports in test mode — block not enforced |
| B004 | MEDIUM | High volume from unmanaged (non-PCE) hosts |
| B005 | MEDIUM | Policy coverage below threshold |
| B006 | HIGH | Single source fan-out on lateral movement ports |
| B007 | HIGH | Single user reaching abnormally many destinations |
| B008 | MEDIUM | High bandwidth anomaly (potential exfiltration/backup) |
| B009 | INFO | Cross-environment traffic volume above threshold |
| L001 | HIGH | Cleartext protocols (Telnet/FTP) in use |
| L002 | MEDIUM | Network discovery protocols unblocked (LLMNR/NetBIOS/mDNS) |
| L003 | HIGH | Database ports reachable from too many application tiers |
| L004 | HIGH | Database flows crossing environment boundaries |
| L005 | HIGH | Kerberos/LDAP accessible from too many source applications |
| L006 | HIGH | High blast-radius lateral path (BFS graph analysis) |
| L007 | HIGH | Unmanaged hosts accessing database/identity/management ports |
| L008 | HIGH | Lateral ports in test mode — policies exist but not enforced |
| L009 | HIGH | Data exfiltration pattern (managed → unmanaged, high bytes) |
| L010 | CRITICAL | Lateral ports allowed across environment boundaries |

For full documentation of each rule — including trigger conditions, attack technique context, and tuning guidance — see **[Security Rules Reference](Security_Rules_Reference.md)**.

### 9.5 Audit Report Sections

The Audit Report contains **4 modules**:

| Module | Description |
|:---|:---|
| Executive Summary | Event counts by severity and category; top event types |
| 1 - System Health Events | `agent.tampering`, offline agents, heartbeat failures |
| 2 - User Activity | Authentication events, login failures, account changes |
| 3 - Policy Changes | Ruleset and rule create/update/delete, policy provisioning |

### 9.6 VEN Status Report

The VEN Status Report inventories all PCE-managed workloads and classifies VEN connectivity:

| Section | Description |
|:---|:---|
| KPI Summary | Total VENs, Online count, Offline count |
| Online VENs | VENs with active agent status **and** last heartbeat ≤ 1 hour ago |
| Offline VENs | VENs that are suspended/stopped, or active but heartbeat > 1 hour ago |
| Lost (last 24 h) | Offline VENs whose last heartbeat was within the past 24 hours |
| Lost (24–48 h ago) | Offline VENs whose last heartbeat was 24–48 hours ago |

Each row includes: hostname, IP, labels, VEN status, hours since last heartbeat, last heartbeat timestamp, policy received timestamp, VEN version.

> **Online detection**: The PCE's `agent.status.status = "active"` reflects **administrative** state only. A VEN can remain `"active"` while unreachable (no heartbeat). The report uses `hours_since_last_heartbeat` — a VEN is considered online only if its last heartbeat was ≤ 1 hour ago. This matches the PCE Web Console behaviour.

### 9.7 Policy Usage Report

The Policy Usage Report analyzes how actively each PCE security rule is being used by matching it against actual traffic flows.

| Module | Description |
|:---|:---|
| Executive Summary | Total rules, rules with traffic hits, coverage percentage |
| Overview | Enabled/disabled breakdown, active/draft status |
| Executive Summary (`pu_mod00_executive`) | Total rules, rules with traffic hits, coverage percentage |
| Overview (`pu_mod01_overview`) | Enabled/disabled breakdown, active/draft status |
| Hit Detail (`pu_mod02_hit_detail`) | Rules with matching traffic; top flows per rule |
| Unused Detail (`pu_mod03_unused_detail`) | Rules with zero traffic hits; candidates for cleanup |
| Deny Effectiveness (`pu_mod04_deny_effectiveness`) | Confirms deny/override-deny rules are actively blocking unwanted traffic |
| Draft Policy Decision (`pu_mod05_draft_pd`) | Per-rule draft policy decision risk — visibility risk, draft conflicts, and draft coverage gap across three lenses |

**Data Sources:**
- **API mode**: Fetches active rulesets from the PCE, then runs parallel async traffic queries for each rule to count matching flows
- **CSV mode**: Imports a Workloader CSV export with pre-computed flow counts (for offline analysis)

### 9.8 Tuning Security Rules

All detection thresholds are in `config/report_config.yaml`:

```yaml
thresholds:
  min_policy_coverage_pct: 30         # B005
  lateral_movement_outbound_dst: 10   # B006
  db_unique_src_app_threshold: 5      # L003
  blast_radius_threshold: 5           # L006
  exfil_bytes_threshold_mb: 100       # L009
  cross_env_lateral_threshold: 5      # L010
  # ... (see Security_Rules_Reference.md for complete list)
```

Edit this file and re-run a report to apply new thresholds — no restart required.

### 9.9 Report Schedules

Configure automated recurring reports via CLI **2. Report Generation → 5. Report Schedule Management** or Web GUI **Report Schedules** tab:

| Field | Description |
|:---|:---|
| Report Type | Traffic Flow / Audit / VEN Status / **Policy Usage** |
| Frequency | Daily / Weekly (day of week) / Monthly (day of month) |
| Time | Hour and minute — input in your **configured timezone** (automatically stored as UTC) |
| Lookback Days | How many days of traffic data to include |
| Output Format | HTML / CSV Raw ZIP / Both |
| Send by Email | Attach report to email using SMTP settings |
| Custom Recipients | Override default recipients for this schedule |

> **Timezone note**: The time fields in CLI and Web GUI always display in the timezone configured under Settings → Timezone. The underlying storage is UTC, so the schedule remains correct if you change the timezone setting.

The daemon loop checks schedules every 60 seconds and runs any schedule whose configured time has been reached.

After each successful run, old report files are automatically cleaned up according to the **retention policy** — see Section 11.3.

### 9.10 R3 Intelligence Modules

These modules run automatically as part of the Traffic Report pipeline and appear as dedicated sections in the HTML output.

| Module | Purpose | Input | Output | Related config |
|---|---|---|---|---|
| `mod_change_impact` | Compare current report KPIs to the previous snapshot; emit `improved` / `regressed` / `neutral` verdict per KPI | Current KPIs dict + previous JSON snapshot | Delta table + overall verdict + previous snapshot timestamp | `report.snapshot_retention_days` |
| `mod_draft_actions` | Actionable remediation suggestions for draft policy decision sub-categories that need human review: Override Deny, Allowed Across Boundary, what-if | Flows DataFrame with `draft_policy_decision` column | `override_deny` block, `allowed_across_boundary` block, `what_if_summary` | `report.draft_actions_enabled` |
| `mod_draft_summary` | Count all 7 draft policy decision subtypes and list top workload pairs per subtype | Flows DataFrame with `draft_policy_decision` column | `counts` dict (7 subtypes) + `top_pairs` per subtype | — |
| `mod_enforcement_rollout` | Rank applications by readiness score for moving to full enforcement | Flows DataFrame with app labels (`src_app` / `dst_app`) + optional draft / readiness summaries | Prioritized app list with score, `why_now` rationale, required allow rules, risk reduction | — |
| `mod_exfiltration_intel` | Flag managed-to-unmanaged flows with high byte volume; optionally join against a CSV of known-bad IPs for threat-match enrichment | Flows DataFrame with `src_managed` / `dst_managed` + optional `bytes` column | `high_volume_exfil` list, `managed_to_unmanaged_count`, `threat_intel_matches` | `report.threat_intel_csv_path` |
| `mod_ringfence` | Per-application dependency profile + candidate allow rules for micro-segmentation; top-app summary when no specific app is targeted | Flows DataFrame with `src_app` / `dst_app` labels | Per-app: intra-app flows, cross-app flows, cross-env flows, candidate allow rules; or top-20 apps list | — |

### 9.11 Draft Policy Decision Behaviour

**Auto-enable of `compute_draft`:** When a ruleset contains rules that use `requires_draft_pd` logic (i.e., the ruleset has pending draft changes), the reporting pipeline automatically enables draft policy decision computation for that ruleset's traffic flows.

**HTML report header pill:** When draft computation is active, the Traffic Report HTML header displays a "Draft Policy Active" indicator pill to make the draft scope visible at a glance.

**`draft_breakdown` cross-tab (from `mod_draft_summary`):** A 7-column cross-tabulation showing the count of flows for each draft policy decision subtype:

| Subtype | Meaning |
|---|---|
| `allowed` | Flow would be allowed by the draft ruleset |
| `potentially_blocked` | Flow has no matching draft rule; default-deny would block it |
| `blocked_by_boundary` | Blocked by a boundary rule in the draft |
| `blocked_by_override_deny` | Blocked by an Override Deny rule in the draft |
| `potentially_blocked_by_boundary` | On a visibility workload; draft boundary would block on enforcement |
| `potentially_blocked_by_override_deny` | On a visibility workload; draft override deny would block on enforcement |
| `allowed_across_boundary` | Allowed despite crossing an application boundary — review required |

**`draft_enforcement_gap` (from `mod_draft_summary` / `mod_draft_actions`):** The set of flows where `policy_decision = potentially_blocked` but the draft resolves to `allowed` or `blocked_by_boundary` — i.e., flows that currently have no rule but would be covered (or explicitly blocked) once the draft is provisioned. This gap quantifies the enforcement delta that will take effect at the next Provision.

---

## 10. Rule Scheduler

The Rule Scheduler automatically enables or disables PCE security rules (Rule or Ruleset) based on time windows. Use cases include maintenance windows, business-hours-only access policies, and temporary allow rules with automatic expiry.

### 10.1 Schedule Types

| Type | Description | Example |
|:---|:---|:---|
| **Recurring** | Repeats on specified days within a time window | Mon–Fri 09:00–17:00 |
| **One-time** | Active until a specific expiration datetime, then auto-reverts | Expires 2026-04-10 18:00 |

> **Midnight wraparound**: Recurring schedules support time windows that cross midnight (e.g., 22:00–06:00). The system correctly evaluates whether "now" falls within the wrapped window.

### 10.2 CLI

Access via CLI main menu **3. Rule Scheduler**:
- **1. Schedule Management** — Browse all Rulesets/Rules and add/remove schedules
- **2. Run Schedule Check Now** — Manually trigger the scheduling engine
- **3. Scheduler Settings** — Enable/disable the background daemon and set the check interval

### 10.3 Web GUI

Access via the **Rule Scheduler** tab:
- Browse all Rulesets and expand individual Rules
- Quick-search Rulesets by name
- Create **Recurring** (time-window based) or **One-time** (auto-expiry) schedules
- View real-time schedule logs under the **Logs** sub-tab

### 10.4 Draft Policy Protection

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

## 11. Settings Reference

### 11.1 Timezone

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

### 11.2 Dashboard Queries

The Dashboard tab supports saving custom traffic queries for repeated use. Each saved query stores filter parameters (policy decision, port, label, IP range, filter direction) and can be run on demand from the Dashboard to populate the Top-10 widgets.

Queries are stored in `config.json` → `settings.dashboard_queries` and are managed entirely through the Web GUI.

### 11.3 Report Output

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

### 11.4 Web GUI

The `web_gui` block in `config.json` controls authentication and the web server bind settings.

| Key | Type | Default | Description |
|---|---|---|---|
| `web_gui.username` | string | `illumio` | Login username for the single-admin account |
| `web_gui.password` | string | `illumio` | **Change on first login.** The GUI stores an Argon2 hash — the plain-text password in the example is only valid before first use. |
| `web_gui.bind_host` | string | `127.0.0.1` | Bind address; set to `0.0.0.0` to expose on all interfaces (use with `allowed_ips`) |
| `web_gui.port` | int | `5000` | Bind port; override with `--port N` on the command line |
| `web_gui.allowed_ips` | list | `[]` | IP allowlist — empty list permits all sources |
| `web_gui.tls.enabled` | bool | `false` | Enable HTTPS (requires `cert_file` + `key_file` or `self_signed: true`) |

> **Security note:** The default credentials `illumio` / `illumio` are documented in `config.json.example`. Change them immediately after first login via Web GUI → **Settings → Web GUI Security**.

### 11.5 Report Intelligence

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

---

## 12. Troubleshooting

| Symptom | Cause | Solution |
|:---|:---|:---|
| `Connection refused` | PCE unreachable | Verify `api.url` and network connectivity |
| `401 Unauthorized` | Invalid API credentials | Regenerate API Key in PCE Console |
| `410 Gone` | Async query expired | The traffic query result was cleaned up; re-run the query |
| `429 Too Many Requests` | API rate limiting | The system auto-retries with backoff; reduce query frequency if persistent |
| Web GUI won't start | Flask not installed | **Ubuntu/Debian**: use venv — `venv/bin/pip install flask pandas pyyaml`. **RHEL**: `dnf install python3-flask` |
| `externally-managed-environment` pip error | Ubuntu/Debian PEP 668 | Create a venv: `python3 -m venv venv && venv/bin/pip install flask pandas pyyaml` |
| No alerts received | Channel not activated | Ensure `alerts.active` array includes your channel(s) |
| Report shows all VENs as online | Old cached state | Ensure `hours_since_last_heartbeat` is returned by your PCE version; check PCE API response for `agent.status` fields |
| Rule Scheduler shows `[SKIP]` log | Rule or parent Ruleset in Draft | Complete and Provision the policy edits in PCE Console; the schedule will resume automatically |
| PCE profile switch has no effect | ApiClient not reinitialized | Use the GUI "Activate" button or CLI profile switch, which triggers reinitialization |
| Policy Usage report shows 0 hits | Rules are draft-only | Only active (provisioned) rules are queried; provision draft rules first |
| `PDF export is not available in this build` | Offline bundle excludes reportlab (pure Python; no WeasyPrint/Pango/Cairo/GTK required) | Use `--format html` or `--format xlsx` instead |
| After upgrade: old config loaded | `config.json` preserved as-is | Compare with `config.json.example` and add any new fields |
| Windows: `nssm.exe not found` | NSSM not in PATH or bundle deploy\ | Add `nssm.exe` to PATH or place it in the bundle `deploy\` folder |

---

# 5. SIEM Integration

# SIEM Forwarder

> [!WARNING]
> Status: **Preview** (2026-04-23).
> Existing deployments may continue to use SIEM forwarding for compatibility, but full production rollout should wait until runtime pipeline gaps are closed.
>
> Known gaps tracked in Task.md:
> - Runtime ingest path does not yet auto-enqueue SIEM dispatch rows.
> - Scheduler dispatch path is not yet wired to a full end-to-end consumer loop.
> - Payload-build failures can currently leave rows in persistent `pending` state.

## Architecture

```
PCE API
  └─► EventsIngestor / TrafficIngestor
           │  (rate-limited, watermarked)
           ▼
      pce_cache.sqlite
           │
     siem_dispatch table
           │
      SiemDispatcher (tick every 5s)
           │
      ┌────┴───────────────────┐
      │         Formatter      │
      │  CEF 0.1 / JSON Lines  │
      │  + RFC5424 syslog hdr  │
      └────┬───────────────────┘
           │
      ┌────┴───────────────────┐
      │       Transport        │
      │  UDP / TCP / TLS / HEC │
      └────────────────────────┘
           │  (failure → DLQ)
           ▼
      SIEM / Splunk / Elastic
```

## Prerequisites

PCE cache must be enabled first (`pce_cache.enabled: true`).

## Enabling

Add to `config/config.json`:

```json
"siem": {
  "enabled": true,
  "destinations": [
    {
      "name": "splunk-hec",
      "transport": "hec",
      "format": "json",
      "endpoint": "https://splunk.example.com:8088",
      "hec_token": "your-hec-token-here",
      "source_types": ["audit", "traffic"],
      "max_retries": 10
    }
  ]
}
```

## Destination Config Schema

| Field | Type | Default | Description |
|---|---|---|---|
| `name` | string | required | Unique identifier (1–64 chars) |
| `transport` | udp\|tcp\|tls\|hec | required | Wire protocol |
| `format` | cef\|json\|syslog_cef\|syslog_json | `cef` | Log line format |
| `endpoint` | string | required | `host:port` for syslog; full URL for HEC |
| `tls_verify` | bool | `true` | Verify TLS certificate (disable only for dev) |
| `tls_ca_bundle` | string | null | Path to CA bundle for custom PKI |
| `hec_token` | string | null | Splunk HEC token (required for `transport: hec`) |
| `batch_size` | int | 100 | Rows per dispatcher tick |
| `source_types` | list | `["audit","traffic"]` | Which data to forward |
| `max_retries` | int | 10 | Retries before quarantine |

## Format Samples

**CEF (audit event):**
```
CEF:0|Illumio|PCE|3.11|policy.update|policy.update|3|rt=1745049600000 dvchost=pce.example.com externalId=uuid-abc outcome=success
```

**JSON Lines (traffic flow):**
```json
{"src_ip":"10.0.0.1","dst_ip":"10.0.0.2","port":443,"protocol":"tcp","action":"blocked","flow_count":5}
```

**RFC5424 syslog envelope (wraps any format):**
```
<14>1 2026-04-19T10:00:00.000Z pce.example.com illumio-ops - - - CEF:0|Illumio|PCE|...
```

Use `format: syslog_cef` or `format: syslog_json` to enable the RFC5424 wrapper.

## Testing a Destination

```bash
illumio-ops siem test splunk-hec
```

Sends one synthetic `siem.test` event and reports success or failure with the error message.

## DLQ Operator Guide

When a destination fails `max_retries` times, the dispatch row moves to the `dead_letter` table. Inspect with:

```bash
illumio-ops siem dlq --dest splunk-hec
```

After fixing the root cause (bad token, network partition, etc.), replay:

```bash
illumio-ops siem replay --dest splunk-hec --limit 1000
```

Purge old entries that are no longer needed:

```bash
illumio-ops siem purge --dest splunk-hec --older-than 30
```

## Transport Selection Guide

| Transport | Delivery | Ordering | Encryption | Use case |
|---|---|---|---|---|
| UDP | Best-effort | No | No | Low-value, high-volume; fire-and-forget |
| TCP | At-least-once | Yes | No | Internal network, no TLS required |
| TLS | At-least-once | Yes | Yes | **Recommended** for production |
| HEC | At-least-once | Yes | Yes (HTTPS) | Splunk environments |

UDP is available but **not recommended for production** — the GUI will show a warning banner when you configure a UDP destination.

## Backoff Schedule

Failed sends are retried with exponential backoff capped at 1 hour:

| Retry | Wait |
|---|---|
| 1 | 10s |
| 2 | 20s |
| 3 | 40s |
| 4 | 80s |
| 5 | 160s |
| 6 | 320s |
| 7 | 640s |
| 8 | 1280s |
| 9 | 2560s |
| 10 | 3600s (cap) |

---

# Appendix A — Report Module Inventory

> Translated from `docs/report_module_inventory_zh.md` (ed20df0~1) — refresh in Phase B.

# Report Module Inventory And Reader Guidance

本文盤點 illumio_ops 既有報表模組的實務價值，並定義每個章節應補充的導讀內容。目標是讓報表讀者不只看到圖表和表格，而是能理解「這章在回答什麼問題」、「哪些現象需要注意」、「下一步該做什麼」。

## NotebookLM 佐證摘要

根據 Illumio 筆記本中的手冊、API guide 與微分段技術說明，Traffic / Flow Visibility 在微分段專案中通常同時服務多個角色：

- 資安/SOC：威脅獵捕、異常偵測、事件回應、橫向移動與資料外洩調查。
- 網管/平台團隊：掌握連線相依性、建立 label-based allow rules、排查未納管或未知依賴。
- DevOps / DevSecOps：理解服務間連線，避免 CI/CD 或微服務變更破壞安全策略。
- App Owner：確認應用上下游依賴，審核合理白名單需求。

因此 Traffic Report 不應只是一份大而全報表。建議拆成兩種 profile：

- Security Risk Traffic Report：聚焦異常、危險流量、橫向移動、勒索軟體高風險埠、PB exposure、blocked/denied patterns、外部威脅或外洩跡象。
- Network Inventory Traffic Report：聚焦應用相依性、label matrix、candidate allow rules、shared infrastructure usage、unmanaged/unknown dependencies、enforcement readiness。

NotebookLM 也建議每個章節採固定導讀格式：

- 本章目的：這章回答什麼業務或資安問題。
- 要注意的訊號：哪些值、趨勢、組合代表異常或需要處理。
- 判讀方式：如何理解圖表、Policy Decision、label matrix 或風險分數。
- 建議行動：讀者看完後應調查、建規則、修 label、隔離、清理規則或修 VEN。

## 評分標準

| 分數 | 意義 |
| ---: | --- |
| 5 | 直接支援風險降低、事件調查、規則制定、enforcement 推進或治理決策。 |
| 4 | 對特定 persona 很有價值，但應 profile-specific 或摘要化。 |
| 3 | 有背景價值，但主報表中需要簡化或只在有異常時顯示。 |
| 2 | 適合 appendix / XLSX / CSV，不適合作為主要章節。 |
| 1 | 實務價值低、重複或容易誤導，除非重新設計否則應移除。 |

建議處置：

- `keep-main`：保留為主章節。
- `keep-profile-specific`：依 Security Risk / Network Inventory profile 決定是否主顯示。
- `redesign`：保留目的，但重寫摘要、圖表或導讀。
- `simplify`：保留但縮短。
- `conditional`：只有資料存在或偵測到異常時顯示。
- `appendix`：移到附錄、XLSX 或 CSV。
- `merge/remove`：合併到其他章節或移除。

## Traffic Report 模組盤點

| Module | 實務價值 | 建議 | 主要受眾 | 章節應表達什麼 |
| --- | ---: | --- | --- | --- |
| `mod01_traffic_overview` | 3 | `simplify` | mixed | 說明資料範圍、流量規模、時間範圍與政策決策概況；不應變成主要決策章節。 |
| `mod02_policy_decisions` | 5 | `keep-profile-specific` | security/network | 說明 allowed / blocked / potentially_blocked 的真實比例。資安看未授權或危險流量；網管看規則覆蓋與 enforcement 影響。 |
| `mod03_uncovered_flows` | 5 | `keep-main` | security/network | 說明哪些流量缺乏 allow policy，進入 enforcement 後可能被 default-deny 影響。PB 必須被視為 gap，不是 staged coverage。 |
| `mod04_ransomware_exposure` | 5 | `keep-profile-specific` | security | 找出 SMB、RDP、SSH 等高風險橫向移動通道，協助資安優先調查或限制。 |
| `mod05_remote_access` | 2 | `merge/remove` | security | 已被 `mod15_lateral_movement` 整併，不建議恢復成獨立主章節，避免重複。 |
| `mod06_user_process` | 3 | `conditional` | security | 當 user/process 欄位存在時，找出異常執行程序、非預期使用者或可疑高活動行為。無資料時不應空顯示。 |
| `mod07_cross_label_matrix` | 4 | `keep-profile-specific` | network/app_owner | 把 observed flows 轉成 label-to-label 依賴矩陣，支援規則制定。資安版只應顯示 risky crossing。 |
| `mod08_unmanaged_hosts` | 5 | `keep-main` | security/network | 找出受管 workload 與 unknown/unmanaged destination 的連線。這同時是風險盲點與規則制定阻礙。 |
| `mod09_traffic_distribution` | 2 | `appendix` | network | Port/protocol 分布本身不是決策；只有出現異常集中、陌生服務或趨勢變化時才適合主顯示。 |
| `mod10_allowed_traffic` | 4 | `keep-profile-specific` | network/security | 網管用於建立 allow rules；資安只看 high-risk allowed paths 或跨區域高風險 allowed traffic。 |
| `mod11_bandwidth` | 3 | `conditional` | security/network | 高流量可用於外洩或容量判讀，但一般 Top Talkers 應進 appendix。 |
| `mod12_executive_summary` | 5 | `redesign` | executive/mixed | 應依 profile 產出不同摘要。風險版講 top risks/actions；盤點版講 rule readiness/dependency gaps。 |
| `mod13_readiness` | 5 | `keep-main` | network/executive | 評估哪些 app/env 可推 enforcement、哪些 label/rule/unknown dependency 還沒準備好。 |
| `mod14_infrastructure` | 5 | `keep-profile-specific` | security/network | 找出 DNS、AD、NTP、DB、proxy、backup、logging 等 shared/crown-jewel service 的暴露與依賴。 |
| `mod15_lateral_movement` | 5 | `keep-profile-specific` | security/network | 資安版用來看橫向移動與 blast radius；盤點版用來理解跨 app/env 依賴與 enforcement 邊界。 |
| `attack_posture.py` | 5 | `keep-supporting` | security/executive | 應作為風險評分與 Top Actions 來源，而不是再產生一個讀者不懂的獨立章節。 |

## Audit Report 模組盤點

| Module | 實務價值 | 建議 | 章節應表達什麼 |
| --- | ---: | --- | --- |
| `audit_mod00_executive` | 4 | `keep-main` | 說明 audit 期間是否有高風險操作、異常控制面活動、需立即關注的事件。 |
| `audit_mod01_health` | 4 | `keep-main` | 說明 PCE/API/audit 資料是否可信，是否有同步、健康或資料完整性問題。 |
| `audit_mod02_users` | 3 | `conditional` | 只在出現高權限、非預期、離峰或異常大量操作時主顯示；一般 top users 應 appendix。 |
| `audit_mod03_policy` | 5 | `keep-main` | 說明 policy/rule set 變更是否合理、是否過寬、是否可能造成風險或斷線。 |
| `audit_mod04_correlation` | 5 | `keep-main` | 把 auth failure、policy change、VEN change、provision 等事件串成可調查故事。 |
| `audit_risk.py` | 5 | `keep-supporting` | 支撐 audit risk scoring 與 attention required，不應讓讀者只看到分數但不知道原因。 |

## Policy Usage Report 模組盤點

| Module | 實務價值 | 建議 | 章節應表達什麼 |
| --- | ---: | --- | --- |
| `pu_mod00_executive` | 4 | `redesign` | 應說明可清理規則、有效 deny、過寬 allow 與查詢信心，而不是只列總數。 |
| `pu_mod01_overview` | 3 | `simplify` | 保留查詢範圍與資料品質，不應成為主要章節。 |
| `pu_mod02_hit_detail` | 4 | `appendix/main-summary` | Top hit rules 可主顯示；完整 hit detail 應進 XLSX/CSV。 |
| `pu_mod03_unused_detail` | 5 | `keep-main` | 直接支援規則清理與 policy hygiene，是高價值章節。 |
| `pu_mod04_deny_effectiveness` | 5 | `keep-main` | 證明 deny/override deny 是否有效阻擋不想要的流量，支援控制有效性。 |

## VEN Status Report 盤點

| Section | 實務價值 | 建議 | 章節應表達什麼 |
| --- | ---: | --- | --- |
| VEN summary | 5 | `keep-main` | 說明整體 agent 健康、enforcement 進度與 segmentation blind spots。 |
| Offline / lost heartbeat | 5 | `keep-main` | 失聯 workload 會造成控制盲點，應優先依 app/env/role 影響排序。 |
| Policy sync status | 5 | `keep-main` | Policy 未同步代表控制狀態可能與 PCE 不一致，應列出需修復對象。 |
| Enforcement mode | 5 | `keep-main` | 追蹤 visibility_only/selective/full 推進狀態，支援微分段專案進度管理。 |
| Online inventory | 2 | `appendix` | 完整線上清單適合 XLSX，不適合主報表。 |

## 建議章節導讀格式

每個主要章節都應在圖表或表格前加入導讀區塊。

```text
本章目的：
說明這章回答的問題，以及它和微分段/風險/規則制定的關係。

要注意的訊號：
列出應優先關注的數值、趨勢、異常組合或資料缺口。

判讀方式：
解釋圖表、Policy Decision、label matrix、風險分數或狀態欄位應如何解讀。

建議行動：
提供讀者下一步，例如調查、確認 App Owner、建立 allow rule、修 label、隔離主機、清理規則或修復 VEN。
```

## 高優先章節導讀範例

### Potentially Blocked / Uncovered Flows

本章目的：找出目前因 workload 尚未進入完整 enforcement 而仍可通過，但缺乏 matching allow rule 的流量。

要注意的訊號：PB 流量集中在核心服務、高風險 port、跨 env、跨 app、unmanaged destination，或在近期變更後突然上升。

判讀方式：`potentially_blocked` 不是「規則已準備好」，而是「目前沒有對應 allow/deny rule；若進入 default-deny enforcement，這類流量可能被阻擋」。

建議行動：與 App Owner 確認是否為合法依賴。合法流量應轉成 label-based allow rule；不合法或未知流量應保留為未來 enforcement 的阻擋候選。

### Application Dependency / Cross-Label Matrix

本章目的：把 observed east-west flows 轉成可制定微分段規則的 app/env/role/service 依賴。

要注意的訊號：Dev 到 Prod、跨 app 直連 DB、unknown destination、unmanaged dependency、過多 any-to-any 類型連線。

判讀方式：矩陣不是要展示所有流量，而是要幫網管和 App Owner 確認「哪些 label group 之間需要 allow rule」。

建議行動：將合法依賴整理成候選 allow rules；補齊缺失 label；將 unknown IP 建成 IP List 或 unmanaged workload；移除不符合架構的依賴。

### Lateral Movement

本章目的：找出可能擴大攻擊面或支援橫向移動的 east-west path。

要注意的訊號：SMB/RDP/SSH/WinRM 等高風險 port、單一來源連大量目的地、跨 zone/cross-env 通訊、連向 crown-jewel infrastructure。

判讀方式：節點和邊的數量代表 blast radius；高風險服務和跨邊界連線應比一般流量優先處理。

建議行動：對可疑來源啟動事件調查；對合法但高風險依賴建立最小權限規則；必要時 quarantine 或先以 deny/boundary 限縮。

### Draft Policy

本章目的：在 provision 前模擬規則變更對現有流量的影響。

要注意的訊號：Draft View 中關鍵業務流量仍為 not allowed / potentially blocked，或新規則 scope 過寬。

判讀方式：Reported View 是目前實際狀態；Draft View 是草稿規則生效後的預期狀態。兩者差異應被視為變更影響分析。

建議行動：Provision 前先確認必要流量已被 allow；縮小過寬規則；把仍會被阻擋的合法流量補成候選規則。

### VEN Status

本章目的：確認 segmentation control plane 是否能實際作用到 workload。

要注意的訊號：offline、lost heartbeat、degraded、policy not synced、host firewall tampering、長期停留 visibility_only。

判讀方式：沒有健康 VEN，就算 PCE 有正確 policy，也可能無法有效執行。VEN 問題應視為 segmentation blind spot。

建議行動：優先修復 crown-jewel 或高風險 app 的 VEN；檢查 PCE 連線、憑證、service 狀態與 policy sync；將健康且規則完整的 workload 推進 enforcement。

