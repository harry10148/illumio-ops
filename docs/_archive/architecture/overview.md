---
title: Architecture Overview
audience: [developer, security, api]
last_verified: 2026-05-15
verified_against:
  - src/ (module tree)
  - illumio-ops.py
  - deploy/
  - data/, config/, vendor/, logs/
  - docs/Architecture.md (legacy, fully audited)
  - docs/fonts-vendoring.md (legacy, folded in)
  - commit 54f70a3
related_docs:
  - report-engine.md
  - siem-pipeline.md
  - i18n-contract.md
  - ../user-guide/settings-and-pce-cache.md
---

> **[English](overview.md)** | **[繁體中文](overview_zh.md)**
> 📍 [INDEX](../INDEX.md) › Architecture › Overview
> 🔍 Last verified **2026-05-15** against commit `54f70a3` — see frontmatter for sources

# Architecture Overview

illumio-ops is a Python application that connects to one or more Illumio Policy
Compute Engine (PCE) instances, caches their data locally in SQLite, analyses
it against a rules engine, and surfaces results through a Flask-based web GUI,
a Click CLI, scheduled reports, and an optional SIEM forwarding pipeline.

---

## High-level diagram

```text
┌──────────────────────────────────────────────────────────────────┐
│                          Illumio PCE                             │
│   REST API (HTTPS :8443 / :443)                                  │
│   Resources: workloads, labels, rulesets, events, traffic flows  │
└──────────────┬───────────────────────────────────────────────────┘
               │  requests (HTTP client)
               │  polling: events every 5 min, traffic every 10 min
               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         illumio-ops core                                    │
│                                                                             │
│   ┌──────────────┐   ┌──────────────┐   ┌────────────────┐                 │
│   │  pce_cache/  │◄──│    api/      │──►│   alerts/      │                 │
│   │  SQLite DB   │   │  PCE client  │   │  event-driven  │                 │
│   │  (optional)  │   │  + models    │   │  notifications │                 │
│   └──────┬───────┘   └──────────────┘   │  (mail/LINE/   │                 │
│          │                              │   webhook)     │                 │
│          │  read                        └────────────────┘                 │
│          ▼                                                                  │
│   ┌──────────────┐   ┌──────────────┐   ┌────────────────┐                 │
│   │   report/    │   │  scheduler/  │   │    events/     │                 │
│   │  rules engine│   │  APScheduler │   │  event catalog │                 │
│   │  + exporters │   │  thread      │   │  + dispatcher  │                 │
│   └──────┬───────┘   └──────────────┘   └────────────────┘                 │
│          │                                                                  │
│          │ output                                                           │
│          ▼                                                                  │
│   ┌──────────────┐   ┌──────────────┐   ┌────────────────┐                 │
│   │    gui/      │   │    cli/      │   │    siem/       │                 │
│   │  Flask app   │   │  Click cmds  │   │  formatters    │                 │
│   │  cheroot     │   │  + menus     │   │  + transports  │                 │
│   │  WSGI server │   │              │   │  (Splunk HEC,  │                 │
│   └──────┬───────┘   └──────┬───────┘   │   Syslog, etc) │                 │
│          │                  │           └───────┬────────┘                 │
└──────────┼──────────────────┼───────────────────┼──────────────────────────┘
           │                  │                   │
           ▼                  ▼                   ▼
      Browser user       Terminal user       SIEM platform
      (HTTP/HTTPS)       (interactive        (Splunk, QRadar,
                          or scripted)        Elastic, syslog)
```

**Event-driven alerts** — the `alerts/` module subscribes to the `events/`
event bus. When a polled PCE event or a threshold breach fires, alert plugins
deliver notifications asynchronously (email, LINE Notify, webhook) without
blocking the GUI or CLI.

---

## Module tour (src/)

### gui/

**13 Python files** — Flask application, route blueprints, and server helpers.

`src/gui/__init__.py` creates the Flask app, registers blueprints, and runs
the cheroot WSGI server (thread-pool, native TLS).  
`src/gui/routes/` contains 10 blueprints:

