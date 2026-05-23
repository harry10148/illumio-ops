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

![Version](https://img.shields.io/badge/Version-v4.0.0--secure--modern--saas-blue?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.10%2B-yellow?style=flat-square&logo=python&logoColor=white)
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
| **Advanced Report Engine** | 15-module traffic reports with **Bulk-Delete** management; 4-module audit reports, policy usage reports, and VEN Status inventory reports — HTML, CSV, PDF, XLSX, or all formats |
| **Security Findings** | 24 automated rules: B-series (B001–B009: Ransomware, Coverage) + L-series (L001–L010: Lateral Movement, Exfiltration) + R-series (R01–R05: Draft Policy alignment) |
| **Report Schedules** | Cron-style recurring reports (daily/weekly/monthly) with automatic email delivery |
| **Rule Scheduler** | Auto enable/disable PCE rules; **three-layer Draft protection** prevents accidental provisioning |
| **Workload Quarantine** | Isolate compromised workloads with Quarantine labels; supports IP/CIDR/subnet search |
| **Multi-Channel Alerts** | Email (SMTP), LINE Notifications, and Webhooks dispatched simultaneously |
| **Internationalization** | Full English + Traditional Chinese (繁體中文) across CLI, Web GUI, reports, and alerts |

> [!NOTE]
> **SIEM Forwarder** — built-in CEF / JSON / RFC5424 syslog / Splunk HEC forwarding over UDP / TCP / TLS / HTTPS, with per-destination DLQ and exponential backoff. New cache rows are enqueued inline at ingest time. See **[SIEM Integration](docs/SIEM_Integration.md)**.

---

## Quick Start (development from source)

> Production deployments use the self-contained offline bundle (no system Python, no network on target). See **[Installation](docs/Installation.md#12-installation)** for the bundle workflow on Linux and Windows.

### Prerequisites

- **PCE admin access** to mint an API Key — in the PCE Web Console, top-right user menu → **My API Keys** → **Add**. Save the resulting `auth_username` (treat as `api.key`) and `secret`.
- **Network reachability** from this host to PCE on HTTPS (typically port 8443).
- **Python 3.10+** with `venv`. On Ubuntu 22.04+ / Debian 12+ a venv is required (PEP 668).
- For lab PCEs using a **self-signed TLS certificate**, set `api.verify_ssl: false` in `config.json` after copying the example — otherwise the first connection fails with an SSL verification error.

### Run

```bash
git clone <repo-url>
cd illumio-ops
cp config/config.json.example config/config.json    # Then edit api.url / api.key / api.secret with the values from "My API Keys"
python -m venv venv && source venv/bin/activate     # Required on Ubuntu 22.04+ / Debian 12+ (PEP 668)
pip install -r requirements.txt

# Most common: persistent daemon + Web GUI on https://127.0.0.1:5001
python illumio-ops.py --monitor-gui --interval 5 --port 5001
```

### Verify it worked

On first run you should see, in order:

1. A `DEFAULT ADMIN LOGIN` banner on stderr printing `username: illumio` / `password: illumio` (the well-known default — the first login forces a change).
2. `TLS: Using self-signed certificate (NNN days remaining)`.
3. `Open in browser: https://127.0.0.1:5001` and (in non-daemon mode) the browser auto-opens.

In the browser: dismiss the self-signed-cert warning, log in as `illumio` / `illumio`, set a new password, then check the Dashboard — the **PCE Status** widget should report "connected". If it shows "auth failed", re-check `api.key` / `api.secret`.

For air-gapped deployments, systemd / NSSM service registration, and the full dependency list, see **[Installation](docs/Installation.md)**. For all execution modes (`--gui` / `--monitor` / interactive CLI), the full subcommand reference, and the operational walkthrough, see **[User Manual §1](docs/User_Manual.md)**.

### First Login (security)

The default credentials `illumio` / `illumio` are seeded automatically on first startup; the GUI gates the session with `must_change_password=true` until the password is changed (see `src/config.py:200`). The plaintext default is also stored at `web_gui._initial_password` in `config.json` — it is wiped on the first successful password change. Full flow: **[User Manual §3](docs/User_Manual.md#3-web-gui-security)**.

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
├── illumio-ops.py          # Entry point — dispatcher routes to click subcommands or legacy argparse
├── src/
│   ├── main.py                 # Legacy argparse path (--monitor / --gui / --report); delegates to src/cli for new flags
│   ├── api_client.py           # PCE REST API (async jobs, native filters, O(1) streaming)
│   ├── api/                    # PCE API helpers (async jobs, labels, traffic queries)
│   ├── analyzer.py             # Rule engine (flow matching, event analysis, state mgmt)
│   ├── cli/                    # Click subcommands + shared output / exit-code helpers (root, monitor, gui_cmd, report, rule, workload, cache, siem, status, config, menus/)
│   ├── gui/                    # Flask Web GUI package — shell + Blueprint routes (auth/admin/dashboard/events/reports/rules/rule_scheduler/actions/config) — ~70 routes total
│   ├── config.py               # ConfigManager (Argon2id GUI password, atomic writes)
│   ├── reporter.py             # Multi-channel alert dispatch (SMTP, LINE, Webhook)
│   ├── i18n/                   # i18n engine (engine.py + JSON data) — EN/ZH_TW with ~2,800 string keys
│   ├── events/                 # Event pipeline (catalog, normalize, dedup, throttle)
│   ├── report/                 # Report engine (15 traffic modules + audit + policy usage + R3 intelligence add-ons)
│   ├── scheduler/              # Report-schedule cron jobs
│   ├── settings/               # Interactive settings wizards (split from legacy settings.py)
│   ├── pce_cache/              # SQLite WAL cache + ingestors
│   ├── siem/                   # SIEM forwarder (CEF/JSON/Syslog, UDP/TCP/TLS/HEC)
│   ├── alerts/                 # Alert plugins (mail, LINE, webhook)
│   ├── templates/              # Flask HTML templates (login, index)
│   └── static/                 # Vendored fonts (Space Grotesk / Inter / JetBrains Mono), JS, CSS
├── config/                     # config.json, alerts.json, report_config.yaml, rule_schedules.json
├── docs/                       # EN + ZH_TW documentation
├── tests/                      # ~178 test files (~970 tests)
├── deploy/                     # systemd (Ubuntu/RHEL) + NSSM (Windows) service configs
└── scripts/                    # Utility scripts (offline bundle build, install/uninstall, preflight)
```

---

## Deployment Notes / 部署注意事項

> Audit reference: `docs/security-audit-2026-05-22.md` L-11 through L-14.

### L-11: Reverse Proxy

This service does **not** automatically configure Flask `ProxyFix`. When deployed behind a reverse proxy (nginx, Apache, Traefik):

- You **must** apply `ProxyFix` middleware before the app starts, trusting exactly 1 hop.
- Without it, IP allowlisting breaks — all requests appear to originate from the proxy's IP.

Example (add before the cheroot server starts in `src/gui/__init__.py`):

```python
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
```

### L-12: Telegram Alert Plugin — Token Leakage via Proxy Access Logs

The Telegram Bot API embeds the token in the URL path (`https://api.telegram.org/bot<TOKEN>/sendMessage`). When deploying the Telegram alert plugin in financial, defence, or high-sensitivity environments, you **must** do one of the following:

- Prevent any forward proxy or WAF from writing full URL paths to access logs.
- Use a direct (NoProxy) connection to bypass corporate proxies.
- Switch to webhook mode (though webhooks still pass through the proxy; the URL does not contain the token).

Loguru logging includes a Telegram token regex scrubber (commit T2.14), but this cannot protect intermediate network devices.

### L-13: Server Header Fingerprinting

cheroot outputs `Server: Cheroot/<version>` by default, exposing version information to fingerprinting. If your audit policy requires header suppression:

- Strip the header at the reverse proxy with `proxy_hide_header Server;` (nginx) or equivalent.
- Alternatively, add a custom cheroot WSGI middleware to remove the header (planned enhancement).

### L-14: Production Git Workflow — autoStash and Reproducibility

`scripts/setup-prod-git.sh` enables `git config merge.autoStash=true`, which means the production host may silently stash **uncommitted local edits** during `git pull` without warning. Consequences:

- The production host may **not** be bit-for-bit reproducible against the deployed `git tag`.
- To prove production exactly matches a release tag during an audit, you must verify no stashed changes exist: `git stash list` must be empty.

**Recommendation:** After each production deployment, run `git stash list` and confirm it is empty. Consider using `scripts/setup.sh` instead of `setup-prod-git.sh` for production hosts where reproducibility must be guaranteed.

## Translations (i18n)

**Single source of truth:** `src/i18n_en.json` and `src/i18n_zh_TW.json` (~2,767 keys each). Every key has an explicit value in both files; no runtime auto-translation.

**Adding a key:**
1. Add the key to **both** JSON files. Use a strict-prefix (`gui_`, `rpt_`, `rule_`, etc. — see `src/i18n/data/strict_prefixes.json`) so a missed translation surfaces as `[MISSING:key]` instead of leaking English.
2. Reference via `t("your_key", lang=lang)`. For request-scoped contexts (web routes, report rendering), always pass `lang=`; never call `set_language()` from a handler — `tests/test_i18n_set_language_callers.py` enforces this.
3. Run `python scripts/audit_i18n_usage.py` to verify glossary respect (Cat E) and parity (Cat I).

**Glossary:** `src/i18n/data/glossary.json` lists English terms that must NOT translate to Chinese in `zh_TW` values. Includes Illumio terminology (Block/Allow/Manage/Unmanage, PCE/VEN, Workload, Service, Port, Policy, Ringfence) plus general dev jargon (SMTP, Online/Offline, App, Label, Ruleset, Enforcement). Adding a new glossary term: append to `preserve_in_zh_tw` and add forbidden Chinese substitutes to `forbidden_zh_substitutes`.

**Reports:** Use `t(key, lang=lang)` directly. The legacy `STRINGS` dict in `src/report/exporters/report_i18n.py` is now a thin compatibility wrapper (`_StringsView`) over `t()` — for new code prefer `t()`.

**Rules (config.json):** Persist `desc_key` and `rec_key`, never localized `desc`/`rec` text. The loader (`ConfigManager._resolve_rule_keys`) renders keys via `t()` at read time per the active language. The migration script `scripts/migrate_rules_to_keys.py` upgrades rules from older format.

**`t()` API:**
```python
from src.i18n import t

# Use process-global language (default)
t("rpt_kicker_traffic")

# Override per call (request-scoped, thread-safe)
t("rpt_kicker_traffic", lang="zh_TW")

# With format() substitution
t("rpt_email_traffic_subject", count=42, lang=lang)

# With explicit fallback
t("possibly_missing_key", default="N/A", lang=lang)
```

**`set_language(lang)`:** Process bootstrap only (CLI startup, ConfigManager.load). Do NOT call from request handlers, scheduler tasks, or anywhere with concurrency.

**Known open items:**
- ~90 pre-existing `zh_TW` values violate the glossary preserve-list (`Label→標籤`, `Offline→離線`, etc.). They were hidden until T8 externalized the glossary (commit ce94d9a). The `forbidden_zh_substitutes` list in `glossary.json` is the source of truth; remediation requires manual edits to `i18n_zh_TW.json`. Tracked by xfail in both `tests/test_i18n_glossary.py::test_zh_tw_values_preserve_glossary_terms` and `tests/test_i18n_audit.py::test_comprehensive_i18n_audit_is_clean`.
