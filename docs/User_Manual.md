# Illumio PCE Monitor — Comprehensive User Manual

> **[English](User_Manual.md)** | **[繁體中文](User_Manual_zh.md)**

---

## 1. Installation & Prerequisites

### 1.1 System Requirements
- **Python 3.8+** (tested up to 3.12)
- **Network Access** to Illumio PCE (HTTPS, default port `8443`)
- **(Optional)** `pip install flask` — required only for Web GUI mode

### 1.2 Installation

```bash
git clone <repo-url>
cd illumio_monitor
pip install -r requirements.txt    # Installs Flask (optional dependencies)
```

### 1.3 Configuration (`config.json`)

Copy the example config and fill in your PCE API credentials:

```bash
cp config.json.example config.json
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
 9. Debug Mode
10. Launch Web GUI
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
| **Dashboard** | API connectivity, rule summary, PCE health check, Traffic Analyzer with Top-10 widgets |
| **Rules** | Full CRUD for Event/Traffic/Bandwidth/Volume rules, bulk delete, inline edit |
| **Workload Search** | Search by hostname/IP/label, apply Quarantine labels |
| **Settings** | API credentials, alert channels, language/theme switching |
| **Actions** | Run Monitor Once, Debug Mode, Test Alert, Load Best Practices |

### 2.3 Background Daemon

```bash
python illumio_monitor.py --monitor                 # Default: every 10 minutes
python illumio_monitor.py --monitor --interval 5     # Every 5 minutes
```

Runs unattended in the background. Handles `SIGINT`/`SIGTERM` gracefully for clean shutdowns.

---

## 3. Rule Types & Configuration

### 3.1 Event Rules

Monitor PCE audit events (e.g., `agent.tampering`, `user.login_failed`).

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

1. **Search** for the target workload (by hostname, IP, or label) via Web GUI → **Workload Search**
2. **Select** a Quarantine level: `Mild`, `Moderate`, or `Severe`
3. The system **automatically creates** the Quarantine label type in the PCE if it doesn't exist
4. The system **appends** the Quarantine label to the workload's existing labels (preserving all others)

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

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now illumio-monitor
```

---

## 7. Troubleshooting

| Symptom | Cause | Solution |
|:---|:---|:---|
| `Connection refused` | PCE unreachable | Verify `api.url` and network connectivity |
| `401 Unauthorized` | Invalid API credentials | Regenerate API Key in PCE Console |
| `410 Gone` | Async query expired | The traffic query result was cleaned up; re-run the query |
| `429 Too Many Requests` | API rate limiting | The system auto-retries with backoff; reduce query frequency if persistent |
| Web GUI won't start | Flask not installed | Run `pip install flask` |
| No alerts received | Channel not activated | Ensure `alerts.active` array includes your channel(s) |
