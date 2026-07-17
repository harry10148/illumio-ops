# illumio-ops

![Version](https://img.shields.io/badge/Version-v4.1.0-blue?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.10%2B-yellow?style=flat-square&logo=python&logoColor=white)
![API](https://img.shields.io/badge/Illumio_API-v25.2-green?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-lightgrey?style=flat-square)

> **[English](README.md)** | **[繁體中文](README_zh.md)**

**illumio-ops** is an **agentless** monitoring and automation companion for **Illumio Core**. It talks to the
**PCE (Policy Compute Engine) exclusively via the PCE REST API** — no agents are deployed, no Workloads are
touched. It fills the operational gaps left by the PCE Web Console: scheduled reports, a security-rule engine
over traffic flows, multi-channel alerting, SIEM forwarding, safe rule scheduling, and Workload quarantine —
all from a single Python process exposing a Flask Web GUI, a Click CLI, and a background scheduler.

## Features

- **9-report family** — traffic, security & risk, audit, policy usage, VEN status, enforcement readiness, rule
  hit count, policy diff (draft vs active), and policy resolver, rendered to HTML / CSV / XLSX.
- **B/L/R security-rule engine** — B-series (ransomware / coverage) and L-series (lateral movement /
  exfiltration) findings on traffic flows, plus R-series (R01–R05) draft-policy alignment checks.
- **FilterBar v2 object selectors** — PCE-style label / IP-list / service filter objects shared across the
  GUI and report engine, instead of free-text filter strings.
- **5 alert channels** — Email, LINE, Webhook, Telegram, and Teams, with per-destination DLQ and a watchdog.
- **SIEM forwarding** — CEF, JSON, and RFC5424 syslog, plus Splunk HEC, over UDP / TCP / TLS / HTTPS.
- **Rule scheduler** — enable/disable PCE rules on a time window, with explicit CLI/GUI confirmation gates.
- **Workload quarantine** — apply and release quarantine from the GUI or CLI, with an audit trail.
- **pce_cache SQLite mirror** — optional WAL-mode local cache of PCE events and traffic, so reports and the
  dashboard don't hammer the PCE.
- **Job health observability** — every background job records `last_run` / `last_status` to
  `logs/job_health.json`, so "should have run but didn't" is visible.
- **Offline bundle installer** — air-gapped install path that ships pinned wheels alongside the source tree.

## Quick Start

```bash
git clone <repo-url>
cd illumio-ops
cp config/config.json.example config/config.json   # edit api.url / api.org_id / api.key / api.secret
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Combined daemon + Web GUI at https://127.0.0.1:5001
python illumio-ops.py --monitor-gui --interval 5 --port 5001
```

**First login:** default account `illumio` / password `illumio`; the forced first-login password change is currently disabled — change the password manually in Settings after first login. GUI passwords are hashed
with **Argon2id**.

The entry point `illumio-ops.py` dispatches to the **Click** command tree (e.g. `illumio-ops report traffic
--format html`, `illumio-ops status`) and keeps a **legacy argparse** path for the classic `--monitor` /
`--gui` / `--report` flags — both styles work.

## Full documentation (Traditional Chinese)

Project documentation is maintained in Traditional Chinese. Start at **[docs/INDEX.md](docs/INDEX.md)** for
the full documentation map — architecture, guides, and reference material.

## License

Released under the **MIT License** — see [LICENSE](LICENSE).