| File | Blueprint |
|---|---|
| `dashboard.py` | live dashboard (charts, story-mode panels) |
| `reports.py` | on-demand report generation & download |
| `rules.py` | security-rule browser |
| `events.py` | PCE event stream viewer |
| `config.py` | PCE profile + settings editor |
| `auth.py` | login / session management (flask-login + argon2) |
| `admin.py` | admin panel (log viewer, cache management) |
| `actions.py` | workload quarantine / unquarantine + accelerate |
| `rule_scheduler.py` | scheduled rule execution status |
| `__init__.py` | blueprint aggregation |

Security middleware: flask-wtf (CSRF), flask-talisman (CSP/HSTS),
flask-limiter (rate limiting), flask-login (session auth).

### cli/

**30 Python files** — Click-based command tree plus interactive menus.

Entry via `illumio-ops.py` dispatcher, which routes to Click or to legacy
argparse depending on `argv[1]`. Click top-level subcommands: `monitor`,
`gui`, `report`, `rule`, `workload`, `config`, `status`, `version`, `siem`,
`cache`, `alert`.

`src/cli/menus/` (11 files) — questionary-driven interactive TUI menus for
alert settings, bandwidth rules, event rules, traffic rules, rule scheduling,
system health, report schedules, and web GUI/TLS configuration.

### report/

**72 Python files** — analysis modules, rules engine, parsers, and exporters.
This is the largest module. See [Report Engine](report-engine.md) for internals.

Sub-structure:

| Sub-dir | Purpose |
|---|---|
| `analysis/` | 20+ analysis modules (mod01–mod15 + attack-posture, draft, ringfence, policy-usage) |
| `analysis/audit/` | Audit log analysis |
| `analysis/policy_usage/` | Policy usage analysis |
| `exporters/` | HTML, XLSX, CSV, chart rendering, CSS, i18n label helpers |
| `parsers/` | PCE API parser, CSV parser, validators |
| `rules/` | Rules engine (R01–R05: draft deny, override deny, visibility breach, boundary allowed, mismatch) |

Top-level files: `report_generator.py`, `rules_engine.py`, `dashboard_summaries.py`,
`snapshot_store.py`, `trend_store.py`, `audit_generator.py`,
`policy_usage_generator.py`, `ven_status_generator.py`, `section_guidance.py`,
`report_metadata.py`, `tz_utils.py`.

> PDF generation via ReportLab was removed (commit `92143a6`). Reports are now
> HTML + XLSX only.

### siem/

**19 Python files** — event forwarder with pluggable formatters and transports.
See [SIEM Pipeline](siem-pipeline.md) for full internals.

| Sub-dir / file | Purpose |
|---|---|
| `formatters/` | CEF, Syslog-CEF, Syslog-JSON, Splunk-HEC, Normalised-JSON |
| `transports/` | Splunk HEC, syslog (TCP/UDP), generic HTTP |
| `dispatcher.py` | dispatch loop (tick: `siem.dispatch_tick_seconds`, default 5 s) |
| `dlq.py` | dead-letter queue (SQLite-backed, per-destination depth cap) |
| `preview.py` | in-GUI format preview |
| `tester.py` | synthetic test event sender |
| `web.py` | GUI routes for SIEM destination management |

Destinations are stored in `config.json` (`siem.destinations[]`) using
`host` + `port` fields (migrated from legacy `endpoint` in `d350d3d`).

### pce_cache/

**15 Python files** — optional SQLite-backed local mirror of PCE event and
traffic data.

Key files: `schema.py` (table definitions), `models.py` (ORM-style models),
`ingestor_events.py` + `ingestor_traffic.py` (pollers), `aggregator.py`
(traffic aggregation), `reader.py` (query interface for report modules),
`retention.py` (row-level TTL enforcement), `watermark.py` (cursor tracking),
`rate_limiter.py` (PCE API rate cap, default 400 req/min), `lag_monitor.py`,
`backfill.py`, `subscriber.py`, `traffic_filter.py`, `web.py` (GUI route).

