# Illumio PCE Monitor — Project Architecture & Code Guide

> **[English](Project_Architecture.md)** | **[繁體中文](Project_Architecture_zh.md)**

---

## 1. System Architecture Overview

```mermaid
graph TB
    subgraph Entry["Entry Points"]
        CLI["CLI Menu<br/>(main.py)"]
        DAEMON["Daemon Loop<br/>(main.py)"]
        GUI["Web GUI<br/>(gui.py)"]
    end

    subgraph Core["Core Engine"]
        CFG["ConfigManager<br/>(config.py)"]
        API["ApiClient<br/>(api_client.py)"]
        ANA["Analyzer<br/>(analyzer.py)"]
        REP["Reporter<br/>(reporter.py)"]
    end

    subgraph External["External"]
        PCE["Illumio PCE<br/>REST API v2"]
        SMTP_SVC["SMTP Server"]
        LINE_SVC["LINE API"]
        HOOK_SVC["Webhook Endpoint"]
    end

    CLI --> CFG
    DAEMON --> CFG
    GUI --> CFG
    CFG --> API
    API --> PCE
    CFG --> ANA
    ANA --> API
    ANA --> REP
    REP --> SMTP_SVC
    REP --> LINE_SVC
    REP --> HOOK_SVC
```

**Data Flow**: Entry Point → `ConfigManager` (loads rules/credentials) → `ApiClient` (queries PCE) → `Analyzer` (evaluates rules against returned data) → `Reporter` (dispatches alerts).

---

## 2. Directory Structure

```text
illumio_monitor/
├── illumio_monitor.py     # Entry point — imports and calls src.main.main()
├── config.json            # Runtime config (credentials, rules, alerts, settings)
├── state.json             # Persistent state (last_check timestamp, alert_history, processed_ids)
├── requirements.txt       # Python dependencies
│
├── src/
│   ├── __init__.py        # Package init, exports __version__
│   ├── main.py            # CLI argument parser (argparse), daemon loop, interactive menu
│   ├── api_client.py      # Illumio REST API client with retry and streaming
│   ├── analyzer.py        # Rule engine: flow matching, metric calculation, state management
│   ├── reporter.py        # Alert aggregation and multi-channel dispatch
│   ├── config.py          # Configuration loading, saving, rule CRUD, atomic writes
│   ├── gui.py             # Flask Web application (routes, JSON API endpoints)
│   ├── settings.py        # CLI interactive menus for rule/alert configuration
│   ├── i18n.py            # Internationalization dictionary (EN/ZH) and language switching
│   ├── utils.py           # Helpers: logging setup, ANSI colors, unit formatting, CJK width
│   ├── templates/         # Jinja2 HTML templates for Web GUI
│   └── static/            # CSS/JS frontend assets
│
├── docs/                  # Documentation (this file, user manual, API cookbook)
├── tests/                 # Unit tests (pytest)
├── logs/                  # Runtime log files (rotating, 10MB × 5 backups)
└── deploy/                # Deployment helpers (NSSM, systemd configs)
```

---

## 3. Module Deep Dive

### 3.1 `api_client.py` — REST API Client

**Responsibility**: All HTTP communication with the Illumio PCE.

| Method | API Endpoint | HTTP | Purpose |
|:---|:---|:---|:---|
| `check_health()` | `/api/v2/health` | GET | PCE health status |
| `fetch_events()` | `/orgs/{id}/events` | GET | Security audit events |
| `execute_traffic_query_stream()` | `/orgs/{id}/traffic_flows/async_queries` | POST→GET→GET | Async traffic flow query with polling |
| `get_labels()` | `/orgs/{id}/labels` | GET | List labels by key |
| `create_label()` | `/orgs/{id}/labels` | POST | Create new label |
| `get_workload()` | `/api/v2{href}` | GET | Fetch single workload |
| `update_workload_labels()` | `/api/v2{href}` | PUT | Update workload's label set |
| `search_workloads()` | `/orgs/{id}/workloads` | GET | Search workloads by params |

**Key Design Patterns**:
- **Retry with Exponential Backoff**: Automatically retries on `429` (rate limit), `502/503/504` (server errors) up to 3 attempts
- **Streaming Download**: Traffic query results (potentially gigabytes) are downloaded as gzip, decompressed in-memory, and yielded line-by-line via Python generators — O(1) memory consumption
- **No External Dependencies**: Uses only `urllib.request` (no `requests` library)

### 3.2 `analyzer.py` — Rule Engine

**Responsibility**: Evaluate API data against user-defined rules.

**Core Functions**:

| Function | Purpose |
|:---|:---|
| `run_analysis()` | Main orchestration: health check → events → traffic → save state |
| `check_flow_match()` | Evaluate a single traffic flow against a rule's filter criteria |
| `calculate_mbps()` | Hybrid bandwidth calculation (interval delta → lifetime fallback) |
| `calculate_volume_mb()` | Data volume calculation with same hybrid approach |
| `query_flows()` | Generic query endpoint used by Web GUI's Traffic Analyzer |
| `run_debug_mode()` | Interactive diagnostic showing raw rule evaluation results |
| `_check_cooldown()` | Prevent alert flooding via per-rule minimum re-alert intervals |

