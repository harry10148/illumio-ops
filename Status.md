# Project Status — illumio_ops

**As of:** 2026-04-18  
**Version:** Wave A + Wave B complete (v3.5.0-websec + v3.5.1-reports + v3.5.2-scheduler)  
**Branch:** main  
**Phase:** 4/5/6 of 9 complete (Phase 7 Logging + Phase 9 Refactor remain)  
**Code Review Date:** 2026-04-13  
**i18n Overhaul:** 2026-04-18 — see Task.md i18n-P1..P7 (all done)

---

## Phase 6 Complete (v3.5.2-scheduler, merged)

APScheduler daemon unification. BackgroundScheduler + 3 jobs (monitor/report/rule). RLock on all 5 ApiClient TTLCaches. SIGINT+SIGTERM handlers for graceful shutdown. Resolves A3 + T1.

## Phase 4 Complete (v3.5.0-websec, merged)

Web GUI security: flask-wtf CSRF + flask-limiter rate limit + flask-talisman headers + flask-login + argon2id password. Permissions-Policy restored. 429 JSON errorhandler. Resolves S1/S4/S5/T1.

## Phase 5 Complete (v3.5.1-reports, about to merge)

Reports Excel/PDF/Charts:
- `chart_renderer.py` dual-engine (plotly HTML offline + matplotlib PNG for PDF/Excel)
- `xlsx_exporter.py` multi-sheet + embedded PNG
- `pdf_exporter.py` weasyprint HTML→PDF + CJK CSS
- `code_highlighter.py` pygments JSON/YAML/bash
- 5 analysis modules produce chart_spec (mod02 pie / mod05 bar / mod07 heatmap / mod10 line / mod15 network)
- CLI/GUI format options extended: html/csv/pdf/xlsx/all
- humanize in HTML summaries
- `/api/reports/generate` format allowlist (security hardening)
- Test count: +21 (231 after Wave B integration), 0 regressions, i18n audit 0 findings

---


## Phase 3 Complete (2026-04-18)

Phase 3 — pydantic v2 settings validation — merged into `upgrade/phase-3-settings-pydantic`.

| Task | Status |
|---|---|
| `src/config_models.py` — 12 BaseModel classes | ✅ |
| `ConfigManager.load()` pydantic validation | ✅ |
| `cm.models` typed access attribute | ✅ |
| 70+ `cm.config[...]` call sites preserved (backward-compat tests) | ✅ |
| `src/cli/config.py` — `validate` + `show` subcommands (isolated) | ✅ |
| Test count: baseline 130 → 147 (+17 new, 0 regressions) | ✅ |
| i18n audit: 0 findings | ✅ |
| Code Review D2 (config schema validation) | ✅ **RESOLVED** |

---

## What This Is

**Illumio PCE Ops** — agentless Python 3.8+ monitoring and automation platform for Illumio Core PCE via REST API.  
Entry point: `python illumio_ops.py` -> `src/main.py`

**Execution modes:**
- `python illumio_ops.py` — interactive CLI menu
- `--monitor` — headless daemon (single-threaded event loop)
- `--gui` — Flask web GUI (mandatory login: illumio/illumio)
- `--monitor-gui` — daemon + web GUI combined

---

## Architecture Overview

