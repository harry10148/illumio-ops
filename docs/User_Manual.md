# Illumio PCE Monitor — Comprehensive User Manual

> **[English](User_Manual.md)** | **[繁體中文](User_Manual_zh.md)**

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
cd illumio_monitor
cp config/config.json.example config/config.json

# Install optional dependencies from AppStream (no EPEL required)
sudo dnf install python3-flask python3-pandas python3-pyyaml
```

#### Ubuntu / Debian

Modern Ubuntu (22.04+) and Debian (12+) enforce **PEP 668** — direct `pip install` is blocked to protect the system Python. Use a virtual environment:

```bash
# Install venv support if not already present
sudo apt install python3-venv

git clone <repo-url>
cd illumio_monitor
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
cd illumio_monitor
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
python illumio_monitor.py
```

Launches a text-based menu for managing rules, settings, and running manual checks.

```text
=== Illumio PCE Monitor ===
API: https://pce.lab.local:8443 | Rules: 5
----------------------------------------
 1. Add Event Rule
 2. Add Traffic Rule
 3. Add Bandwidth/Volume Rule
 4. Manage Rules
 5. Settings
 6. Load Best Practices
 7. Test Alert
 8. Run Monitor Once
 9. Rule Simulation & Debug Mode
10. Launch Web GUI
11. View Application Logs
12. Generate Traffic Flow Report
13. Generate Audit Log Report
14. Generate VEN Status Report
15. Report Schedules
 0. Exit
```

### 2.2 Web GUI

```bash
python illumio_monitor.py --gui
python illumio_monitor.py --gui --port 8080    # Custom port
```

Opens a browser-based dashboard at `http://127.0.0.1:5001` with tabs for:

| Tab | Features |
|:---|:---|
| **Dashboard** | API connectivity, rule summary, PCE health check; Traffic Analyzer with Top-10 widgets (by bandwidth / volume / flow count); saved dashboard queries |
| **Rules** | Full CRUD for Event/Traffic/Bandwidth/Volume rules, bulk delete, inline edit |
| **Reports** | Generate Traffic, Audit, and VEN Status reports on demand; download HTML or CSV raw data ZIP; delete old reports |
| **Report Schedules** | Create/edit/toggle recurring schedules (daily/weekly/monthly) with email delivery; trigger on demand; view run history |
| **Workload Search** | Search by hostname/IP/label; apply Quarantine labels (single or bulk) |
| **Settings** | API credentials, alert channels, timezone, language/theme switching |
| **Actions** | Run Monitor Once, Debug Mode, Test Alert, Load Best Practices |

### 2.3 Background Daemon

```bash
python illumio_monitor.py --monitor                 # Default: every 10 minutes
python illumio_monitor.py --monitor --interval 5     # Every 5 minutes
```

Runs unattended in the background. Handles `SIGINT`/`SIGTERM` gracefully for clean shutdowns.

### 2.4 Command-Line Reference

```bash
python illumio_monitor.py [OPTIONS]
```

| Flag | Default | Description |
|:---|:---|:---|
| `--monitor` | — | Run in headless daemon mode |
| `-i` / `--interval N` | `10` | Monitoring interval in minutes |
| `--gui` | — | Launch the Web GUI |
| `-p` / `--port N` | `5001` | Web GUI port |
| `--report` | — | Generate a Traffic Flow Report from the command line |
| `--source api\|csv` | `api` | Report data source |
| `--file PATH` | — | CSV file path (used with `--source csv`) |
| `--format html\|csv\|all` | `html` | Report output format |
| `--email` | — | Send report by email after generation |
| `--output-dir PATH` | `reports/` | Output directory for report files |

**Examples:**