Cache is optional (`pce_cache.enabled: false` by default). When enabled,
events are polled every `events_poll_interval_seconds` (default 300 s) and
traffic every `traffic_poll_interval_seconds` (default 600 s).

See [Settings & PCE Cache](../user-guide/settings-and-pce-cache.md) for operator config.

### alerts/ + events/

**alerts/ — 5 Python files** (+ 3 templates):

| File | Purpose |
|---|---|
| `base.py` | base alert class |
| `plugins.py` | delivery plugins (email, LINE Notify, webhook) |
| `metadata.py` | alert rule metadata |
| `template_utils.py` | Jinja2 template helpers |
| `templates/` | `mail_wrapper.html.tmpl`, `line_digest.txt.tmpl`, `webhook_payload.json.tmpl` |

**events/ — 8 Python files** — event catalog, event bus, and dispatcher.
Defines the canonical list of PCE event types (`FULL_EVENT_CATALOG`,
`ACTION_EVENTS`, `SEVERITY_FILTER_EVENTS`, `DISCOVERY_EVENTS`) and handles
internal routing from the PCE poll loop to alert subscribers.

### scheduler/

**2 Python files** — APScheduler integration.

`jobs.py` registers timed jobs (report schedules, rule scheduler check,
cache polls) against an APScheduler `BackgroundScheduler`.
`__init__.py` initialises the scheduler.

APScheduler requires SQLAlchemy when `scheduler.persist=true` (job store
persistence across restarts).

### i18n/

**2 Python files** (+ JSON data directory) — runtime translation layer.
See [i18n Contract](i18n-contract.md) for the full contract.

`src/i18n/__init__.py` — translation lookup engine.  
`src/i18n/data/` — locale JSON dictionaries (`en.json`, `zh_TW.json`).

The GUI uses `{{ _('key') }}` in Jinja2 templates; the CLI and report
modules use `t('key')` helpers. All keys are centralised in the JSON
dictionaries — no inline string literals in templates.

### api/

**4 Python files** — PCE REST API client and domain models.

| File | Purpose |
|---|---|
| `__init__.py` | PCE client (requests-based, org-scoped) |
| + up to 3 domain-model files | Workload, Label, Ruleset, Event domain objects |

Fetches label definitions, workloads, rulesets, events, and traffic flows.
Results are cached in `pce_cache.sqlite` when the cache is enabled, or held
in-memory for single-request analysis.

See [REST API Reference](../reference/rest-api.md) for the internal HTTP API.

### settings/

**1 Python file** — backwards-compatibility shim.

`src/settings/__init__.py` re-exports symbols from `src/events/catalog`,
`src/cli/menus/*`, and `src/utils` so legacy importers (`from src.settings
import X`) continue to work without modification.

The actual configuration management lives in `src/config.py` (`ConfigManager`),
which reads/writes `config/config.json` and validates values with pydantic.

---

## Data flow

```text
PCE REST API
  │
  │  1. api/ client: GET /orgs/{org_id}/events, /traffic_flows, /workloads, ...
  │     (requests + orjson; retried with cachetools TTL for label lookups)
  ▼
pce_cache/ ingestors (when cache.enabled)
  │  2. pce_cache/ingestor_events.py  → stores events rows     → SQLite
  │     pce_cache/ingestor_traffic.py → stores traffic rows    → SQLite
  │     pce_cache/aggregator.py       → aggregates traffic     → SQLite
  │     pce_cache/watermark.py        → tracks poll cursor
  │     pce_cache/retention.py        → enforces TTL (events 90d, raw traffic 7d, agg 90d)
  ▼
report/ analysis (on demand or scheduled)
  │  3. reader.py reads from SQLite (cache path)
  │     OR api/ fetches live (no-cache path)
  │  4. rules_engine.py evaluates R01–R05 against policy objects
  │  5. analysis/mod*.py modules build section data
  │  6. exporters/ render HTML / XLSX / CSV
  ▼
  ├── gui/routes/reports.py   → browser download / inline view
  ├── gui/routes/dashboard.py → live dashboard panels
  ├── cli/ subcommands        → stdout / saved file
  └── siem/ dispatcher        → forwards events to SIEM destinations
        │
        ▼
      siem/formatters/ (CEF / Syslog-CEF / Syslog-JSON / HEC / NormJSON)
        │
        ▼
      siem/transports/ (Splunk HEC / syslog TCP-UDP / HTTP)
        │
        ▼
      SIEM platform
```

