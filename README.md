# illumio-ops

![Version](https://img.shields.io/badge/Version-v6.1.0-blue?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.12-yellow?style=flat-square&logo=python&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-lightgrey?style=flat-square)

> **[English](README.md)** | **[繁體中文](README_zh.md)**

**illumio-ops** is an agentless companion for **Illumio Core** focused on **lateral movement**: it reads the PCE
through its REST API only (no agents, nothing changed on Workloads unless an operator quarantines one) and runs as
one service with a web GUI. v6 is a rebuild of 5.x; it has no command line.

- **Detection** of lateral movement (fan-out, new management connections, pivot chains, cross-environment, …) and
  of anomalies in allowed traffic, on a home focus list and the lateral-movement page.
- **Alerts** on PCE events, traffic, detections and the product's own health, to email, LINE, Telegram, Teams and
  webhooks; rules can leave out labels, Workloads, addresses, PCE IP lists and public addresses.
- **Reports** (HTML, CSV, XLSX, JSON) by schedule or on demand, mailed with a readable summary.
- **Investigation workbench**, host profiles, quarantine, Rule Hit Count.
- **SIEM forwarding** of audit events, detections, alerts and new connections (syslog, TLS, Splunk HEC; CEF or JSON).
- Three collection modes: lightweight (default; queries the PCE on demand), alerts, full.

## Install, upgrade from 5.x, roll back

See [docs/guide/v6-installation.md](docs/guide/v6-installation.md): an offline bundle for Linux x86_64 (RHEL/Rocky),
`install.sh` for a fresh install or an upgrade of a 5.x installation (settings carried over, SIEM and event alerts
continue where 5.x stopped), and `rollback.sh` to go back. 5.x documentation is kept in
[docs/legacy-5.x](docs/legacy-5.x/).

## Development

```
python3.12 -m venv .venv && .venv/bin/pip install --require-hashes -r requirements.lock -r requirements-dev.txt
npm ci --prefix web
bash scripts/gen_contracts.sh && npm --prefix web run build
.venv/bin/python -m pytest tests -n auto --dist loadfile
```

CI (`.github/workflows/ci.yml`) also runs pip-audit, the contract diff, the frontend typecheck and build, ruff and
mypy (strict). The offline bundle is built by `scripts/build_bundle.sh`.
