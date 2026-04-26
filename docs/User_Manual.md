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
ExecStart=/usr/bin/python3 illumio_ops.py --monitor --interval 5
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
ExecStart=/opt/illumio_ops/venv/bin/python illumio_ops.py --monitor --interval 5
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
| Hit Detail | Rules with matching traffic; top flows per rule |
| Unused Detail | Rules with zero traffic hits; candidates for cleanup |

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