```
illumio_ops.py              Entry point (argparse -> src/main.py)
src/                        77 Python files, ~19,100 lines
  main.py (870 LOC)         CLI menus, daemon loop, signal handling
  api_client.py (2542 LOC)  PCE REST API (async jobs, native filters, O(1) streaming)
  analyzer.py (1087 LOC)    Traffic/event analysis engine (run_analysis 196-line method)
  reporter.py (1342 LOC)    Multi-channel alert dispatch (SMTP, LINE, Webhook)
  config.py (400 LOC)       ConfigManager (config/config.json, deep merge, defaults)
  settings.py (1938 LOC)    Interactive CLI/GUI settings menus
  gui.py (2662 LOC)         Flask web application (SPA, dashboard, rule mgmt)
  i18n.py (1403 LOC)        i18n engine (en/zh-TW, ~1400+ string keys)
  utils.py (408 LOC)        Colors, safe_input, encoding helpers
  module_log.py (106 LOC)   Per-module ring-buffer logging
  state_store.py (80 LOC)   Persistent JSON state (atomic write + file locking)
  rule_scheduler.py (246)   Auto enable/disable PCE rules (3-layer draft protection)
  rule_scheduler_cli.py (676) Web/CLI interfaces for rule scheduler
  report_scheduler.py (496) Cron-style scheduled report delivery
  events/                   Event processing pipeline
    catalog.py (297)          Vendor-aligned event taxonomy
    matcher.py (84)           Nested field rule matching
    normalizer.py (343)       Event normalization + dedup
    poller.py (110)           PCE event polling with watermark
    shadow.py (87)            Legacy rule matching (candidate for removal)
    stats.py (175)            Event statistics tracking
    throttle.py (148)         Alert throttle with suppression count
  report/                   Report generation subsystem
    report_generator.py (547)   15-module traffic report orchestrator
    audit_generator.py (695)    4-module audit report with DataFrame pipeline
    policy_usage_generator (478) Policy usage hit/miss analysis
    ven_status_generator (240)   VEN inventory report
    rules_engine.py (1058)       Security Findings engine (B/L series rules)
    dashboard_summaries.py (118) GUI dashboard summary builders
    report_metadata.py (75)      Report metadata attachment
    tz_utils.py (60)             Timezone utilities
    analysis/                    Per-module analysis (15 modules)
      mod01_traffic_overview .. mod15_lateral_movement
      attack_posture.py (223)    Attack posture ranking + recommendations
    exporters/                   Output formatters
      html_exporter.py (804)     Traffic report HTML
      audit_html_exporter.py (516) Audit report HTML
      policy_usage_html_exporter.py (337) Policy usage HTML
      ven_html_exporter.py (172) VEN report HTML
      csv_exporter.py (85)       Raw CSV export
      report_css.py (234)        Shared CSS
      report_i18n.py (511)       Report-specific i18n
      table_renderer.py (75)     HTML table builder
  alerts/                   Alert output plugins
    base.py (36)              AlertPlugin ABC
    plugins.py (132)          EMAIL, LINE, WEBHOOK implementations
    metadata.py (103)         Plugin config metadata
    template_utils.py (16)    Alert template helpers
  templates/                Flask HTML templates (2 files)
  static/                   CSS + JS assets
scripts/
  generate_assessment_docx.js (228 LOC)  Node.js branded .docx generator
  audit_i18n_usage.py         i18n key audit script
  generate_alert_mail_samples.py  Alert email sample generator
tests/                      19 test files, pytest suite
config/                     config.json.example, report_config.yaml
docs/                       EN + ZH_TW documentation (10 files)
deploy/                     systemd (Ubuntu/RHEL) + NSSM (Windows) service configs
```

---

## Code Review Summary (2026-04-13)

### Codebase Metrics

| Metric | Value |
|---|---|
| Python source files | 77 |
| Total Python LOC (src/) | ~19,100 |
| Test files | 19 |
| i18n string keys | ~1,400+ |
| Report analysis modules | 15 (mod01-mod15) |
| Security rules (B/L series) | ~19 |
| Documentation files | 10 (EN + ZH_TW) |

### Security Findings

| ID | Severity | Issue | Location |
|---|---|---|---|
| S1 | ✅ **RESOLVED** | argon2id via argon2-cffi; PBKDF2 silent upgrade on login | Phase 4 |
| S2 | **HIGH** | Hardcoded default password fallback ("illumio") | `gui.py:406` |
| S3 | **HIGH** | SMTP password stored plaintext in config.json | `config.py:25`, `alerts/plugins.py:45` |
| S4 | ✅ **RESOLVED** | flask-wtf CSRFProtect; token via X-CSRF-Token header | Phase 4 |
| S5 | ✅ **RESOLVED** | flask-limiter 5/minute on /api/login | Phase 4 |
| S6 | **MEDIUM** | SSL verification disableable via config | `api_client.py:140-144` |
| S7 | **LOW** | Silent exception swallowing in critical paths | `api_client.py`, `analyzer.py`, `gui.py` |

### Architecture Issues

| ID | Severity | Issue | Location |
|---|---|---|---|
| A1 | **MEDIUM** | Tight coupling (Analyzer->ApiClient->Reporter->Events) | Core modules |
| A2 | **MEDIUM** | Global mutable state in multiple modules | `utils.py:21`, `i18n.py:8`, `gui.py:184`, `module_log.py:28` |
| A3 | ✅ **RESOLVED** | Daemon loop single-threaded — replaced with APScheduler BackgroundScheduler (Phase 6) | `src/scheduler/` |
| A4 | **MEDIUM** | Inconsistent error handling (return empty vs raise vs pass) | Across codebase |
| A5 | **LOW** | `events/shadow.py` appears to duplicate matcher.py logic | `events/shadow.py` |

### Code Quality Issues

| ID | Severity | Issue | Location |
|---|---|---|---|
| Q1 | **MEDIUM** | `run_analysis()` is 196 lines — needs decomposition | `analyzer.py:436-632` |
| Q2 | **MEDIUM** | `api_client.py` is 2542 LOC with 50+ methods — god class | `api_client.py` |
| Q3 | **LOW** | Duplicate `extract_id()` in analyzer and rule_scheduler | `analyzer.py`, `rule_scheduler.py` |
| Q4 | **LOW** | Inconsistent naming (tz_str vs timezone_str vs _tz_str) | Across codebase |
| Q5 | ✅ **FIXED** | Label cache now uses TTLCache(ttl=900) — stale data resolved | `api_client.py` — Phase 2 |