**State Management** (`state.json`):
- `last_check`: ISO timestamp of last successful check — used as anchor for event queries
- `history`: Rolling window of match counts per rule (pruned to 2 hours)
- `alert_history`: Per-rule last-alert timestamp for cooldown enforcement
- `processed_ids`: Dedup buffer (capped at 2000 entries)
- **Atomic Writes**: Uses `tempfile.mkstemp()` + `os.replace()` to prevent corruption on crash

### 3.3 `reporter.py` — Alert Dispatcher

**Responsibility**: Format and send alerts through configured channels.

**Alert Categories**: `health_alerts`, `event_alerts`, `traffic_alerts`, `metric_alerts`

**Output Formats**:
- **Email**: Rich HTML tables with color-coded severity badges and embedded flow snapshots
- **LINE**: Plain text summary (LINE API character limits)
- **Webhook**: Raw JSON payload (full structured data for SOAR ingestion)

### 3.4 `config.py` — Configuration Manager

**Responsibility**: Load, save, and validate `config.json`.

- **Deep Merge**: User config is merged over defaults — any missing fields are auto-populated
- **Atomic Save**: Writes to `.tmp` file first, then `os.replace()` for crash safety
- **Rule CRUD**: `add_or_update_rule()`, `remove_rules_by_index()`, `load_best_practices()`

### 3.5 `gui.py` — Flask Web GUI

**Responsibility**: Browser-based management interface.

**Architecture**: Flask backend exposing ~25 JSON API endpoints, consumed by a Vanilla JS frontend (`templates/index.html`).

**Key Endpoints**:

| Route | Method | Purpose |
|:---|:---|:---|
| `/api/status` | GET | Dashboard data (health, stats, rules) |
| `/api/rules` | GET/POST/DELETE | Rule CRUD |
| `/api/dashboard/top10` | POST | Traffic Analyzer (Top-10 by bandwidth/volume/connections) |
| `/api/quarantine/search` | POST | Workload search for quarantine |
| `/api/quarantine/apply` | POST | Apply quarantine label to workload |
| `/api/settings` | GET/PUT | Read/write application settings |

### 3.6 `i18n.py` — Internationalization

**Responsibility**: Provide translated strings for all UI text.

- Contains a ~800-entry dictionary mapping keys to `{"en": "...", "zh": "..."}` pairs
- `t(key, **kwargs)` function returns the string in the current language with variable substitution
- Language is set globally via `set_language("en"|"zh")`

---

## 4. Data Flow Diagram

```mermaid
sequenceDiagram
    participant D as Daemon/CLI
    participant C as ConfigManager
    participant A as ApiClient
    participant P as PCE
    participant E as Analyzer
    participant R as Reporter

    D->>C: Load config & rules
    D->>A: Initialize (credentials)
    D->>E: run_analysis()

    E->>A: check_health()
    A->>P: GET /api/v2/health
    P-->>A: 200 OK
    A-->>E: Status

    E->>A: fetch_events(last_check)
    A->>P: GET /orgs/{id}/events?timestamp[gte]=...
    P-->>A: Event list
    A-->>E: Events
    E->>E: Match events against event rules

    E->>A: execute_traffic_query_stream(start, end, pds)
    A->>P: POST /orgs/{id}/traffic_flows/async_queries
    P-->>A: 202 {href, status: "queued"}
    loop Poll until completed
        A->>P: GET /orgs/{id}/traffic_flows/async_queries/{uuid}
        P-->>A: {status: "completed"}
    end
    A->>P: GET .../download
    P-->>A: gzip stream
    A-->>E: yield flow records

    E->>E: Match flows against traffic/bandwidth/volume rules
    E->>R: Add triggered alerts
    E->>E: save_state()

    R->>R: Format alerts (HTML/text/JSON)
    R-->>D: Send via Email/LINE/Webhook
```

---

## 5. How to Modify This Project

### 5.1 Add a New Rule Type

1. **Define the rule schema** in `settings.py` — create a new `add_xxx_menu()` function
2. **Add matching logic** in `analyzer.py` → `run_analysis()` — handle the new type in the traffic loop
3. **Add GUI support** in `gui.py` — create a new API endpoint for the rule type
4. **Add i18n keys** in `i18n.py` for any new UI strings

### 5.2 Add a New Alert Channel

1. **Add config fields** in `config.py` → `_DEFAULT_CONFIG["alerts"]`
2. **Implement the sender** in `reporter.py` — create `_send_xxx()` method
3. **Register in dispatcher** in `reporter.py` → `send_alerts()` — add the new channel check
4. **Add GUI settings** in `gui.py` → `api_save_settings()` and frontend

### 5.3 Add a New API Endpoint

1. **Add the method** in `api_client.py` — follow the pattern of existing methods
2. **URL format**: Use `self.base_url` for org-scoped endpoints, `self.api_cfg['url']/api/v2` for global ones
3. **Error handling**: Return `(status, body)` tuple, let callers handle specific status codes
4. **Refer to** `docs/REST_APIs_25_2.txt` for endpoint schemas

### 5.4 Add a New i18n Language

1. Add the language code to every entry in `i18n.py`'s dictionary (alongside `"en"` and `"zh"`)
2. Add the language option in `gui.py` → settings endpoint
3. Update `config.py` defaults to include the new language code
