# Illumio PCE Ops

![Version](https://img.shields.io/badge/Version-v3.20.0--report--intelligence-blue?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.8%2B-yellow?style=flat-square&logo=python&logoColor=white)
![API](https://img.shields.io/badge/Illumio_API-v25.2-green?style=flat-square)

> Primary documentation is now consolidated in Traditional Chinese: [README_zh.md](README_zh.md).

Illumio PCE Ops is an agentless operations toolkit for Illumio Core / PCE. It covers CLI and daemon monitoring, a Flask Web GUI, traffic and audit reporting, PCE Cache, SIEM Preview forwarding, scheduled reports, rule scheduling, workload quarantine, and i18n-aware HTML/CSV/PDF/XLSX outputs.

## Quick Start

```bash
git clone <repo-url>
cd illumio_ops
cp config/config.json.example config/config.json
python illumio_ops.py
```

Common commands:

```bash
python illumio_ops.py --gui
python illumio_ops.py --monitor --interval 5
python illumio_ops.py report traffic --format html --profile security_risk
python illumio_ops.py cache status
python illumio_ops.py siem status
```

## Documentation

The long-form English duplicates were removed to reduce document sprawl. Use the consolidated canonical docs:

| Document | Purpose |
|:---|:---|
| [Chinese README](README_zh.md) | Project overview |
| [User Manual](docs/User_Manual_zh.md) | Install, operation, deployment, reports, cache, SIEM Preview |
| [Architecture](docs/Project_Architecture_zh.md) | Feature inventory, architecture, data flow |
| [API / Integration Guide](docs/API_Cookbook_zh.md) | PCE API, internal APIs, SIEM/SOAR examples |
| [Security Rules Reference](docs/Security_Rules_Reference_zh.md) | R/B/L findings, thresholds, port reference |
| [SIEM Integration](docs/SIEM_Integration.md) | Existing English SIEM integration compatibility doc |
