# Illumio PCE Ops

<!-- BEGIN:doc-map -->
| Document | EN | 中文 |
|---|---|---|
| README | [README.md](README.md) | [README_zh.md](README_zh.md) |
| Installation | [Installation.md](docs/Installation.md) | [Installation_zh.md](docs/Installation_zh.md) |
| User Manual | [User_Manual.md](docs/User_Manual.md) | [User_Manual_zh.md](docs/User_Manual_zh.md) |
| Report Modules | [Report_Modules.md](docs/Report_Modules.md) | [Report_Modules_zh.md](docs/Report_Modules_zh.md) |
| Security Rules | [Security_Rules_Reference.md](docs/Security_Rules_Reference.md) | [Security_Rules_Reference_zh.md](docs/Security_Rules_Reference_zh.md) |
| SIEM Integration | [SIEM_Integration.md](docs/SIEM_Integration.md) | [SIEM_Integration_zh.md](docs/SIEM_Integration_zh.md) |
| Architecture | [Architecture.md](docs/Architecture.md) | [Architecture_zh.md](docs/Architecture_zh.md) |
| PCE Cache | [PCE_Cache.md](docs/PCE_Cache.md) | [PCE_Cache_zh.md](docs/PCE_Cache_zh.md) |
| API Cookbook | [API_Cookbook.md](docs/API_Cookbook.md) | [API_Cookbook_zh.md](docs/API_Cookbook_zh.md) |
<!-- END:doc-map -->

![Version](https://img.shields.io/badge/Version-v3.20.0--report--intelligence-blue?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.8%2B-yellow?style=flat-square&logo=python&logoColor=white)
![API](https://img.shields.io/badge/Illumio_API-v25.2-green?style=flat-square)

> **[English](README.md)** | **[繁體中文](README_zh.md)**

An advanced **agentless** monitoring and automation tool for **Illumio Core (PCE)** via REST API. Features real-time security event detection, intelligent traffic analysis, advanced report generation with automated security findings, scheduled report delivery, and multi-channel alerting.

---

## Highlights

| Feature | Description |
|:---|:---|
| **Execution Modes** | Background daemon (`--monitor`), interactive CLI, standalone Web GUI (`--gui`), or **Persistent Monitor + UI** (`--monitor-gui`) |
| **Enterprise Security** | **Web GUI session security**: **login rate limiting** (5/min), **CSRF synchronizer token** pattern, **IP Allowlisting** (CIDR/Subnet). Password is plaintext in `config.json` (offline-isolated deployment model). |
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

- **Python 3.8+** (tested up to 3.12)
- **Install:** `pip install -r requirements.txt` — ~25 pinned packages spanning Flask + security middleware (`flask-wtf`, `flask-limiter`, `flask-talisman`, `flask-login`), reports + charts (`pandas`, `pyyaml`, `openpyxl`, `reportlab`, `matplotlib`, `plotly`, `pygments`), HTTP client (`requests`, `orjson`, `cachetools`), config validation (`pydantic`), scheduler + cache (`APScheduler`, `SQLAlchemy`), structured logging (`loguru`), CLI UX (`rich`, `questionary`, `click`, `humanize`).
- **Offline-isolated targets:** use `scripts/build_offline_bundle.sh` to produce a self-contained tarball with all wheels pre-built; see [User Manual §1](docs/User_Manual.md) for the full bundle workflow.
- **PDF export:** `reportlab` is included by default (pure Python; no WeasyPrint / Pango / Cairo / GTK / GDK-PixBuf required). PDF output is a static English summary; HTML and XLSX are the recommended formats for full localized content.

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
> If you lose your password, edit `web_gui.password` in `config/config.json` to a new value (or remove it entirely to fall back to the default `illumio`). The value is plaintext.

### 4. Security Features

| Feature | Details |
|:---|:---|
| **Web GUI password** | Plaintext in `config.json` `web_gui.password`. Designed for offline-isolated deployments; other secrets (PCE API key/secret, LINE token, SMTP password, webhook URL) are also plaintext for consistency. Change `illumio` default on first login. |
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

- [Installation](docs/Installation.md) ([中文](docs/Installation_zh.md)) — RHEL/Ubuntu/Windows/dev install, offline bundle build/install/upgrade/uninstall, systemd
- [User Manual](docs/User_Manual.md) ([中文](docs/User_Manual_zh.md)) — CLI subcommands, GUI walkthrough, daemon mode, alerts, quarantine, multi-PCE, settings, troubleshooting
- [Report Modules](docs/Report_Modules.md) ([中文](docs/Report_Modules_zh.md)) — All 22+ analysis modules (mod01-mod15, R3 intelligence, Policy Usage), output formats, scheduling, draft_pd behaviour
- [Security Rules Reference](docs/Security_Rules_Reference.md) ([中文](docs/Security_Rules_Reference_zh.md)) — B-Series, L-Series, R-Series rule catalogues; severity model; compute_draft auto-enable
- [SIEM Integration](docs/SIEM_Integration.md) ([中文](docs/SIEM_Integration_zh.md)) — CEF/JSON formats, UDP/TCP/TLS/HEC transports, forwarder config, field mapping
- [Architecture](docs/Architecture.md) ([中文](docs/Architecture_zh.md)) — Illumio platform background; system overview; module map; data flow
- [PCE Cache](docs/PCE_Cache.md) ([中文](docs/PCE_Cache_zh.md)) — SQLite WAL cache layer; refresh policy; operator commands
- [API Cookbook](docs/API_Cookbook.md) ([中文](docs/API_Cookbook_zh.md)) — PCE REST API integration patterns; auth/pagination/async-job; common endpoints

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
│   ├── config.py               # ConfigManager (plaintext config, atomic writes)
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