```bash
# Generate HTML report for the last 7 days and email it
python illumio_monitor.py --report --format html --email

# Generate report from CSV export and save both HTML + raw CSV
python illumio_monitor.py --report --source csv --file traffic_export.csv --format all

# Web GUI on a custom port
python illumio_monitor.py --gui --port 8080
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

### 3.2 Traffic Rules

Detect connection anomalies by counting matching traffic flows.

| Parameter | Description |
|:---|:---|
| **Policy Decision** | `Blocked (2)`, `Potentially Blocked (1)`, `Allowed (0)`, or `All (3)` |
| **Port / Protocol** | Filter by destination port (e.g., `443`) or IP protocol number (e.g., `6` for TCP) |
| **Source/Dest Label** | Exact label match in `key=value` format (e.g., `role=Web`) |
| **Source/Dest IP** | IP address or IP List name |
| **Excludes** | Negative filters for Port, Label, or IP |

### 3.3 Bandwidth & Volume Rules

Detect data exfiltration patterns.

| Type | Metric | Unit | Calculation |
|:---|:---|:---|:---|
| **Bandwidth** | Peak transmission rate | Mbps | Max of all matching flows |
| **Volume** | Cumulative data transfer | MB | Sum of all matching flows |

> **Hybrid Calculation**: The system prioritizes "Delta interval" metrics. For long-lived connections without measurable deltas, it falls back to "Lifetime total" to prevent exfiltration from slipping unnoticed.

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

**Single vs. bulk apply**: Select a single workload and click **Apply Quarantine** for individual isolation. Check multiple workloads and click **Bulk Quarantine** to isolate them in parallel (concurrent API calls).

> **Important**: Quarantine labels alone do not block traffic. You must create corresponding **Enforcement Boundaries** or **Deny Rules** in the PCE that reference the `Quarantine` label key to actually restrict traffic.

---

## 6. Advanced Deployment

### 6.1 Windows Service (NSSM)

```powershell
nssm install IllumioMonitor "C:\Python312\python.exe" "C:\illumio_monitor\illumio_monitor.py" --monitor --interval 5
nssm set IllumioMonitor AppDirectory "C:\illumio_monitor"
nssm start IllumioMonitor
```

### 6.2 Linux systemd

#### RHEL / CentOS (system Python)

```ini
# /etc/systemd/system/illumio-monitor.service
[Unit]
Description=Illumio PCE Monitor
After=network.target

[Service]
Type=simple
User=illumio
WorkingDirectory=/opt/illumio_monitor
ExecStart=/usr/bin/python3 illumio_monitor.py --monitor --interval 5
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

#### Ubuntu / Debian (venv)

Create the venv first, then point `ExecStart` at the venv interpreter:

```bash
cd /opt/illumio_monitor
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

```ini
# /etc/systemd/system/illumio-monitor.service
[Unit]
Description=Illumio PCE Monitor
After=network.target

