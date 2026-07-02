# illumio-ops

![Version](https://img.shields.io/badge/Version-v4.1.0-blue?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.10%2B-yellow?style=flat-square&logo=python&logoColor=white)
![API](https://img.shields.io/badge/Illumio_API-v25.2-green?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-lightgrey?style=flat-square)

> **[English](README.md)** | **[繁體中文](README_zh.md)**

**illumio-ops** is an **agentless** monitoring and automation companion for **Illumio Core**, talking to the **PCE (Policy Compute Engine) exclusively via the PCE REST API** — no agents are deployed and no Workloads are touched. It fills the operational gaps left by the PCE Web Console: scheduled traffic / audit / policy-usage / VEN-status reports, a B/L/R security-rule engine over traffic flows, multi-channel alerting, SIEM forwarding, safe rule scheduling, Workload quarantine, and multi-PCE management — all from a single Python process exposing a Flask Web GUI, a Click CLI, and a background scheduler.

---

## Highlights

- **Four execution modes** — background daemon (`--monitor`), standalone Web GUI (`--gui`), combined monitor + GUI (`--monitor-gui`), or an interactive CLI menu.
- **24 automated security rules** — B-series (ransomware / coverage), L-series (lateral movement / exfiltration), and R-series R01–R05 (Draft policy alignment) evaluated against PCE traffic flows.
- **Rich report engine** — three traffic report profiles (`report traffic` for plain traffic facts, `report security` for the 15-module security & risk analysis, `report inventory` for network inventory) plus audit, policy-usage, and VEN-status reports, rendered to **HTML / CSV / XLSX**.
- **Multi-channel alerts** — Email, LINE, Webhook, Telegram, and Teams.
- **SIEM forwarder** — CEF, JSON, and RFC5424 syslog, plus Splunk HEC, over UDP / TCP / TLS / HTTPS with a per-destination dead-letter queue (DLQ).
- **Local SQLite cache** — optional WAL-mode mirror of PCE events and traffic with retention TTLs, so reports and the dashboard run without hammering the PCE.
- **Hardened Web GUI** — cheroot HTTPS server, Argon2id password hashing, CSRF/CSP/HSTS middleware, rate limiting, and an IP allowlist.
- **Full bilingual i18n** — English and Traditional Chinese (繁體中文) at parity (~4,043 keys each) across CLI, Web GUI, reports, and alerts, with a glossary that keeps Illumio terms (PCE, VEN, Workload, Service, Port, Policy) in English.

---

## Architecture Overview

illumio-ops runs as a **single Python process**. It pulls data from one or more PCE instances over the REST API, optionally caches it in SQLite, evaluates it with the rule and report engines, and surfaces results through the Web GUI, CLI, scheduled reports, alerts, and the SIEM pipeline.

```text
┌───────────────────────────────────────────────────────────────────────┐
│  Illumio Core — PCE (Policy Compute Engine)                           │
│  REST API over HTTPS · workloads, labels, rulesets, events,          │
│  traffic flows, draft policy                                         │
└──────────────────────────────┬────────────────────────────────────────┘
                               │  agentless · PCE REST API only
                               │  async traffic (Explorer) queries · native filters
                               ▼
┌───────────────────────────────────────────────────────────────────────┐
│  api/ + api_client.py        PCE REST client (requests)               │
└──────────────────────────────┬────────────────────────────────────────┘
                               ▼
┌───────────────────────────────────────────────────────────────────────┐
│  pce_cache/                  SQLite (WAL) local mirror                 │
│  ingestors · aggregator · retention · reader · subscriber · backfill  │
└──────────────────────────────┬────────────────────────────────────────┘
                               ▼
┌──────────────────────────────────────┐   ┌────────────────────────────┐
│  analyzer.py + report/ rule engine   │   │  events/ pipeline           │
│  B/L/R flow→rule matching · monitor  │   │  poll → normalize → dedup → │
│  cycle · 15 traffic modules + audit  │   │  throttle → classify        │
│  + policy-usage + VEN status         │   │  (vendor catalog) → shadow  │
│                                      │   │  → stats → runbooks         │
└──────────────────┬───────────────────┘   └─────────────┬──────────────┘
                   │                                     │
       ┌───────────┴───────────────┬─────────────────────┘
       ▼                           ▼                     ▼
┌──────────────┐  ┌────────────────────────┐  ┌───────────────────────────────┐
│ report/      │  │ reporter.py + alerts/  │  │ siem/ forwarder               │
│ exporters    │  │ Email · LINE · Webhook │  │ CEF · JSON · RFC5424 syslog · │
│ HTML·CSV·XLSX│  │ · Telegram · Teams     │  │ Splunk HEC over UDP/TCP/TLS/  │
│              │  │                        │  │ HTTPS + per-dest DLQ          │
└──────────────┘  └────────────────────────┘  └───────────────────────────────┘

   Presented through:  gui/ (Flask + cheroot HTTPS, ~88 routes)  ·  cli/ (Click + interactive menu)
   Driven on a timer:  scheduler/ (cron jobs: scheduled reports, cache polls, rule-scheduler checks)
```

**Data flow:** `PCE REST API → pce_cache (SQLite) → analyzer / report rule engine → reports + alerts + SIEM`, with the Web GUI and CLI sitting on top and the scheduler driving the periodic work.

### Subsystems (`src/`)

| Subsystem | Responsibility |
|---|---|
| `api/` + `api_client.py` | PCE REST client — async traffic (Explorer) queries, native server-side filters, label / Workload / ruleset / event fetch, and `update_rules` for draft policy. |
| `pce_cache/` | Optional SQLite WAL local mirror — event & traffic ingestors, aggregator, retention (TTL), reader, subscriber, backfill, watermark cursor, and PCE rate limiter. |
| `analyzer.py` | The B/L/R flow-to-rule matching engine and the monitor cycle (event/traffic analysis and state management). |
| `events/` | Event pipeline — poll → normalize → dedup → throttle → classify against a vendor event catalog → shadow → stats → runbooks. |
| `report/` | Report engine — 15 traffic-analysis modules plus audit, policy-usage, VEN-status, and the R-rules; HTML / CSV / XLSX exporters, PCE parsers, and the B/L rules engine. |
| `reporter.py` + `alerts/` | Multi-channel alert dispatch — Email, LINE, Webhook, Telegram, and Teams plugins. |
| `siem/` | SIEM forwarder — CEF / JSON / RFC5424-syslog / Splunk-HEC formatters over UDP / TCP / TLS / HTTPS transports, with a per-destination DLQ. |
| `gui/` | Flask Web GUI (~88 routes) across `auth` / `admin` / `dashboard` / `events` / `reports` / `rules` / `rule_scheduler` / `actions` / `config` blueprints, served by cheroot over HTTPS. |
| `cli/` | Click command tree (`monitor`, `monitor-gui`, `gui`, `report`, `rule`, `workload`, `siem`, `cache`, `config`, `status`, `version`) plus questionary-driven interactive menus. |
| `scheduler/` | Cron-style scheduled jobs — scheduled reports, cache polls, and rule-scheduler checks. |
| `config.py` + `settings/` | `ConfigManager` (Argon2id GUI password, atomic config writes) and the interactive settings wizards. |
| `i18n/` | Runtime translation layer — English + Traditional Chinese at parity (~4,043 keys), with glossary-preserved terms. |

A fuller, file-by-file tour now lives in the **Operations Manual** — **[docs/operations-manual_zh.md](docs/operations-manual_zh.md)** (操作手冊, 繁體中文).

---

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

**First login:** account `illumio`, with a **forced password change on first use**. GUI passwords are hashed with **Argon2id**.

### Execution modes

| Mode | Command | What it does |
|---|---|---|
| Background daemon | `python illumio-ops.py --monitor --interval 5` | Headless monitor cycle: polls the PCE, runs rules, sends alerts, forwards to SIEM. |
| Standalone Web GUI | `python illumio-ops.py --gui --port 5001` | Serves the Flask dashboard only. |
| Monitor + GUI | `python illumio-ops.py --monitor-gui --interval 5 --port 5001` | Both of the above in one process (recommended for a service). |
| Interactive CLI menu | `python illumio-ops.py` | A questionary-driven TUI for configuration and one-off actions. |

The entry point `illumio-ops.py` dispatches to the **Click** command tree for subcommands (e.g. `illumio-ops report traffic`, `illumio-ops status`) and keeps a **legacy argparse** path for the classic `--monitor` / `--gui` / `--report` flags — both styles work.

For air-gapped installs, the systemd service, and Windows (NSSM) deployment, see **[docs/getting-started.md](docs/getting-started.md)**.

---

## Project Structure

```text
illumio-ops/
├── illumio-ops.py              # Entry point — dispatches to Click subcommands or the legacy argparse path
├── src/
│   ├── main.py                 # Legacy argparse path (--monitor / --gui / --report) + interactive menu
│   ├── api_client.py           # PCE REST client (async jobs, native filters, draft-policy update_rules)
│   ├── api/                    # PCE API helpers — async_jobs, labels, traffic_query (Explorer)
│   ├── analyzer.py             # B/L/R flow-to-rule matching engine + monitor cycle
│   ├── cli/                    # Click command tree + shared output/exit-code helpers + menus/
│   ├── gui/                    # Flask Web GUI — app shell (cheroot HTTPS) + routes/ blueprints (~88 routes)
│   ├── config.py               # ConfigManager (Argon2id GUI password, atomic writes)
│   ├── config_models.py        # pydantic config models
│   ├── reporter.py             # Multi-channel alert dispatch orchestration
│   ├── alerts/                 # Alert plugins — Email, LINE, Webhook, Telegram, Teams
│   ├── events/                 # Event pipeline — catalog, normalizer, throttle, shadow, stats, runbooks
│   ├── report/                 # Report engine — analysis/ (15 modules), rules/ (R01–R05), exporters/, parsers/
│   ├── report_scheduler.py     # Scheduled-report execution + retention
│   ├── scheduler/              # APScheduler-style cron jobs
│   ├── pce_cache/              # SQLite WAL cache + ingestors/aggregator/retention/reader/subscriber/backfill
│   ├── siem/                   # SIEM forwarder — formatters/ (CEF/JSON/syslog), transports/ (UDP/TCP/TLS/HEC), DLQ
│   ├── settings/               # Interactive settings wizards
│   ├── i18n/                   # i18n engine (glossary, strict prefixes); catalogs at src/i18n_en.json / src/i18n_zh_TW.json
│   ├── templates/              # Flask HTML templates (login, index)
│   └── static/                 # Vendored fonts, JS, CSS
├── config/                     # config.json (+ .example), alerts.json, rule_schedules.json, tls/  (secrets gitignored)
├── docs/                       # Bilingual documentation (EN + 繁體中文) — start at docs/INDEX.md
├── deploy/                     # systemd unit + Windows NSSM service configs + log-shipping examples
├── scripts/                    # install.sh, offline-bundle build, preflight, version bump
├── tests/                      # Test suite
└── reports/                    # Generated report output + audit findings
```

---

## Documentation

All documentation lives under [`docs/`](docs/). Start at the hub, then dive into the core manuals:

- **[docs/INDEX.md](docs/INDEX.md)** / **[docs/INDEX_zh.md](docs/INDEX_zh.md)** — the documentation map.
- **操作手冊 — Operations Manual:** [docs/operations-manual_zh.md](docs/operations-manual_zh.md) — install, deploy, configure, run, and operate illumio-ops (繁體中文).
- **事件規則說明 — Event Rules:** [docs/event-rules_zh.md](docs/event-rules_zh.md) — the real-time monitor rule engine, the B/L/R report rule engine, and the event pipeline, audited line-by-line against the source (繁體中文).
- **Getting started:** [docs/getting-started.md](docs/getting-started.md) / [docs/getting-started_zh.md](docs/getting-started_zh.md).
- **Reference:** [reference/cli.md](docs/reference/cli.md), [reference/glossary.md](docs/reference/glossary.md), [reference/rest-api.md](docs/reference/rest-api.md) (each with a `_zh` sibling).
- **Contributing:** [contributing/dev-setup.md](docs/contributing/dev-setup.md), [contributing/i18n-workflow.md](docs/contributing/i18n-workflow.md), [contributing/release-process.md](docs/contributing/release-process.md).
- **Latest audit:** [reports/audit/2026-06-26-static-findings.md](reports/audit/2026-06-26-static-findings.md).

Historical and superseded docs (the old `user-guide/` and `architecture/` sets, UX reviews, the 2026-05-22 security audit, and session handoffs) have been removed from the tree; they remain recoverable from git history.

---

## Security Rules

illumio-ops ships **24 automated rules** evaluated against PCE traffic flows by the report rule engine:

- **B-series (B001–B009)** — ransomware exposure and segmentation-coverage findings.
- **L-series (L001–L010)** — lateral-movement and data-exfiltration findings.
- **R-series (R01–R05)** — Draft policy alignment (draft-deny detected, override-deny, visibility-boundary breach, allowed-across-boundary, draft/reported mismatch).

Each rule carries a severity, bilingual `desc_key` / `rec_key` i18n keys, and remediation guidance. The catalog is browsable from the GUI **Rules** page; the judgment logic is implemented in `src/report/rules_engine.py` and `src/report/rules/`.

> **Note:** The R-series (R01–R05) engine **is wired** — `RulesEngine.evaluate()` calls `_eval_draft_pd()`, which runs R01–R05 whenever the unified DataFrame carries a `draft_policy_decision` column (populated by `flatten_flow_record`). A **live PCE test on 2026-06-26** confirmed the PCE returns `draft_policy_decision` for every flow when a traffic query runs with draft computation (`update_rules`, ~12 s), so the draft data is **proven available**. Activation is **on-demand** for draft-policy analysis rather than wired into every report — cache-served reports carry no draft column and skip the R-rules without paying the ~12 s cost. See [Status & Notes](#status--notes).

---

## Deployment & Security Notes

### Canonical install (`/opt/illumio-ops`)

The supported install path is **`/opt/illumio-ops`** via **[`scripts/install.sh`](scripts/install.sh)**, which provisions a hardened systemd service:

- Creates a dedicated, login-less system account (`useradd --system --no-create-home --shell /sbin/nologin`).
- Installs to `/opt/illumio-ops` and registers `deploy/illumio-ops.service` with `NoNewPrivileges=true` and `ProtectHome=true`.

> Do **not** deploy under `/root/illumio-ops` — that is a legacy, unhardened dev layout.

### Reverse proxy (ProxyFix)

The service does **not** automatically configure Flask `ProxyFix`. Behind nginx / Apache / Traefik you **must** apply `ProxyFix` (trusting exactly one hop) before the cheroot server starts, otherwise the IP allowlist sees only the proxy's address and every request appears to originate there.

### TLS / self-signed certificates

The GUI can run over HTTP (dev/internal) or HTTPS. cheroot terminates TLS natively with a hardened cipher list. Use the built-in CSR/self-signed certificate workflow (GUI settings or `illumio-ops config`) and store the key/cert under `config/tls/`.

### IP allowlist

`web_gui.allowed_ips` restricts which client addresses may reach the GUI. Combine with `--host 127.0.0.1` and/or a reverse proxy for defence in depth.

### Secrets

`config/config.json` holds PCE API credentials and alert-channel secrets in plaintext, so it — along with `config/alerts.json`, `config/rule_schedules.json`, and `config/tls/` — is **gitignored**. Apply restrictive filesystem permissions (e.g. `chmod 600`). illumio-ops performs **no outbound telemetry**: the only outbound connections are to the configured PCE and to SIEM / alert destinations.

### Telegram alert plugin — token leakage via proxy access logs

The Telegram Bot API embeds the bot token in the **URL path** (`https://api.telegram.org/bot<TOKEN>/sendMessage`). In high-sensitivity environments, prevent any forward proxy or WAF from writing full URL paths to access logs, use a direct (NoProxy) connection to bypass corporate proxies, or switch to webhook mode (the webhook URL does not contain the token). The Loguru token scrubber redacts local logs but cannot protect intermediate network devices.

### Server header fingerprinting

cheroot emits `Server: Cheroot/<version>` by default, exposing version information to fingerprinting. If your audit policy requires header suppression, strip it at the reverse proxy with `proxy_hide_header Server;` (nginx) or an equivalent directive.

### Production git workflow — autoStash and reproducibility

`scripts/setup-prod-git.sh` enables `git config merge.autoStash=true`, so a production host may silently stash uncommitted local edits during `git pull`. The host may then not be bit-for-bit **reproducible** against the deployed git tag. After each deployment, run `git stash list` and confirm it is empty; for hosts where reproducibility must be guaranteed, use `scripts/setup.sh` instead.

---

## Status & Notes

This branch resolved **all 11 HIGH-severity findings** and the large majority of the **2026-06-26 audit** ([`reports/audit/2026-06-26-static-findings.md`](reports/audit/2026-06-26-static-findings.md)). The audit items that earlier drafts listed as limitations — the report-scheduler local-timezone crash, report-output HTML escaping / XSS, SIEM syslog-over-TLS custom-CA handling, and the pce_cache incremental-ingestion edge cases — are now **fixed**. The full test suite passes (**1,969 tests**), and a live PCE test on **2026-06-26** confirmed end-to-end behavior.

Genuine current notes:

- **R-series rules are activated on-demand** — the R01–R05 engine is wired and the PCE draft data is proven available (live-verified 2026-06-26); it runs as a draft-policy analysis pass rather than on every report (see [Security Rules](#security-rules)).
- **No PDF report output** — reports render to **HTML / CSV / XLSX** only; there is no PDF exporter (the `--format pdf` flag is a legacy no-op).
- **Minor i18n / typing backlog** — a few low/info-severity i18n labels remain (analyzer debug output, `run_ven_summary`), alongside a pre-existing `mypy` type-annotation backlog.
- **ProxyFix is not applied by the app** — operators behind a reverse proxy must add Flask `ProxyFix` themselves; otherwise the IP allowlist sees only the proxy's address.

---

## Internationalization (i18n)

All user-visible text uses `t(key, lang=lang)`. The single source of truth is **`src/i18n_en.json`** and **`src/i18n_zh_TW.json`** (~4,043 keys each, at parity — every key exists in both files with no runtime auto-translation). A **glossary** (`src/i18n/data/glossary.json`) keeps domain terms — PCE, VEN, Workload, Service, Port, Policy, Ruleset, Enforcement — in English inside Chinese values.

When adding a key, add it to **both** JSON files and reference it via `t("your_key", lang=lang)`; per the [AGENTS.md](AGENTS.md) guardrail, run `python3 scripts/audit_i18n_usage.py` and the i18n tests before merging. See [docs/contributing/i18n-workflow.md](docs/contributing/i18n-workflow.md) for the full workflow.

---

## License

Released under the **MIT License** — see [LICENSE](LICENSE).