### Test Coverage Assessment

| Area | Coverage | Assessment |
|---|---|---|
| api_client.py | Excellent | 11 tests: native filters, async jobs, retry, caching |
| analyzer.py | Good | 6 tests: flow matching, threshold, cooldown |
| events/* | Excellent | Normalization, rule matching, watermark, throttle |
| gui.py (security) | Excellent | Login, IP allowlist, CSRF, password hashing |
| audit_generator.py | Excellent | DataFrame pipeline, enrichment, metadata |
| attack_posture.py | Good | Ranking, schema validation, determinism |
| i18n.py | Good | Placeholder validation, EN/ZH_TW completeness |
| report modules (mod01-15) | **None** | No unit tests for individual analysis modules |
| alerts/plugins.py | **None** | No tests for EMAIL/LINE/WEBHOOK dispatch |
| rule_scheduler_cli.py | **None** | No tests for scheduler web/CLI interface |
| settings.py | **None** | No tests for interactive configuration |
| HTML/CSV exporters | **None** | No tests for report formatting |
| Overall estimate | ~60-70% | Strong core coverage; significant gaps in report/alert modules |

### Concurrency Issues

| ID | Issue | Location |
|---|---|---|
| T1 | ✅ **RESOLVED** | `_login_attempts` / `_LOGIN_ATTEMPTS` removed; flask-limiter handles it | Phase 4 |
| T2 | Module-level globals (`_current_lang`, `_registry`) not thread-safe | `i18n.py`, `module_log.py` |
| T3 | ✅ **RESOLVED** | Daemon loop blocking — APScheduler ThreadPoolExecutor (Phase 6) | `src/scheduler/` |

### Documentation Status

| Document | Status | Accuracy |
|---|---|---|
| README.md (EN) | Good | Current (v3.1.0) |
| README_zh.md (ZH_TW) | Good | Mirrors EN |
| User_Manual (EN/ZH) | Good | Installation + execution modes |
| Project_Architecture (EN/ZH) | Good | Mermaid diagrams, module guide |
| Security_Rules_Reference (EN/ZH) | Fair | Rule names listed; no threshold tuning docs |
| API_Cookbook (EN/ZH) | Fair | Only 2 scenarios; needs expansion |

### Dependency Status (Phase 0 — 2026-04-18)

**Production** (pinned in `requirements.txt`, bundled into future RPM):

| Package | Phase | Pinned? |
|---|---|---|
| flask | existing | ✓ >=3.0,<4.0 |
| pandas | existing (**mandatory** — 41 files, 338 DataFrame ops) | ✓ >=2.0,<3.0 |
| pyyaml | existing (**mandatory** — report_config.yaml) | ✓ >=6.0,<7.0 |
| rich, questionary, click, humanize | Phase 1 (CLI UX) | ✓ |
| requests, orjson, cachetools | Phase 2 (HTTP + cache) | ✓ **used** |
| pydantic, pydantic-settings | Phase 3 (Settings) | ✓ |
| flask-wtf, flask-limiter, flask-talisman, flask-login, argon2-cffi | Phase 4 (Web security) | ✓ **used** |
| openpyxl, weasyprint, matplotlib, plotly, pygments | Phase 5 (Reports) | ✓ |
| APScheduler | Phase 6 (Scheduler) | ✓ **used** |
| loguru | Phase 7 (Logging) | ✓ |

**Dev-only** (`requirements-dev.txt`, NOT bundled):
pytest, pytest-cov, responses, freezegun, ruff, mypy, build, pyinstaller

**CI gate**: `tests/test_dependency_baseline.py` runs `scripts/verify_deps.py` + enforces pin discipline (3 tests, all passing).

---

## Strengths

1. **Zero-dependency CLI core** — stdlib-only for daemon/CLI; optional deps for GUI/reports
2. **Full i18n coverage** — EN + ZH_TW across CLI, GUI, reports, and alerts (~1400+ keys)
3. **Secure deployment** — systemd hardening (`ProtectSystem=strict`, `NoNewPrivileges=true`)
4. **Comprehensive event pipeline** — catalog, normalization, dedup, throttle, watermark persistence
5. **Strong API client** — async job management, native filter resolution, retry with backoff
6. **Multi-platform deployment** — Linux systemd (Ubuntu/RHEL) + Windows NSSM

## Key Risks

1. ~~Password security (SHA256 → should be bcrypt/argon2)~~ **Resolved Phase 4 — argon2id**
2. No dependency version pinning — production drift risk
3. Single-threaded daemon — blocking risk under load
4. God class pattern in api_client.py (2542 LOC)
5. Report module analysis (mod01-15) has zero test coverage
