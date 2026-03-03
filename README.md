# Illumio PCE Monitor

![Version](https://img.shields.io/badge/Version-v1.0.0-blue?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.8%2B-yellow?style=flat-square&logo=python&logoColor=white)
![API](https://img.shields.io/badge/Illumio_API-v25.2-green?style=flat-square)

> **[English](README.md)** | **[繁體中文](README_zh.md)**

An advanced **agentless** monitoring and automation tool for **Illumio Core (PCE)** via REST API. Features intelligent traffic analysis, security event detection, workload quarantine, and automated multi-channel alerting — with **zero external dependencies** (Python stdlib only for CLI/daemon modes).

---

## ✨ Key Features

| Feature | Description |
|:---|:---|
| **Triple Execution Modes** | Background daemon (`--monitor`), interactive CLI wizard, or Flask-powered **Web GUI** (`--gui`) |
| **Security Event Monitoring** | Tracks PCE audit events with anchor-based timestamps — guaranteed zero duplicate alerts |
| **High-Performance Traffic Engine** | Aggregates rules into a single bulk API query; processes data via O(1) memory streaming |
| **Workload Quarantine** | Isolate compromised workloads by applying Quarantine labels (Mild/Moderate/Severe) |
| **Multi-Channel Alerts** | Email (SMTP), LINE Notifications, and Webhooks dispatched simultaneously |
| **Multi-Language UI** | Instant English ↔ Traditional Chinese switching in the Web GUI without reload |

---

## 🚀 Quick Start

### 1. Requirements
- **Python 3.8+**
- (Optional for Web GUI): `pip install flask`

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

## 📖 Documentation

| Document | Description |
|:---|:---|
| **[User Manual](docs/User_Manual.md)** | Installation, execution modes, rule creation, alert channels, Web GUI guide |
| **[Project Architecture](docs/Project_Architecture.md)** | Codebase design, module responsibilities, data flow, modification guide |
| **[API Cookbook](docs/API_Cookbook.md)** | Scenario-based API tutorial for SIEM/SOAR integration (Quarantine, Traffic Query, etc.) |

---

## 📁 Project Structure

```text
illumio_monitor/
├── illumio_monitor.py     # Entry point
├── config.json            # Runtime configuration (credentials, rules, alerts)
├── state.json             # Persistent state (last check timestamp, alert history)
├── requirements.txt       # Python dependencies
├── src/
│   ├── main.py            # CLI argument parser, daemon loop, interactive menu
│   ├── api_client.py      # Illumio REST API client (retry, streaming, auth)
│   ├── analyzer.py        # Rule engine: traffic/event matching, metrics calculation
│   ├── reporter.py        # Alert dispatcher (Email, LINE, Webhook)
│   ├── config.py          # Configuration manager with atomic writes
│   ├── gui.py             # Flask Web GUI backend (routes + API endpoints)
│   ├── settings.py        # CLI interactive menus for rule CRUD
│   ├── i18n.py            # Internationalization (EN/ZH translation dictionary)
│   ├── utils.py           # Helpers (logging, color codes, unit formatting)
│   ├── templates/         # Jinja2 HTML templates
│   └── static/            # CSS/JS frontend assets
├── docs/                  # Documentation files
├── tests/                 # Unit tests (pytest)
├── logs/                  # Runtime log files
└── deploy/                # Deployment scripts (NSSM, systemd)
```
