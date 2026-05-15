# illumio-ops

![Version](https://img.shields.io/badge/Version-v3.25.0--tracks--abcd-blue?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.10%2B-yellow?style=flat-square&logo=python&logoColor=white)
![API](https://img.shields.io/badge/Illumio_API-v25.2-green?style=flat-square)

> **[English](README.md)** | **[繁體中文](README_zh.md)**

**illumio-ops** is an agentless monitoring and automation companion for **Illumio Core (PCE)**, communicating exclusively via the PCE REST API. It fills the operational gaps left by the PCE Web Console: scheduled traffic/audit/VEN-status reports, multi-channel alerting (Email, LINE, Webhook), SIEM forwarding, safe rule scheduling, workload quarantine, and multi-PCE management — all without deploying agents or touching workloads.

---

## Quick Start

```bash
git clone <repo-url>
cd illumio-ops
cp config/config.json.example config/config.json   # edit api.url / api.key / api.secret
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Persistent daemon + Web GUI at https://127.0.0.1:5001
python illumio-ops.py --monitor-gui --interval 5 --port 5001
```

First login: `illumio` / `illumio` (forced password change on first use).

For air-gapped installs, systemd/NSSM service setup, and Windows deployment, see **[docs/getting-started.md](docs/getting-started.md)**.

---

## Documentation

All documentation lives in [docs/](docs/). Start at [INDEX.md](docs/INDEX.md).

Chinese (繁體中文): [INDEX_zh.md](docs/INDEX_zh.md).

---

## Highlights

- **Four execution modes** — background daemon, interactive CLI, standalone Web GUI, or combined monitor + GUI (`--monitor-gui`)
- **24 automated security rules** — B-series (ransomware/coverage), L-series (lateral movement/exfiltration), R-series (Draft policy alignment)
- **15-module traffic reports** + audit, policy usage, and VEN status reports; HTML / CSV / PDF / XLSX output
- **SIEM forwarder** — CEF, JSON, RFC5424 syslog, Splunk HEC over UDP/TCP/TLS/HTTPS with per-destination DLQ
- **Full i18n** — English and Traditional Chinese (繁體中文) across CLI, Web GUI, reports, and alerts