[Service]
Type=simple
User=illumio
WorkingDirectory=/opt/illumio_monitor
ExecStart=/opt/illumio_monitor/venv/bin/python illumio_monitor.py --monitor --interval 5
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now illumio-monitor
```

---

## 7. Traffic Reports & Security Findings

### 7.1 Generating Reports

Reports can be triggered from three places:

| Location | How |
|:---|:---|
| Web GUI → Reports tab | Click **Traffic Report**, **Audit Summary**, or **VEN Status** |
| CLI → menu item **[13] Generate Report** | Select report type and date range |
| Daemon mode | Configure a schedule via **[15] Report Schedules** — reports run automatically and can be emailed |

Reports are saved to the `reports/` directory as `.html` (formatted report) and/or `_raw.zip` (CSV raw data) depending on your format setting.

**Dependencies required:**
```bash
pip install pandas pyyaml
```

### 7.2 Report Sections (Traffic Report)

A traffic report contains **15 analytical modules** plus the Security Findings section:

| Section | Description |
|:---|:---|
| Executive Summary | KPI cards: total flows, policy coverage %, top findings |
| 1 · Traffic Overview | Total flows, allowed/blocked/PB breakdown, top ports |
| 2 · Policy Decisions | Per-decision breakdown with inbound/outbound split and per-port coverage % |
| 3 · Uncovered Flows | Flows without an allow rule; port gap ranking; uncovered services (app+port) |
| 4 · Ransomware Exposure | **Investigation targets** (destination hosts with ALLOWED traffic on critical/high ports) prominently highlighted; per-port detail; host exposure ranking |
| 5 · Remote Access | SSH/RDP/VNC/TeamViewer traffic analysis |
| 6 · User & Process | User accounts and processes appearing in flow records |
| 7 · Cross-Label Matrix | Traffic matrix between environment/app/role label combinations |
| 8 · Unmanaged Hosts | Traffic from/to non-PCE-managed hosts; per-app and per-port detail |
| 9 · Traffic Distribution | Port and protocol distribution |
| 10 · Allowed Traffic | Top allowed flows; audit flags |
| 11 · Bandwidth & Volume | Top flows by bytes + Bandwidth (Mbps) column; Max/Avg/P95 stat cards; anomaly detection (P95 of multi-connection flows) |
| 13 · Enforcement Readiness | Score 0–100 with factor breakdown and remediation recommendations |
| 14 · Infrastructure Scoring | Node centrality scoring to identify critical services (in-degree, out-degree, betweenness) |
| 15 · Lateral Movement Risk | Lateral movement pattern analysis and high-risk paths |
| **Security Findings** | **Automated rule evaluation — see Section 7.3** |

### 7.3 Security Findings Rules

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

### 7.3 Audit Report Sections

The Audit Report contains **4 modules**:

| Module | Description |
|:---|:---|
| Executive Summary | Event counts by severity and category; top event types |
| 1 · System Health Events | `agent.tampering`, offline agents, heartbeat failures |
| 2 · User Activity | Authentication events, login failures, account changes |
| 3 · Policy Changes | Ruleset and rule create/update/delete, policy provisioning |

### 7.3b VEN Status Report

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

### 7.4 Tuning Security Rules

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

### 7.5 Report Schedules

Configure automated recurring reports via CLI menu **[15]** or Web GUI **Report Schedules** tab:

| Field | Description |
|:---|:---|
| Report Type | Traffic Flow / Audit / VEN Status |
| Frequency | Daily / Weekly (day of week) / Monthly (day of month) |
| Time | Hour and minute — input in your **configured timezone** (automatically stored as UTC) |
| Lookback Days | How many days of traffic data to include |
| Output Format | HTML / CSV Raw ZIP / Both |
| Send by Email | Attach report to email using SMTP settings |
| Custom Recipients | Override default recipients for this schedule |

> **Timezone note**: The time fields in CLI and Web GUI always display in the timezone configured under Settings → Timezone. The underlying storage is UTC, so the schedule remains correct if you change the timezone setting.

The daemon loop checks schedules every 60 seconds and runs any schedule whose configured time has been reached.

After each successful run, old report files (`.html` and `.zip`) are automatically cleaned up according to the **retention policy** — see Section 8.3.

---

## 8. Settings Reference

### 8.1 Timezone

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

### 8.2 Dashboard Queries

The Dashboard tab supports saving custom traffic queries for repeated use. Each saved query stores filter parameters (policy decision, port, label, IP range) and can be run on demand from the Dashboard to populate the Top-10 widgets.

Queries are stored in `config.json` → `settings.dashboard_queries` and are managed entirely through the Web GUI.

### 8.3 Report Output

Controls where reports are saved and how long they are kept.

| Setting | Default | Description |
|:---|:---|:---|
| `report.output_dir` | `reports/` | Directory for generated reports (relative to project root, or absolute path) |
| `report.retention_days` | `30` | Auto-delete `.html`/`.zip` reports older than this many days after each scheduled run. Set to `0` to disable. |

**Configure from Web GUI**: Settings → **Report Output** fieldset
**Configure from CLI**: Settings menu → **[5] Report Output**
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

## 9. Troubleshooting

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
| Schedule email fails: `'Finding' object has no attribute 'get'` | Outdated code | Pull latest — this was fixed in commit `98c0b47` |
