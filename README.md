# Illumio PCE Ops

![Version](https://img.shields.io/badge/Version-v3.2.0-blue?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.8%2B-yellow?style=flat-square&logo=python&logoColor=white)
![API](https://img.shields.io/badge/Illumio_API-v25.2-green?style=flat-square)

> **[English](README.md)** | **[繁體中文](README_zh.md)**

An advanced **agentless** monitoring and automation tool for **Illumio Core (PCE)** via REST API. Features real-time security event detection, intelligent traffic analysis, advanced report generation with automated security findings, scheduled report delivery, and multi-channel alerting — with **zero external dependencies** for CLI/daemon modes (Python stdlib only).

---

## Highlights

| Feature | Description |
|:---|:---|
| **Execution Modes** | Background daemon (`--monitor`), interactive CLI, standalone Web GUI (`--gui`), or **Persistent Monitor + UI** (`--monitor-gui`) |
| **Enterprise Security** | **PBKDF2 password hashing** (260k iterations), **login rate limiting** (5/min), **CSRF synchronizer token** pattern, **IP Allowlisting** (CIDR/Subnet) |
| **Security Event Monitoring** | Tracks PCE audit events with anchor-based timestamps — guaranteed zero duplicate alerts |
| **High-Performance Traffic Engine** | Aggregates rules into a single bulk API query; O(1) memory streaming for large datasets |
| **Advanced Report Engine** | 15-module traffic reports with **Bulk-Delete** management; 4-module audit reports, policy usage reports, and VEN Status inventory reports — HTML + CSV |
| **Security Findings** | 19 Automated rules: B-series (Ransomware, Coverage) + L-series (Lateral Movement, Exfiltration) |
| **Report Schedules** | Cron-style recurring reports (daily/weekly/monthly) with automatic email delivery |
| **Rule Scheduler** | Auto enable/disable PCE rules; **three-layer Draft protection** prevents accidental provisioning |
| **Workload Quarantine** | Isolate compromised workloads with Quarantine labels; supports IP/CIDR/subnet search |
| **Multi-Channel Alerts** | Email (SMTP), LINE Notifications, and Webhooks dispatched simultaneously |
| **Internationalization** | Full English + Traditional Chinese (繁體中文) across CLI, Web GUI, reports, and alerts |

---

## SIEM Status (Preview)

> [!WARNING]
> Built-in SIEM forwarder is currently in **Preview** status.
> Existing deployments already using SIEM can keep running for compatibility, but new production rollout is not recommended until runtime pipeline gaps are closed.

## Quick Start

### 1. Requirements

- **Python 3.8+**
- **Core (no install needed):** CLI and daemon modes run with zero external dependencies.
- **Optional — Web GUI:** `flask>=3.0`
- **Optional — Reports:** `pandas`, `pyyaml`
- **Optional — PDF export:** `reportlab` (pure Python). PDF export does not require WeasyPrint, Pango, Cairo, GTK, or GDK-PixBuf. PDF output is a static English summary; HTML and XLSX are the recommended formats for full localized content.

### 2. Installation & Launch

```bash
git clone <repo-url>
cd illumio_ops
cp config/config.json.example config/config.json    # Edit with your PCE credentials

# Interactive CLI:
python illumio_ops.py

# Visual Web GUI:
python illumio_ops.py --gui

# Persistent Mode (Daemon + Web GUI):
python illumio_ops.py --monitor-gui --interval 5 --port 5001

# Background Daemon Only:
python illumio_ops.py --monitor --interval 5

# New subcommand style (Phase 1+):
python illumio_ops.py monitor -i 5
python illumio_ops.py status
python illumio_ops.py version
```

### Shell Tab Completion (bash)

```bash
# Source once (dev)
source scripts/illumio-ops-completion.bash

# Install globally (RPM will do this automatically):
sudo cp scripts/illumio-ops-completion.bash /etc/bash_completion.d/illumio-ops
```

### 3. First Login

Default credentials: **username `illumio`** / **password `illumio`**.

1. Log in with the default credentials.
2. **Change your password immediately** in the **Settings** page.
3. Configure **IP Allowlisting** to restrict access to trusted networks.

> [!WARNING]
> If you lose your password, delete the `password_hash` and `password_salt` keys from `config/config.json` to reset to defaults.

### 4. Security Features

| Feature | Details |
|:---|:---|
| **Password Hashing** | PBKDF2-HMAC-SHA256 with 260,000 iterations (stdlib, no external deps) |
| **Rate Limiting** | 5 login attempts per IP per 60 seconds; returns HTTP 429 on excess |
| **CSRF Protection** | Synchronizer token pattern via `<meta>` tag injection (no XSS-readable cookie) |
| **IP Allowlisting** | Supports individual IPs, CIDR ranges, and subnet masks |
| **SMTP Credentials** | Set `ILLUMIO_SMTP_PASSWORD` env var to avoid storing passwords in config |

### 5. Logging (loguru)

Logs are written to `logs/illumio_ops.log` with 10 MB rotation and 10-file retention.

**SIEM / JSON sink** — enable structured JSON logging by adding to `config/config.json`:
```json
{
  "logging": {
    "json_sink": true,
    "level": "INFO"
  }
}
```
This writes one JSON object per line to `logs/illumio_ops.json.log`, compatible with tools like Splunk, Elasticsearch, and Datadog.

---

## Report Engine

Reports can be generated from the Web GUI, CLI menu, or run automatically on a schedule.

### Traffic Report — 15 Analysis Modules

| Module | Description |
|:---|:---|
| Executive Summary | KPI cards: total flows, coverage %, top security findings |
| 1 · Traffic Overview | Total flows, policy decision breakdown, top ports |
| 2 · Policy Decisions | Per-decision with inbound/outbound split and per-port coverage % |
| 3 · Uncovered Flows | Flows without allow rules; port gap ranking; uncovered services |
| 4 · Ransomware Exposure | **Investigation targets** (allowed traffic on critical/high-risk ports) |
| ... | See [User Manual](docs/User_Manual.md) for full list |

---

## Documentation

| Document | Description |
|:---|:---|
| **[User Manual](docs/User_Manual.md)** | Installation, execution modes, security settings, report schedules |
| **[Security Rules Reference](docs/Security_Rules_Reference.md)** | Documentation for the 19 security finding rules (B+L series) |
| **[Project Architecture](docs/Project_Architecture.md)** | Module design, threading model, and security implementation |
| **[API Cookbook](docs/API_Cookbook.md)** | Scenario-based API tutorial for SIEM/SOAR integration |

---

## Project Structure

```text
illumio_ops/
├── illumio_ops.py          # Entry point
├── src/
│   ├── main.py                 # CLI argparse, daemon/GUI orchestration
│   ├── api_client.py           # PCE REST API (async jobs, native filters, O(1) streaming)
│   ├── analyzer.py             # Rule engine (flow matching, event analysis, state mgmt)
│   ├── gui.py                  # Flask Web GUI (~40 JSON API endpoints, auth, CSRF)
│   ├── config.py               # ConfigManager (PBKDF2 hashing, atomic writes)
│   ├── reporter.py             # Multi-channel alert dispatch (SMTP, LINE, Webhook)
│   ├── i18n.py                 # i18n engine (EN/ZH_TW, ~1400+ string keys)
│   ├── events/                 # Event pipeline (catalog, normalize, dedup, throttle)
│   ├── report/                 # Report engine (15 traffic modules + audit + policy usage)
│   └── alerts/                 # Alert plugins (mail, LINE, webhook)
├── config/                     # config.json, report_config.yaml
├── docs/                       # EN + ZH_TW documentation
├── tests/                      # 19 test files (116 tests)
├── deploy/                     # systemd (Ubuntu/RHEL) + NSSM (Windows) service configs
└── scripts/                    # Utility scripts
```