**Refresh cadence** (configurable in `config.json`):

| Data type | Default poll interval |
|---|---|
| PCE events | 300 s (5 min) |
| Traffic flows | 600 s (10 min) |
| SIEM dispatch tick | 5 s |
| Rule scheduler check | 300 s |

---

## Configuration

### config/ layout

```
config/
├── config.json             # main runtime config (operator-owned)
├── config.json.example     # template — copy and edit
├── alerts.json             # alert rules engine state (custom rules)
├── report_config.yaml      # report profile definitions
├── rule_schedules.json     # scheduled rule-run definitions (created by GUI)
└── tls/                    # TLS cert + key (created by GUI/CLI CSR workflow)
```

**config.json top-level sections:**

| Section | Purpose |
|---|---|
| `api` | PCE connection: `url`, `org_id`, `key`, `secret`, `verify_ssl` |
| `alerts` | Alert channel destinations (SMTP, LINE, webhook) |
| `web_gui` | Bind address/port, username, password hash, TLS, security settings |
| `rule_scheduler` | Enabled flag + check interval |
| `report_schedules` | List of scheduled report definitions |
| `pce_cache` | Cache enabled, `db_path`, retention days, poll intervals, rate limit |
| `siem` | Enabled, destinations list, DLQ depth, dispatch tick |

Multiple PCE profiles are managed via the GUI settings page (stored as
additional named objects alongside `api`). Switching the active profile
updates `config.json`.

### data/ layout

```
data/
└── pce_cache.sqlite    # SQLite cache DB (created when pce_cache.enabled)
```

Snapshots and trend data are stored within the SQLite database. No
other persistent artefacts are written to `data/` at runtime.

---

## Logging

illumio-ops uses **loguru** (`>=0.7,<0.8`) configured in `illumio-ops.py` or
the GUI startup path.

```
logs/
├── illumio_ops.log     # main application log (JSON-structured lines)
├── modules/            # placeholder directory; not currently written to
└── state.json          # last-known operational state (last poll timestamp, etc.)
```

Log rotation and retention are configured via loguru `rotation` / `retention`
parameters in the startup config block. JSON-structured lines allow ingestion
by filebeat or rsyslog — see `deploy/filebeat.illumio_ops.yml` and
`deploy/rsyslog.illumio_ops.conf` for reference configurations.

**Audited 2026-05-15**: `logs/modules/` exists on disk but no current `src/`
code writes to it; per-module file logging is **not currently wired**. Treat
the directory as a vestige until/unless per-module sinks are introduced.

---

## Vendor & static assets

### vendor/

```
vendor/
└── windows/
    └── nssm-2.24.zip   # NSSM binary for Windows service install
```

No Python package vendoring — runtime dependencies are installed via pip
from `requirements.txt` (or `requirements-offline.txt` for air-gapped deploys).

### src/static/

```
src/static/
├── css/     # compiled CSS (Tailwind-based utility classes)
├── js/      # frontend JS (Plotly, Alpine.js, chart init, quarantine modal, etc.)
└── fonts/   # vendored web fonts (see Appendix A below)
```

Font files are served directly by Flask's static file handler. No build step
is required to update fonts — replace the woff2 file and restart the server.

### Appendix A — Vendored Fonts

_(Folded in from `docs/fonts-vendoring.md`, commit `1d7f3c3`.)_

