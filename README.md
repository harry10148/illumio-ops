# Illumio PCE Ops

![Version](https://img.shields.io/badge/Version-v3.1.0-blue?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.8%2B-yellow?style=flat-square&logo=python&logoColor=white)
![API](https://img.shields.io/badge/Illumio_API-v25.2-green?style=flat-square)

> **[English](README.md)** | **[繁體中文](README_zh.md)**

An advanced **agentless** monitoring and automation tool for **Illumio Core (PCE)** via REST API. Features real-time security event detection, intelligent traffic analysis, advanced report generation with automated security findings, scheduled report delivery, and multi-channel alerting — with **zero external dependencies** for CLI/daemon modes (Python stdlib only).

---

## ✨ Key Features

| Feature | Description |
|:---|:---|
| **Execution Modes** | Background daemon (`--monitor`), interactive CLI, standalone Web GUI (`--gui`), or **Persistent Monitor + UI** (`--monitor-gui`) |
| **Security Enforced** | **Mandatory login authentication** for all Web GUI modes; supports **IP Allowlisting** (CIDR/Subnet) for restricted access. |
| **Security Event Monitoring** | Tracks PCE audit events with anchor-based timestamps — guaranteed zero duplicate alerts. |
| **High-Performance Traffic Engine** | Aggregates rules into a single bulk API query; O(1) memory streaming for large datasets. |
| **Advanced Report Engine** | 15-module traffic reports with **Bulk-Delete** management; 4-module audit reports, and VEN Status inventory reports — HTML + CSV. |
| **Security Findings** | 19 Automated rules: B-series (Ransomware, Coverage) + L-series (Lateral Movement, Exfiltration). |
| **Report Schedules** | Cron-style recurring reports (daily/weekly/monthly) with automatic email delivery. |
| **Rule Scheduler** | Auto enable/disable PCE rules; **three-layer Draft protection** prevents accidental provisioning. |
| **Workload Quarantine** | Isolate compromised workloads with Quarantine labels; supports IP/CIDR/subnet search. |
| **Multi-Channel Alerts** | Email (SMTP), LINE Notifications, and Webhooks dispatched simultaneously. |

---

## 🚀 Quick Start

### 1. Requirements

- **Python 3.8+**
- **Core (no install needed):** CLI and daemon modes run with zero external dependencies.
- **Optional — Web GUI:** `flask`
- **Optional — Reports:** `pandas`, `pyyaml`

### 2. Installation & Launch

```bash
git clone <repo-url>
cd illumio_ops
cp config/config.json.example config/config.json    # Edit with your PCE credentials

# Interactive CLI:
python illumio_ops.py

# Visual Web GUI (Requires login: illumio / illumio):
python illumio_ops.py --gui

# Persistent Mode (Daemon + Web GUI):
python illumio_ops.py --monitor-gui --interval 5 --port 5001

# Background Daemon Only:
python illumio_ops.py --monitor --interval 5
```

### 3. Default Credentials

The Web GUI is secured by default.
- **Username**: `illumio`
- **Password**: `illumio`

> [!WARNING]
> Please change your password and configure **IP Allowlisting** in the **Settings** menu immediately after your first login.

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
| 4 · Ransomware Exposure | **Investigation targets** (allowed traffic on critical/high-risk ports) |
| ... | See [User Manual](docs/User_Manual.md) for full list |

---

## 📚 Documentation

| Document | Description |
|:---|:---|
| **[User Manual](docs/User_Manual.md)** | Installation, execution modes, security settings, report schedules |
| **[Security Rules Reference](docs/Security_Rules_Reference.md)** | Documentation for the 19 security finding rules (B+L series) |
| **[Project Architecture](docs/Project_Architecture.md)** | Module design, threading model, and security implementation |
| **[API Cookbook](docs/API_Cookbook.md)** | Scenario-based API tutorial for SIEM/SOAR integration |

---

## 📁 Project Structure

```text
illumio_ops/
├── illumio_ops.py          # Entry point
├── src/
│   ├── main.py                 # CLI argparse, daemon/GUI orchestration
│   ├── gui.py                  # Flask Web GUI with Auth & IP Filtering
│   ├── config.py               # ConfigManager (thread-safe, atomic writes)
│   ├── templates/login.html    # Secure Login (Light Theme)
│   └── ...
├── docs/                       # Comprehensive documentation
├── tests/                      # Unit tests (including test_gui_security.py)
└── ...
```
