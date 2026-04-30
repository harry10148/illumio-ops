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
| Glossary | [Glossary.md](docs/Glossary.md) | [Glossary_zh.md](docs/Glossary_zh.md) |
| Troubleshooting | [Troubleshooting.md](docs/Troubleshooting.md) | [Troubleshooting_zh.md](docs/Troubleshooting_zh.md) |
<!-- END:doc-map -->

![Version](https://img.shields.io/badge/Version-v3.20.0--report--intelligence-blue?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.8%2B-yellow?style=flat-square&logo=python&logoColor=white)
![API](https://img.shields.io/badge/Illumio_API-v25.2-green?style=flat-square)

> **[English](README.md)** | **[繁體中文](README_zh.md)**

An advanced **agentless** monitoring and automation tool for **Illumio Core (PCE)** via REST API.

---

## What is this for?

Illumio PCE manages workload microsegmentation policy and captures traffic telemetry, but day-to-day ops needs sit outside its built-in UI: scheduled reports, multi-channel alerting, SIEM forwarding, rule scheduling, and switching between PCE environments. **illumio-ops** fills those gaps as an agentless companion that talks to PCE only via REST API.

You'll likely want this if any of these match your situation:

- You operate one or more PCE deployments and want **scheduled traffic / audit / VEN-status / policy-usage reports** delivered by email.
- You need **continuous monitoring** of PCE audit events and traffic anomalies with alerts via Email, LINE, or Webhook (Slack/Teams).
- You want to **forward PCE events / flows to a SIEM** (Splunk HEC, Splunk syslog, ELK, Sentinel) without standing up a separate forwarder.
- You manage **multiple PCEs** and want a single tool to switch between them.
- You want a **safe rule scheduler** that auto-enables/disables PCE rules with three-layer Draft protection.

If you only need the PCE web console for occasional manual queries, you don't need this tool.

---

## Highlights

| Feature | Description |
|:---|:---|
| **Execution Modes** | Background daemon (`--monitor`), interactive CLI, standalone Web GUI (`--gui`), or **Persistent Monitor + UI** (`--monitor-gui`) |
| **Enterprise Security** | Argon2id passwords with first-login force-change, HTTPS by default (ECDSA P-256 self-signed), CSRF synchronizer tokens, login rate limiting, IP allowlisting (CIDR/Subnet) |
| **Security Event Monitoring** | Tracks PCE audit events with anchor-based timestamps — guaranteed zero duplicate alerts |
| **High-Performance Traffic Engine** | Aggregates rules into a single bulk API query; O(1) memory streaming for large datasets |
| **Advanced Report Engine** | 15-module traffic reports with **Bulk-Delete** management; 4-module audit reports, policy usage reports, and VEN Status inventory reports — HTML + CSV |
| **Security Findings** | 19 automated rules: B-series (Ransomware, Coverage) + L-series (Lateral Movement, Exfiltration) + R-series (Draft Policy alignment) |
| **Report Schedules** | Cron-style recurring reports (daily/weekly/monthly) with automatic email delivery |
| **Rule Scheduler** | Auto enable/disable PCE rules; **three-layer Draft protection** prevents accidental provisioning |
| **Workload Quarantine** | Isolate compromised workloads with Quarantine labels; supports IP/CIDR/subnet search |
| **Multi-Channel Alerts** | Email (SMTP), LINE Notifications, and Webhooks dispatched simultaneously |
| **Internationalization** | Full English + Traditional Chinese (繁體中文) across CLI, Web GUI, reports, and alerts |

> [!WARNING]
> **SIEM Status (Preview)** — the built-in SIEM forwarder is currently in **Preview**. Existing deployments can keep running for compatibility, but new production rollout is not recommended until runtime pipeline gaps are closed.

---

## Quick Start

```bash
git clone <repo-url>
cd illumio-ops
cp config/config.json.example config/config.json    # Edit with your PCE credentials
pip install -r requirements.txt

# Most common: persistent daemon + Web GUI on https://127.0.0.1:5001
python illumio-ops.py --monitor-gui --interval 5 --port 5001
```

For RHEL / Ubuntu / Windows offline-bundle installs, air-gapped deployments, systemd / NSSM service registration, and dependency details, see **[Installation](docs/Installation.md)**.

For all execution modes (`--gui` / `--monitor` / interactive CLI), the full subcommand reference, and the operational walkthrough, see **[User Manual §1](docs/User_Manual.md)**.

### First Login

The default username is `illumio`. On first startup with an empty `web_gui.password`, an initial password is auto-generated and stored at `web_gui._initial_password` in `config.json`; the first login is forced to change it. Full flow: **[User Manual §3](docs/User_Manual.md#3-web-gui-security)**.

### Logging

Plain text rotates at `logs/illumio_ops.log` (10 MB × 10). For SIEM ingest, enable the JSON sink in `config.json` → `logging.json_sink: true` to additionally write `logs/illumio_ops.json.log`. See **[Troubleshooting §7](docs/Troubleshooting.md)** for log diagnostics.

---

## Documentation — by role

**Setting up for the first time**
- [Installation](docs/Installation.md) — RHEL/Ubuntu/Windows install, offline bundle, systemd/NSSM
- [User Manual §1](docs/User_Manual.md) — execution modes, CLI subcommands

**Day-to-day operations**
- [User Manual](docs/User_Manual.md) — alerts, quarantine, multi-PCE, settings reference
- [Report Modules](docs/Report_Modules.md) — what each report section means
- [Troubleshooting](docs/Troubleshooting.md) — common errors and fixes

**Security analysis**
- [Security Rules Reference](docs/Security_Rules_Reference.md) — B/L/R rule catalogues, severity model
- [Report Modules](docs/Report_Modules.md) — module-level findings

**Integrations**
- [SIEM Integration](docs/SIEM_Integration.md) — CEF/JSON/HEC formats, receiver examples
- [API Cookbook](docs/API_Cookbook.md) — PCE REST API patterns; tool's HTTP API

**Storage / advanced**
- [PCE Cache](docs/PCE_Cache.md) — local SQLite cache; backfill; retention

**Background**
- [Architecture](docs/Architecture.md) — Illumio platform primer + this tool's internals
- [Glossary](docs/Glossary.md) — Illumio + tool-specific terms

---

## Project Structure

```text
illumio-ops/
├── illumio-ops.py          # Entry point
├── src/
│   ├── main.py                 # CLI argparse, daemon/GUI orchestration
│   ├── api_client.py           # PCE REST API (async jobs, native filters, O(1) streaming)
│   ├── analyzer.py             # Rule engine (flow matching, event analysis, state mgmt)
│   ├── gui.py                  # Flask Web GUI (~40 JSON API endpoints, auth, CSRF)
│   ├── config.py               # ConfigManager (Argon2id GUI password, atomic writes)
│   ├── reporter.py             # Multi-channel alert dispatch (SMTP, LINE, Webhook)
│   ├── i18n.py                 # i18n engine (EN/ZH_TW, ~1400+ string keys)
│   ├── events/                 # Event pipeline (catalog, normalize, dedup, throttle)
│   ├── report/                 # Report engine (15 traffic modules + audit + policy usage)
│   ├── pce_cache/              # SQLite WAL cache + ingestors
│   ├── siem/                   # SIEM forwarder (CEF/JSON/Syslog, UDP/TCP/TLS/HEC)
│   └── alerts/                 # Alert plugins (mail, LINE, webhook)
├── config/                     # config.json, report_config.yaml
├── docs/                       # EN + ZH_TW documentation
├── tests/                      # 19 test files (116 tests)
├── deploy/                     # systemd (Ubuntu/RHEL) + NSSM (Windows) service configs
└── scripts/                    # Utility scripts
```