| File | License | Source | Size | Used by |
|---|---|---|---|---|
| `NotoSansCJKtc-Regular.otf` | OFL | github.com/notofonts/noto-cjk | 15.7 MB | CJK fallback (PDF outputs, GUI when CJK glyphs needed) |
| `Montserrat-latin.woff2` | OFL | github.com/JulietaUla/Montserrat | 37 KB | Legacy email/report inline styles (`reporter.py`, `report_generator.py`, `report_css.py`, `chart_renderer.py`) — removed from GUI CSS fallback chain; retained until report layer migrated |
| `SpaceGrotesk-VF.woff2` | OFL | github.com/floriankarsten/space-grotesk | 48 KB | GUI headings (post Track A redesign) |
| `Inter-VF.woff2` | OFL | @fontsource-variable/inter v5.2.8 (latin subset) | 48 KB | GUI body text; Report body |
| `JetBrainsMono-VF.woff2` | OFL | @fontsource-variable/jetbrains-mono v5.2.8 (latin subset) | 40 KB | Code blocks / table figures (`tnum`) |

All three active fonts are **variable fonts** (woff2 with `fvar` axis). Using
variable fonts avoids serving multiple static-weight files and keeps the total
font payload under 280 KB (the three active variable fonts total 136 KB).

**Sourcing notes:**
- `SpaceGrotesk-VF.woff2` — from `floriankarsten/space-grotesk` repo (`wght` axis 300–700).
- `Inter-VF.woff2` — latin-subset variable font from `@fontsource-variable/inter`; the full `InterVariable.woff2` from rsms/inter v4.0 is 340 KB (all scripts), so the latin subset is used instead.
- `JetBrainsMono-VF.woff2` — latin-subset from `@fontsource-variable/jetbrains-mono`; the upstream JetBrains release zip only includes static woff2 + variable ttf (no variable woff2), so fontsource is used.

**To update a font:**
1. Download the new variable woff2 from the source URL above.
2. Verify: `fontTools.ttLib.TTFont(...).flavor == 'woff2'` and `'fvar' in font`.
3. Replace the file in `src/static/fonts/`.
4. Update the size column in this table.
5. Restart the server — no build step needed.

---

## Process model

illumio-ops runs as a **single Python process**:

```
python illumio-ops.py --monitor-gui --interval 10
  │
  ├── Main thread: Flask app served by cheroot WSGI server
  │     cheroot thread pool (numthreads=10, configurable)
  │     HTTP:  cheroot plain TCP listener
  │     HTTPS: cheroot + BuiltinSSLAdapter (TLS, hardened cipher list)
  │
  ├── APScheduler BackgroundScheduler thread
  │     - pce_cache event poller (every 300 s)
  │     - pce_cache traffic poller (every 600 s)
  │     - SIEM dispatcher tick (every 5 s)
  │     - Rule scheduler check (every 300 s)
  │     - Scheduled report runner
  │     Job store: in-memory (default) or SQLAlchemy-backed (scheduler.persist=true)
  │
  └── Alert delivery threads (spawned per alert event, short-lived)
```

The CLI path (`illumio-ops report traffic`, etc.) runs in the main thread
without starting the web server or APScheduler — it is a single-shot
synchronous command.

**No gunicorn or uWSGI** — cheroot is the production WSGI server. The
`requirements.txt` `cheroot>=10.0,<12.0` pin is mandatory.

---

## Data flow & sensitive fields

_(Auditor / security cross-cut — see spec §1.)_

### What illumio-ops stores

