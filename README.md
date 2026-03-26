# Illumio PCE Monitor

![Version](https://img.shields.io/badge/Version-v1.0.0-blue?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.8%2B-yellow?style=flat-square&logo=python&logoColor=white)
![API](https://img.shields.io/badge/Illumio_API-v25.2-green?style=flat-square)

> **[English](README.md)** | **[繁體中文](README_zh.md)**

An advanced **agentless** monitoring and automation tool for **Illumio Core (PCE)** via REST API. Features real-time security event detection, intelligent traffic analysis, advanced report generation with automated security findings, scheduled report delivery, and multi-channel alerting — with **zero external dependencies** for CLI/daemon modes (Python stdlib only).

---

## ✨ Key Features

| Feature | Description |
|:---|:---|
| **Triple Execution Modes** | Background daemon (`--monitor`), interactive CLI wizard, or Flask-powered **Web GUI** (`--gui`) |
| **Security Event Monitoring** | Tracks PCE audit events with anchor-based timestamps — guaranteed zero duplicate alerts |
| **High-Performance Traffic Engine** | Aggregates rules into a single bulk API query; O(1) memory streaming for large datasets |
| **Advanced Report Engine** | 15-module traffic reports, 4-module audit reports, and VEN Status inventory reports — HTML + Excel |
| **19 Automated Security Findings** | B-series (ransomware, coverage, anomalies) + L-series (lateral movement, exfiltration, blast-radius) |
| **Report Schedules** | Cron-style recurring reports (daily/weekly/monthly) with automatic email delivery |
| **Workload Quarantine** | Isolate compromised workloads by applying Quarantine labels (Mild/Moderate/Severe) |
| **Multi-Channel Alerts** | Email (SMTP), LINE Notifications, and Webhooks dispatched simultaneously |
| **Multi-Language UI** | Instant English ↔ Traditional Chinese switching in Web GUI and HTML reports without reload |

---

## 🚀 Quick Start

### 1. Requirements

- **Python 3.8+**
- **Core (no install needed):** CLI and daemon modes run with zero external dependencies
- **Optional — Web GUI:** `flask`
- **Optional — Reports:** `pandas`, `openpyxl`, `pyyaml`

### 2. Installation & Launch

```bash
git clone <repo-url>
cd illumio_monitor
cp config.json.example config.json    # Edit with your PCE credentials

# Interactive CLI:
python illumio_monitor.py

# Visual Web GUI (opens http://127.0.0.1:5001):
python illumio_monitor.py --gui

# Background Daemon (checks every 5 minutes):
python illumio_monitor.py --monitor --interval 5
```

### 3. Configuration (`config.json`)

```json
{
    "api": {
        "url": "https://pce.example.com:8443",
        "org_id": "1",
        "key": "api_xxxxxxxxxxxxxx",
        "secret": "your-api-secret-here",
        "verify_ssl": true
    }
}
```

> For a full configuration reference, see the [User Manual](docs/User_Manual.md).

---

## 📊 Report Engine

Reports can be generated from the Web GUI, CLI menu, or run automatically on a schedule.

### Traffic Report — 15 Analysis Modules

| Module | Description |
|:---|:---|
| Executive Summary | KPI cards: total flows, coverage %, top security findings |
| 1 · Traffic Overview | Total flows, policy decision breakdown, top ports |
| 2 · Policy Decisions | Per-decision with inbound/outbound split and per-port coverage % |
| 3 · Uncovered Flows | Flows without allow rules; port gap ranking; uncovered services |
| 4 · Ransomware Exposure | **Investigation targets** (allowed traffic on critical/high-risk ports), per-port detail, host exposure ranking |
| 5 · Remote Access | SSH/RDP/VNC/TeamViewer traffic analysis |
| 6 · User & Process | User accounts and processes appearing in flow records |
| 7 · Cross-Label Matrix | Traffic matrix between environment/app/role label combinations |
| 8 · Unmanaged Hosts | Traffic from/to non-PCE-managed hosts; per-app and per-port detail |
| 9 · Traffic Distribution | Port and protocol distribution charts |
| 10 · Allowed Traffic | Top allowed flows; audit flags |
| 11 · Bandwidth & Volume | Top flows by bytes + bandwidth (max/avg/P95); anomaly detection |
| 13 · Enforcement Readiness | Score 0–100 with factor breakdown and remediation recommendations |
| 14 · Infrastructure Scoring | Node centrality scoring to identify critical infrastructure |
| 15 · Lateral Movement Risk | Lateral movement pattern analysis and risk paths |
| **Security Findings** | 19 automated rules — CRITICAL/HIGH/MEDIUM/LOW/INFO severity |

### Other Reports

| Report | Description |
|:---|:---|
| **Audit Report** | System health events, user authentication activity, policy changes |
| **VEN Status Inventory** | Online/offline VENs with last-heartbeat bucketing (24h / 24–48h / long-term) |

---

## 🔍 Security Findings (19 Rules)

Automated detection runs against every traffic dataset and groups findings by severity.

| Series | Focus | Rules |
|:---|:---|:---|
| **B-series** | Ransomware exposure, policy coverage gaps, behavioural anomalies | B001–B009 |
| **L-series** | Lateral movement, credential theft, blast-radius paths, data exfiltration | L001–L010 |

Key detections include: ransomware ports allowed across environments (CRITICAL), single-source fan-out on lateral movement ports, blast-radius path analysis via graph traversal, and data exfiltration patterns (managed → unmanaged with high byte volume). See [Security Rules Reference](docs/Security_Rules_Reference.md) for full documentation.

---

## 🏢 Enterprise / Offline Installation

### Method A — Red Hat / CentOS (dnf / yum)

```bash
sudo dnf install python3-flask python3-pyyaml python3-pandas
# openpyxl is not in the official RHEL repo — use Method B
```

### Method B — Pre-download Wheels (pip offline)

```bash
# On a machine with internet access:
pip download flask pandas openpyxl pyyaml -d ./offline_packages/

# On the air-gapped host:
pip install --no-index --find-links=./offline_packages/ flask pandas openpyxl pyyaml
```

### Method C — Internal PyPI Mirror (Nexus / Artifactory)

```bash
pip install pandas openpyxl pyyaml flask \
    --index-url https://nexus.internal/repository/pypi-proxy/simple/
```

| Package | RHEL AppStream | Ubuntu `apt` | Offline wheel |
|---------|:--------------:|:------------:|:-------------:|
| `flask` | ✅ `python3-flask` | ✅ `python3-flask` | ✅ |
| `pyyaml` | ✅ `python3-pyyaml` | ✅ `python3-yaml` | ✅ |
| `pandas` | ✅ `python3-pandas` (RHEL 8+) | ✅ `python3-pandas` | ✅ |
| `openpyxl` | ❌ not in repo | ✅ `python3-openpyxl` | ✅ |

---

## 📚 Documentation

| Document | Description |
|:---|:---|
| **[User Manual](docs/User_Manual.md)** | Installation, execution modes, rule creation, alert channels, reports, schedules |
| **[Security Rules Reference](docs/Security_Rules_Reference.md)** | Full documentation for all 19 security finding rules with trigger conditions and tuning guidance |
| **[API Cookbook](docs/API_Cookbook.md)** | Scenario-based API tutorial for SIEM/SOAR integration |

---

## 📁 Project Structure

```text
illumio_monitor/
├── illumio_monitor.py          # Entry point
├── config.json                 # Runtime configuration (gitignored)
├── state.json                  # Persistent state (gitignored)
├── requirements.txt
│
├── src/
│   ├── main.py                 # CLI argparse, daemon loop, interactive menu
│   ├── api_client.py           # Illumio REST API client (retry, streaming, auth)
│   ├── analyzer.py             # Rule engine: event/traffic/bandwidth matching
│   ├── reporter.py             # Alert dispatcher (Email, LINE, Webhook) + report email
│   ├── config.py               # ConfigManager (atomic writes, rule CRUD)
│   ├── gui.py                  # Flask Web GUI (~25 JSON API endpoints)
│   ├── settings.py             # CLI interactive wizards (rules, schedules)
│   ├── report_scheduler.py     # Cron-style daemon scheduler for recurring reports
│   ├── i18n.py                 # EN / ZH_TW translation dictionary (200+ keys)
│   ├── utils.py                # Logging, ANSI colour, unit formatting, CJK width
│   ├── templates/index.html    # Web GUI SPA (vanilla JS, Illumio brand theme)
│   │
│   └── report/                 # Report engine
│       ├── report_generator.py     # Unified entry: parse → analyse → export
│       ├── audit_generator.py      # Audit report orchestrator
│       ├── ven_status_generator.py # VEN status report orchestrator
│       ├── rules_engine.py         # 19 security finding rules (B+L series)
│       ├── parsers/                # API parser, CSV parser, validators
│       ├── exporters/              # HTML + Excel exporters, report i18n
│       └── analysis/               # 15 traffic modules + 4 audit modules
│
├── config/
│   ├── report_config.yaml      # Ransomware ports, detection thresholds
│   ├── semantic_config.yaml    # Custom semantic rules (optional)
│   └── csv_column_mapping.yaml # CSV column name mapping
│
├── docs/                       # Documentation
├── deploy/                     # systemd service + Windows installer
├── tests/                      # Unit tests (pytest)
└── logs/                       # Rotating application logs
```

---

## 🧪 Testing

```bash
# Unit tests
pytest tests/test_analyzer.py

# Audit report integration test (uses DummyApiClient)
python test_audit.py

# Real API integration test (requires valid config.json credentials)
python test_real_events.py
```