| Data category | Storage | Retention | Contains PII? |
|---|---|---|---|
| PCE event records | `pce_cache.sqlite` | 90 days (default) | Usernames in audit events (PCE-originated) |
| Raw traffic flows | `pce_cache.sqlite` | 7 days (default) | Source/dest IP, port, workload name |
| Aggregated traffic | `pce_cache.sqlite` | 90 days (default) | Aggregated counts, no per-session IPs |
| PCE API credentials | `config/config.json` | Until rotated | API key + secret (plaintext in JSON) |
| GUI session credentials | `config/config.json` | Until changed | argon2-hashed password |
| Alert channel secrets | `config/config.json` | Until rotated | SMTP password, LINE token, webhook URL |
| Report outputs | filesystem (operator-chosen path) | Operator-managed | Workload names, IPs, usernames from PCE |
| Logs | `logs/illumio_ops.log` | Loguru rotation policy | API response excerpts, workload names |

### Key points for auditors

- **config.json is sensitive.** It contains plaintext PCE API credentials and
  alert channel secrets. Apply OS-level file permissions (`chmod 600`) and
  exclude it from version control.
- **pce_cache.sqlite** mirrors PCE event and traffic data. IP addresses and
  usernames from PCE audit events are stored. Apply filesystem ACLs
  appropriate to your data classification policy.
- **Retention defaults** (90 / 7 / 90 days) are configurable in
  `config.json` under `pce_cache.*_retention_days`.
- **No outbound telemetry** — illumio-ops does not phone home. The only
  outbound connections are to the configured PCE (`api.url`) and to
  SIEM destinations (`siem.destinations`).
- **TLS** — the GUI can run over HTTP (dev/internal) or HTTPS. For
  production, use the built-in CSR generation workflow (`illumio-ops config
  tls csr`, added in commit `86d550e`) to generate a signed cert and import
  it into cheroot's TLS adapter.

---

## Deployment topology

### Linux — systemd

Reference unit: `deploy/illumio-ops.service`.

```
[Service]
Type=simple
User=illumio-ops
Group=illumio-ops
WorkingDirectory=/opt/illumio-ops
ExecStart=/opt/illumio-ops/python/bin/python3 /opt/illumio-ops/illumio-ops.py \
          --monitor-gui --interval 10
Restart=always
RestartSec=10
```

The unit runs the bundled Python interpreter from `python/bin/python3`
(offline bundle layout). Adjust the path for a virtualenv-based install.

Log output goes to the systemd journal (`StandardOutput=journal`) as well as
to `logs/illumio_ops.log` via loguru.

### Windows — NSSM

Reference script: `deploy/install_service.ps1`.  
NSSM binary: `vendor/windows/nssm-2.24.zip`.

```powershell
.\install_service.ps1 -Action install
.\install_service.ps1 -Action install -NssmPath "C:\Tools\nssm.exe" -Interval 5
.\install_service.ps1 -Action uninstall
.\install_service.ps1 -Action status
```

Service name: `IllumioOps` / Display name: `Illumio PCE Ops`.
Runs as the system account by default; configure a service account as needed.

### Log shipping (optional)

Reference configurations in `deploy/`:

| File | Purpose |
|---|---|
| `filebeat.illumio_ops.yml` | Filebeat input config for log shipping |
| `rsyslog.illumio_ops.conf` | rsyslog module config for syslog relay |
| `logstash.illumio_ops.conf` | Logstash pipeline for structured log ingestion |
| `siem_destination.example.json` | Example SIEM destination object for `config.json` |

### Docker

**TODO:** No Docker compose file or Dockerfile was found in `deploy/` at
verification time. Docker support, if any, is undocumented.

### Network ports

| Port | Protocol | Purpose | Configurable |
|---|---|---|---|
| 5000 (default) | HTTP or HTTPS | Web GUI (cheroot) | `web_gui.port` in config.json |
| 8443 / 443 | HTTPS | Outbound to PCE | `api.url` in config.json |
| Destination-specific | TCP/UDP | Outbound SIEM forwarding | per `siem.destinations[]` |

---

## Related Docs

- [Report Engine](report-engine.md) — internal report pipeline (next task)
- [SIEM Pipeline](siem-pipeline.md) — internal SIEM forwarding pipeline
- [i18n Contract](i18n-contract.md) — runtime translation model
- [Settings & PCE Cache](../user-guide/settings-and-pce-cache.md) — operator-level cache config
