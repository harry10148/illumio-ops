# Active Tasks — illumio_ops

**As of:** 2026-04-19  
**Source:** Code Review (full project analysis) + Upgrade Roadmap

---

## CLI Audit / Hotfix (2026-04-19)

- [x] `Rules > Manage` legacy menu audited and fixed: prompt now explains `m <idx>` / `d <idx[,idx...]>`, `h/?` shows command help, modify rejects multi-index input, original rule is preserved until edit/save completes, and regression tests added for help/delete/modify/error flows.

## CLI + Wizard Bug Fixes (2026-04-19)

- [x] **Bug 1 — CLI subcommand routing**: `illumio_ops.py` `_CLICK_SUBCOMMANDS` was missing `rule`, `workload`, `config`; commands like `illumio-ops rule list` silently fell back to the interactive menu. Fixed by adding all three names. (`illumio_ops.py:26`)
- [x] **Bug 2 — Wizard silent exit on Enter key**: `safe_input()` in `src/utils.py:262` conflated empty Enter with "go back" for int fields (both returned `None` with action=`"back"`). Changed to action=`"empty"` for empty Enter. All int-field None-handlers in `add_traffic_menu` and `add_bandwidth_volume_menu` (`src/settings.py`) updated to check `get_last_input_action() == "empty"` before applying defaults, so pressing Enter accepts the default instead of silently aborting the wizard. 14 tests pass.

## CLI Full Review Follow-up (2026-04-19)

- [x] **Finding 1 — Report CLI surface mismatch**: click `report` now supports `traffic` / `audit` / `ven-status` / `policy-usage`, and legacy argparse `--report` path now supports `--report-type traffic|audit|ven_status|policy_usage`.
- [x] **Finding 2 — `workload list --limit` lacks lower-bound validation**: `--limit` now uses `click.IntRange(min=1)` so invalid values fail fast before any API call.
- [x] **Finding 3 — Rule Scheduler blank Enter silently exits**: `schedule_management_ui()` no longer treats empty input as back; blank Enter now refreshes the screen instead of exiting.
- [x] **Compatibility matrix**: added explicit regression coverage for entrypoint click/argparse detection, legacy `--report-type` dispatch by report kind, `--monitor-gui` / `--gui` dispatch, and click `report` subcommand argument mapping.

## Source IP Trust Review (2026-04-19)

- [x] Reviewed current source-IP trust path in Web GUI (`web_gui.allowed_ips`).
- [x] Fixed single-IP mismatch for IPv4-mapped IPv6 remotes and loopback equivalence in [src/gui.py](/mnt/d/OneDrive/RD/illumio_ops/src/gui.py).
- [x] Added regression coverage for exact-IP allowlist, mapped IPv6 remotes, and allowlist normalization in [tests/test_gui_security.py](/mnt/d/OneDrive/RD/illumio_ops/tests/test_gui_security.py).

## Repository Cleanup (2026-04-20)

- [x] Removed all remaining `upgrade/*` local branches.
- [x] Removed the remaining `upgrade/*` remote branch (`origin/upgrade/phase-11-charts-dashboard`).
- [x] Removed all `upgrade/*` worktrees and pruned stale worktree metadata; only the main worktree remains.

---

## Phase 13: PCE Cache + SIEM Forwarder 📋 PLANNED (2026-04-19)

Plan: [docs/superpowers/plans/2026-04-19-phase-13-pce-cache-and-siem.md](docs/superpowers/plans/2026-04-19-phase-13-pce-cache-and-siem.md) • Target tag: `v3.11.0-siem-cache` • Branch: `feature/phase-13-siem-cache`

- [x] **T1**: Branch + baseline (465 passed, branch `feature/phase-13-siem-cache` created, package skeleton scaffolded)
- [ ] **T2**: SQLAlchemy models + WAL schema (6 tables: events / traffic_raw / traffic_agg / watermarks / dispatch / dead_letter)
- [ ] **T3**: Global rate limiter (token bucket, 400/min default) + `ApiClient._request(rate_limit=...)` feature flag
- [ ] **T4**: Watermark store (per-source cursor with error recording)
- [ ] **T5**: Events ingestor (sync ≤ 10k, async via `Prefer: respond-async` beyond)
- [ ] **T6**: Traffic filter + deterministic sampler (`hash(src,dst,port)` for idempotent drops)
- [ ] **T7**: Traffic ingestor (async `/traffic_flows/async_queries`, 200k cap, filter+sample applied)
- [ ] **T8**: Traffic aggregator (daily rollup to `pce_traffic_flows_agg`, idempotent UPSERT)
- [ ] **T9**: Retention worker (per-table TTL purge)
- [ ] **T10**: Formatters — CEF + JSON Lines + RFC5424 syslog header wrapper
- [ ] **T11**: Transports — UDP / TCP / TCP+TLS / Splunk HEC (stdlib `socket`/`ssl` + `requests`)
- [ ] **T12**: Dispatcher + DLQ with exponential backoff (cap 1h) and quarantine after N retries
- [ ] **T13**: Config models (pydantic v2) + APScheduler job registration behind flags
- [ ] **T14**: CLI `illumio-ops siem test|status|replay|purge|dlq`
- [ ] **T15**: Flask blueprint `/api/siem/` — destinations CRUD + DLQ admin + UDP warning banner
- [ ] **T16**: Docs — `docs/PCE_Cache.md`, `docs/SIEM_Forwarder.md`, update `docs/SIEM_Integration.md`
- [ ] **T17**: E2E test + i18n audit + Status/Task updates + PR + tag

---

## Phase 14: Reports on PCE Cache 📋 PLANNED (2026-04-19)

Plan: [docs/superpowers/plans/2026-04-19-phase-14-reports-on-cache.md](docs/superpowers/plans/2026-04-19-phase-14-reports-on-cache.md) • Target tag: `v3.12.0-reports-cache` • Branch: `feature/phase-14-reports-cache`

- [ ] **T1**: Branch + baseline (≥ 470 passed post-Phase 13)
- [ ] **T2**: `CacheReader` facade with full/partial/miss coverage semantics
- [ ] **T3**: `AuditGenerator` cache-first + API fallback
- [ ] **T4**: `ReportGenerator` traffic cache-first + API fallback (raw + agg)
- [ ] **T5**: `BackfillRunner` + `illumio-ops cache backfill|status|retention` + GUI modal
- [ ] **T6**: HTML report "Data source" pill (cache / API / mixed) in both audit + traffic exporters
- [ ] **T7**: Docs (user manual section) + E2E + final validation + PR + tag

---

## Phase 15: Alerts on PCE Cache 📋 PLANNED (2026-04-19)

Plan: [docs/superpowers/plans/2026-04-19-phase-15-alerts-on-cache.md](docs/superpowers/plans/2026-04-19-phase-15-alerts-on-cache.md) • Target tag: `v3.13.0-alerts-cache` • Branch: `feature/phase-15-alerts-cache` (independent of Phase 14)

- [ ] **T1**: Branch + baseline
- [ ] **T2**: `IngestionCursor` additive table (per-consumer cursor with `(ingested_at, id)` tuple)
- [ ] **T3**: `CacheSubscriber` with persistent cursor
- [ ] **T4**: `Analyzer` event/flow paths read from subscriber when cache enabled
- [ ] **T5**: `EventPoller` adapter delegates to subscriber
- [ ] **T6**: 30s monitor tick when `pce_cache.enabled` (drops from `interval_minutes`)
- [ ] **T7**: Cache lag monitor — warns on stalled ingestor
- [ ] **T8**: Docs (architecture diagram update) + E2E + PR + tag

---

## Phase 12: Polish & Advanced ✅ DONE (v3.10.0-polish, 2026-04-19)

- [x] **T1**: Branch + baseline (406 passing)
- [x] **T2**: humanize sweep — Jinja filters, dashboard.js helper, 3 HTML exporter updates, 3 tests
- [x] **T3**: SIEM docs — `docs/SIEM_Integration.md` + 3 deploy configs + 4 tests
- [x] **T4**: GUI rule highlight — `/api/rules/<idx>/highlight` + `pygments.css` + 4 tests
- [x] **T5**: APScheduler persistence — `SchedulerSettings`, `SQLAlchemyJobStore`, `replace_existing=True` + 5 tests
- [x] **T6**: Shell completions — bash/zsh/fish in `scripts/completions/`; entrypoint updated
- [x] **T7**: 422 passed, 0 failed; i18n audit 0 findings; Status.md + Task.md updated
- [x] 422 passed, 1 skipped; i18n audit clean

---

## Phase 11: Charts + Dashboard ✅ DONE (v3.9.0-dashboard, 2026-04-19)

- [x] **T1**: Branch + baseline + `tests/test_phase11_chart_coverage.py` (20 failing tests)
- [x] **T2**: mod01/03/04 chart_specs (pie, bar by risk level)
- [x] **T3**: mod06/08/09 chart_specs (bar processes/users, pie managed/unmanaged, bar ports)
- [x] **T4**: mod11/12/13/14 chart_specs (bar apps, bar maturity dims, bar readiness, bar tiers)
- [x] **T5**: `/api/dashboard/chart/<chart_id>` Flask endpoint + 5 tests
- [x] **T6**: `illumio-ops rule edit <id>` interactive CLI + 5 tests
- [x] **T7**: `ReportSchedule.cron_expr` + `APScheduler.CronTrigger` + 9 cron tests
- [x] **T8**: i18n audit 0 findings; 406 passed; Status.md + Task.md updated
- [x] 406 passed, 1 skipped; i18n audit clean

---

## Phase 10: UX Quick Wins ✅ DONE (v3.8.0-ux, 2026-04-19)

- [x] **T1**: Branch + baseline + format contract freeze test (317 baseline)
- [x] **T2**: CSV demoted — `--format html` is new default; `gui_fmt_*` i18n keys added
- [x] **T3**: pdf/xlsx/all parity for AuditGenerator, VenStatusGenerator, PolicyUsageGenerator (20 new parity tests)
- [x] **T4**: Audit chart_specs — audit_mod00 (bar), audit_mod02 (bar), audit_mod03 (bar)
- [x] **T5**: VEN chart_specs — status_chart_spec (pie), os_chart_spec (bar)
- [x] **T6**: Policy Usage chart_specs — pu_mod02 (bar), pu_mod04 (pie)
- [x] **T7**: chart_spec coverage regression test — 15 tests for 5 modules
- [x] **T8**: CLI `illumio-ops rule list [--type X] [--enabled-only]` — 6 tests
- [x] **T9**: CLI `illumio-ops workload list [--env X] [--limit N] [--enforcement X]` — 3 tests
- [x] **T10**: rich.progress spinner on `_wait_for_async_query` — TTY-only, silent in daemon
- [x] 366 passed, 1 skipped, 1 pre-existing flaky (subprocess timeout)

---

## Phase 9: Architecture Refactor ✅ DONE (v3.7.0-refactor)

- [x] **A5**: `events/shadow.py` evaluated — retained as active GUI endpoint; 17 tests added
- [x] **Q3**: Canonical `extract_id()` in `src/href_utils.py`; duplicate copies removed
- [x] **A4**: `src/exceptions.py` typed hierarchy (7 classes); silent fallback sites audited
- [x] **Q1**: `Analyzer.run_analysis()` decomposed: 196→~20 lines orchestrating 5 private methods; 27 new tests
- [x] **A3** (residuals): `_InputState` + `_I18nState` singletons with Lock; `deque(maxlen=200)` ring buffer; `_registry` lock
- [x] **A2 + Q2**: `api_client.py` 2569→765 LOC facade; `src/api/` package: LabelResolver + AsyncJobManager + TrafficQueryBuilder; all 50+ public methods preserved
- [x] **A1**: `src/interfaces.py` typing.Protocol (IApiClient/IReporter/IEventStore); `Analyzer.__init__` type-annotated; 4 mock-free tests
- [x] 314 passed, 2 pre-existing PDF failures, 1 pre-existing subprocess timeout

---

## Phase 7: Logging → loguru ✅ DONE (v3.6.0-loguru merged)

- [x] `src/loguru_config.py` — `setup_loguru()`: rotating file + TTY console + optional JSON SIEM sink
- [x] `src/utils.py::setup_logger()` — delegates to loguru; signature preserved for 2 callers
- [x] `scripts/migrate_to_loguru.py` — codemod: 86 src/ files migrated (import + %s→{})
- [x] stdlib 3rd-party logs intercepted via `_StdLibInterceptHandler`
- [x] `src/config_models.py` — `LoggingSettings` (level/json_sink/rotation/retention)
- [x] `src/main.py` — reads `config.logging` at startup
- [x] `tests/conftest.py` — loguru↔caplog bridge (autouse fixture)
- [x] 15 new tests (9 loguru setup + contract + migration script); 266 passed, 3 pre-existing failures
- [x] `module_log.py` untouched (GUI ring-buffer, not logging infra)

---

## Phase 6: APScheduler 統一 ✅ DONE (v3.5.2-scheduler merged)

BackgroundScheduler + 3 jobs. RLock on all 5 ApiClient TTLCaches. SIGINT+SIGTERM handlers. Resolves A3 + T1.

---

## Phase 4: Web GUI Security ✅ DONE (v3.5.0-websec merged)

flask-wtf CSRF + flask-limiter rate limit + flask-talisman headers + flask-login + argon2id. Resolves S1/S4/S5/T1.

---

## Phase 5: Reports Excel/PDF/Charts ✅ DONE (v3.5.1-reports about to merge)

- [x] `chart_renderer.py` — plotly HTML (offline) + matplotlib PNG from same spec
- [x] `code_highlighter.py` — pygments JSON/YAML/bash
- [x] `xlsx_exporter.py` — openpyxl multi-sheet + embedded chart PNG
- [x] `pdf_exporter.py` — weasyprint HTML→PDF + CJK CSS (skips Windows)
- [x] chart_spec in mod02/05/07/10/15; pygments CSS in 4 HTML exporters
- [x] CLI + GUI format: html/csv/pdf/xlsx/all; `/api/reports/generate` allowlist
- [x] humanize in HTML summaries; scheduler format select expanded
- [x] +21 new tests (3 skipped for PDF on Windows); i18n 0 findings
---

## Phase 3: 設定驗證 ✅ DONE (2026-04-18)

- [x] **P3**: pydantic v2 + pydantic-settings integration
  - `src/config_models.py`: 12 BaseModel classes (ApiSettings, SmtpSettings, WebGuiSettings, ...)
  - `ConfigManager.load()` wired to pydantic validation; failures log per-field errors and fall back to merged data
  - `cm.models` new attribute exposes typed schema; `cm.config` dict access 100% backward-compatible (70+ call sites unchanged)
  - **Status.md D2 resolved** (config schema validation)
  - Top-level `extra='forbid'` catches config.json typos at startup
  - `src/cli/config.py`: `illumio-ops config validate / show` subcommands (isolated; registration deferred to Phase 1+3 integration)
  - Test count: baseline 130 → 147 (+17 new, 0 regressions)
  - i18n audit: 0 findings
  - Branch: `upgrade/phase-3-settings-pydantic` → tag `v3.4.3-settings`

---

## Phase 0: Dependency Baseline ✅ DONE (2026-04-18)

- [x] **P0**: Pin all roadmap packages
  - `requirements.txt`: 24 production packages pinned (flask + pandas + pyyaml + 21 new across Phase 1-7)
  - `requirements-dev.txt`: 8 dev-only packages (pytest/ruff/mypy/pyinstaller/responses/freezegun/pytest-cov/build)
  - `scripts/verify_deps.py`: import-test smoke script (handles Windows GTK3 absence for weasyprint)
  - `tests/test_dependency_baseline.py`: 3-test CI gate (verify script exists, all prod imports succeed, no unpinned lines)
  - All **130 tests pass** + 1 pre-existing skip; clean venv install verified
  - **Branch**: `upgrade/phase-0-deps`, to be merged + tagged `v3.4.0-deps`
  - Roadmap: [docs/superpowers/plans/2026-04-18-upgrade-roadmap.md](docs/superpowers/plans/2026-04-18-upgrade-roadmap.md)
  - Detailed plan: [docs/superpowers/plans/2026-04-18-phase-0-deps.md](docs/superpowers/plans/2026-04-18-phase-0-deps.md)
  - **Next**: Wave A — Phase 1 (CLI), Phase 2 (HTTP), Phase 3 (Settings) can run in parallel

---

## Phase 1: CLI UX 升級 ✅ DONE (2026-04-18)

- [x] **P1**: rich + questionary + click + humanize integration
  - `Colors`/`draw_panel`/`Spinner`/`safe_input` 底層改 rich/questionary，446 呼叫點無感升級
  - 新 `src/cli/` click subcommand：`monitor`/`gui`/`report`/`status`/`version`
  - `illumio_ops.py` 依 argv[1] 派送 click vs argparse，舊 flag 完整向後相容
  - 主選單狀態列加「Last activity: 3 minutes ago」（humanize）
  - Bash completion 腳本備好供 RPM 使用 (`scripts/illumio-ops-completion.bash`)
  - Test count: 130 → 150（新增 20）；i18n audit 持續 0 findings
  - **Branch**: `upgrade/phase-1-cli-rich` → squash merge + tag `v3.4.1-cli`
  - Detailed plan: [docs/superpowers/plans/2026-04-18-phase-1-cli-rich.md](docs/superpowers/plans/2026-04-18-phase-1-cli-rich.md)
  - **Next Wave A task**: Phase 2 (HTTP) ‖ Phase 3 (Settings) 已可並行

---

## Phase 1: Security Hardening ✅ DONE

- [x] **S1: Replace SHA256 with PBKDF2-HMAC-SHA256 (260k iterations, stdlib)**
  - `src/config.py` — new `hash_password()` / `verify_password()` with `pbkdf2:` prefix
  - Legacy SHA256 hashes upgraded automatically on next successful login
  - No new external dependency

- [x] **S2: Default credentials illumio/illumio**
  - `src/config.py` — first-run sets default password `illumio` (PBKDF2 hashed)
  - No `_initial_password` stored in config; users change password via Settings

- [x] **S3: SMTP password env var override**
  - `src/alerts/plugins.py` — `ILLUMIO_SMTP_PASSWORD` env var takes precedence over config

- [x] **S4: CSRF token — synchronizer token pattern**
  - `src/gui.py` — cookie removed; token injected into `<meta name="csrf-token">` in `index.html`
  - `src/static/js/utils.js` — `_csrfToken()` now reads from meta tag (no XSS-readable cookie)
  - Login response JSON now includes `csrf_token` for API clients / tests

- [x] **S5: Login rate limiting**
  - `src/gui.py` — 5 attempts per 60 seconds per IP; returns HTTP 429

---

---

## Phase 2: HTTP client 重構 ✅ DONE (2026-04-18)

- [x] **P2**: requests + orjson + cachetools migration
  - `_request()` 底層改 `requests.Session` + `urllib3.Retry`（429/502/503/504 自動退避）
  - Hot path `json.loads` 改 `orjson.loads`（async traffic 大型回應提速 2-3×）
  - label caches 全包 `TTLCache(ttl=900)` — **Status.md Q5 解決**
  - 50+ ApiClient public method 簽章完全不變
  - Test count: 130 → 145 (+15: contract/retry/ttl/orjson_compat tests)
  - Branch: `upgrade/phase-2-http-requests` → squash merge + tag `v3.4.2-http`

---

## Phase 2b: Architecture Improvements (Priority: MEDIUM)

- [x] **A4 (partial): Fix silent exception swallowing**
  - `src/api_client.py:2293` — async job poll parse failure now logs warning
  - `src/api_client.py:2537` — provision state check failure now logs debug
  - Remaining `except: pass` in analyzer.py are intentional (format fallback chains)

- [ ] **A1: Decompose `run_analysis()` method (196 lines)**
  - File: `src/analyzer.py:436-632`
  - Extract: `_fetch_and_analyze_traffic()`, `_analyze_events()`, `_dispatch_alerts()`

- [ ] **A2: Split `api_client.py` god class (2542 LOC)**
  - Consider extracting: `TrafficQueryBuilder`, `AsyncJobManager`, `LabelResolver`
  - Keep `ApiClient` as facade

- [ ] **A3: Resolve global mutable state**
  - `src/utils.py:21` — `_LAST_INPUT_ACTION`
  - `src/i18n.py:8,14` — `_current_lang`
  - `src/gui.py:184` — `_rs_log_history`
  - Wrap in thread-safe singletons or use `threading.local()`

- [ ] **A4: Standardize error handling**
  - Define exception hierarchy: `IllumioOpsError -> APIError, ConfigError, ReportError, AlertError`
  - Replace silent `except: pass` with logged exceptions
  - Key locations: `api_client.py:2293,2537`, `analyzer.py:823,975`, `gui.py:170,223,1097`

- [ ] **A5: Evaluate `events/shadow.py` for removal**
  - Appears to duplicate `events/matcher.py` logic
  - If deprecated, remove and update imports

---

## Phase 3: Test Coverage Expansion (Priority: MEDIUM)

- [ ] **T1: Add tests for report analysis modules (mod01-mod15)**
  - 15 modules with zero unit test coverage
  - Priority: mod12 (executive summary), mod13 (readiness), mod15 (lateral movement)

- [ ] **T2: Add tests for alert plugin dispatch**
  - File: `src/alerts/plugins.py`
  - Test EMAIL, LINE, WEBHOOK with mock transport

- [ ] **T3: Add tests for HTML/CSV exporters**
  - Files: `src/report/exporters/*.py`
  - Verify output structure, CSS injection safety, table rendering

- [ ] **T4: Add integration test for daemon loop**
  - File: `src/main.py:37-119`
  - Test monitor + report scheduler + rule scheduler interaction

- [ ] **T5: Add negative test cases for API client**
  - Network timeouts, malformed JSON, max-retry exhaustion
  - Partial async job responses, cache corruption

---

## Phase 4: Dependency & Config Hardening (Priority: LOW)

- [x] **D1: Pin dependency versions in requirements.txt**
  - `flask>=3.0,<4.0` (tested on 3.1.3)
  - pandas/pyyaml constraints added as comments (installed via OS packages on RHEL)

- [x] **D2: Add config schema validation on load** ✅ RESOLVED (Phase 3)
  - `src/config_models.py`: pydantic v2 ConfigSchema + 11 nested BaseModel classes
  - `ConfigManager.load()` validates via pydantic; logs per-field errors on failure
  - `cm.models` exposes typed access; `cm.config` dict patterns unchanged

- [x] **D3: Add label cache TTL to api_client** ✅ Done in Phase 2
  - All 5 caches now use `TTLCache(ttl=900)` — Status.md Q5 resolved

---

## Phase i18n: Full Localization Audit (Priority: HIGH — in progress)

Goal: EN UI is fully English, ZH UI is fully Chinese except whitelisted
professional terms, and logs/low-level events stay English.

Whitelisted English terms (keep in zh_TW): PCE, VEN, Workload, Enforcement,
Port, Service, Policy, Allow, Deny, Blocked, Potentially Blocked.

Baseline audit (2026-04-18): 1537 raw findings — see
`scripts/audit_i18n_report.md` generated by `scripts/audit_i18n_usage.py`.
Breakdown: A=560, B=183, C=179, D=55, E=126, F=376, G=58.

- [x] **i18n-P1: Build comprehensive audit script**
  - `scripts/audit_i18n_usage.py` rewritten with 7 categories (A–G)
  - Emits `scripts/audit_i18n_report.md` with per-line Markdown table
  - CI-friendly exit code (1 on any finding)

- [x] **i18n-P2: Report content layer** (2026-04-18)
  - 59 new `rpt_*` keys added to `report_i18n.STRINGS` (section intros,
    subnotes, VEN KPI labels, mod04 correlation-window strings)
  - 43 orphan `rpt_*` keys filled in `i18n_en.json` with real English
    (previously "Rpt Xxx Yyy" placeholders)
  - `_subnote()` refactored in `html_exporter.py` + `audit_html_exporter.py`
    from `(text)` → `(i18n_key, en_text)`, emits `data-i18n`
  - `_section()` refactored in `html_exporter.py` + `ven_html_exporter.py`
    to take `(intro_key, intro_en)` instead of hardcoded zh intro text
  - `ven_status_generator.py` KPIs changed from `{'label': zh_str, ...}` to
    `{'i18n_key': 'rpt_ven_kpi_*', ...}` resolved by the exporter
  - Glossary violations fixed in STRINGS: Port, Service, Workload, Enforcement
    now preserved in zh_TW (e.g. "連接埠" → "Port", "服務" → "Service")
  - Rule residue fixed: "Deny Rule 明細" → "Deny 規則明細", etc.
  - Audit script updated to skip `rpt_*` keys that exist in STRINGS when
    checking categories A (placeholder leak) and F (json placeholder)
  - Baseline 1537 findings → 962 findings (-575, ~37%)
  - All 121 tests pass

- [x] **i18n-P3: GUI templates + JS** (2026-04-18)
  - 19 new GUI i18n keys added (toast/progress/error strings for report
    generation flows) in `i18n_en.json` + `_ZH_EXPLICIT`
  - 30 existing placeholder EN values replaced with human-quality text
    (e.g., `gui_btn_view`: "Button View" → "View")
  - `index.html` mojibake / CJK fallback text cleaned (9 data-i18n initial
    texts + 7 mojibake comments) — applyI18n still overrides at runtime,
    but initial render is now readable English
  - `dashboard.js` refactored: 14 `|| '中文'` fallbacks → `|| 'English'`;
    8 hardcoded zh toast/progress templates wrapped in
    `(_translations['key'] || 'EN template').replace(...)`
  - `quarantine.js`, `rule-scheduler.js`, `settings.js` zh fallbacks → EN
  - `gui_lang_en` / `gui_lang_zh` left as native-language labels
    ("English" / "繁體中文") in both modes (standard UX)
  - Baseline (Phase 2 end) 962 → 834 (-128, category C down 122→38)
  - All 121 tests pass

- [x] **i18n-P4: GUI backend (Flask)** (2026-04-18)
  - 147 placeholder EN values in `i18n_en.json` filled with human-quality
    English (e.g., `gui_delete_confirm` → "Delete \"{filename}\"?",
    `gui_snap_title` → "Latest Traffic Report Summary")
  - 12 referenced-but-missing keys added to json + `_ZH_EXPLICIT`
    (`alert_desc`, `cli_generated`, `error_modifying`, `mail_subject`, etc.)
  - `module_log.py` `MODULES` dict refactored: hardcoded zh labels →
    English-default + companion `MODULE_I18N_KEYS` for the JS side; 5 keys
    added to i18n
  - `src/static/js/module-log.js` now renders `<option data-i18n="...">`
    so the module-log dropdown tracks language toggles
  - `gui.py` logger mojibake cleaned (6 corrupted log strings now English)
  - `analyzer.py` / `settings.py` zh comments translated
  - Audit script hardened:
    - `t\(` regex now requires non-identifier lookbehind (eliminated 144
      false positives from `.get("x")`, `.set("x")` matches)
    - Category A no longer flags keys where json value happens to equal
      humanize output (an explicit entry still counts as "not leaked")
  - Baseline (Phase 3 end) 834 → 259 (-575, categories A/F/G now 0)
  - All 121 tests pass
  - ~~**Deferred**: `reporter.py` alert email refactor~~ — completed
    2026-04-18 as Phase i18n-P8 (see below)

- [x] **i18n-P5: CLI + audit precision + glossary enforcement** (2026-04-18)
  - Core engine updates in `src/i18n.py`:
    - `_TOKEN_MAP_ZH` glossary whitelist now keeps Port/Service(s)/
      Workload(s)/Policy/Enforcement in English (was 連接埠/服務/工作負載/
      策略/強制執行 before)
    - `_PHRASE_OVERRIDES` regex table: `\bPort\b` → 連接埠 rule removed;
      Service/Workload/Policy/Enforcement stay English via regex
    - 26 `_ZH_EXPLICIT` entries updated to use whitelist-respecting zh
      (e.g., `gui_port: "連接埠"` → `"Port"`, `gui_all_services: "全部
      服務"` → `"全部 Services"`)
    - `rpt_filter_port`, `rpt_filter_ex_port`, `event_rule_create/update/
      delete`, `gui_rs_col_rule_type`, `gui_rs_legend_child` residues fixed
    - Missing `ven_generating`, `ven_saving`, `failed_login_detail`,
      `src_port_detail` added
  - Audit script precision pass (removed ~200 false-positives combined):
    - Category B no longer flags zh_value that came from an explicit
      `_ZH_EXPLICIT` override, or a humanize output that produced proper
      Chinese via `_TOKEN_MAP_ZH`, or where zh is deliberately same as EN
      for terms like TCP/URL/API Key
    - Category C gained `BILINGUAL_DATA_FILES` (`attack_posture.py`)
      and `BILINGUAL_DATA_LINES` whitelist for intentional bilingual data
      (email section headers, input parsers, native language labels, etc.)
    - Category C now checks the AST literal's full value AND the source-line
      range, so multi-line HTML/email f-strings match whitelist needles
    - Category D excludes rpt_* keys that live in `report_i18n.STRINGS`
      (the user-visible text never flows through `get_messages()` for those)
    - Category D residue-token list narrowed to `Rule / Detail / Generate /
      Loading / Search / Filter` — product-feature nouns (`Audit Report`,
      `Traffic Analysis`, `Policy Usage`, `Status`, `Events`) are no longer
      flagged as residue
    - Category E glossary regex switched from `\b` to ASCII-only
      `(?<![A-Za-z])term(?![A-Za-z])` because Python's `\b` treats CJK as
      word chars — "檢查Policy" now matches the Policy rule
  - `tests/test_gui_security.py` updated: `Policy` stays English in zh_TW
  - **Audit result: 0 findings across A/B/C/D/E/F/G**
  - Baseline (Phase 4 end) 259 → 0
  - All 121 tests pass

- [x] **i18n-P8: `reporter.py` alert email refactor** (2026-04-18)
  - Added 130 alert-layer i18n keys covering: 6 severity labels, 5 status
    labels, 10 event-type recommendations, 12 snapshot/column labels, 4
    section headings, 15 plain-text field labels, 26 verb labels (audit
    events), 14 resource category labels, 10 resource-field labels, 4
    change-table labels, 7 event-card extras, 4 section intro notes.
  - `Reporter._severity_label()` / `_status_label()` /
    `_event_recommendation()` now look up i18n keys instead of returning
    hardcoded zh.
  - `generate_pretty_snapshot_html()` — snapshot table column labels,
    empty-state message, process/user badges all resolved via `t()`.
  - `_render_event_detail_html()` — `_RESOURCE_LABELS`, `_VERB_STYLE`,
    `_STATUS_LABELS`, `_FIELD_LABELS`, diff-table column headers,
    overflow summary, "(empty)"/"(none)" sentinels, workload/resource/
    account/action/parser-notes/actor-source extras — all via `t()`.
  - `_build_line_message()` — LINE section headers, field prefixes,
    severity/warning labels, rule fallbacks, remaining-events note.
  - `_build_mail_html()` — summary tile labels, severity labels, the four
    section intro notes (health/event/traffic/metric), `條件` / `數值`
    column headers.
  - `_build_plain_text_report()` event-description field label now via
    `t()`.
  - 3 missing `health_time` / `health_status` / `health_details` keys
    added so the inline `default='時間'` fallbacks can be removed.
  - `src/reporter.py` now contains **0** CJK characters (was 164).
  - **Audit still clean (0 findings)**, all 127 tests still pass.

- [x] **i18n-P6: Lock logs/events to English-only** (2026-04-18)
  - New `tests/test_log_layer_english.py` — AST-walks every `.py` in `src/`
    and fails if any `logger.*()`, `raise SomeError(...)`, or `print()`
    inside `src/events/*.py` contains CJK in its static string argument
  - Handles f-string literal parts and `+`-concatenation chains
  - Skips legitimate bilingual data files (`i18n.py`, `report_i18n.py`,
    `attack_posture.py`) where zh is intentional template content

- [x] **i18n-P7: Glossary + regression tests + CI audit** (2026-04-18)
  - `_TOKEN_MAP_ZH` + `_PHRASE_OVERRIDES` glossary preservation landed in
    Phase 5 (Port/Service/Workload/Policy/Enforcement stay English)
  - Expanded `tests/test_i18n_quality.py` from 3 to 7 tests:
    - email-key placeholder sweep (EN + ZH)
    - dashboard localization regression
    - ``test_every_english_value_is_not_a_placeholder`` — full EN sweep
    - ``test_glossary_terms_stay_english_in_zh_tw`` — 11-term whitelist
      verified for every key whose EN contains the term
    - ``test_report_strings_have_both_en_and_zh`` — STRINGS completeness
    - ``test_language_native_labels_are_stable`` — language selector labels
      stay native in both modes
  - New `tests/test_i18n_audit.py` — CI gate that runs the full
    `scripts/audit_i18n_usage.py` via subprocess and fails on any finding
  - **Final state: all 127 tests pass, 0 audit findings across A–G**

---

## Phase 5: Documentation Updates

- [x] **DOC0: Full documentation refresh (2026-04-13)**
  - All 10 docs + 2 READMEs updated to v3.2.0
  - Default credentials → random first-login password flow
  - Security sections updated: PBKDF2, rate limiting, CSRF synchronizer token, SMTP env var
  - API Cookbook: removed hardcoded "illumio" passwords from code examples
  - Version alignment across all files

- [ ] **DOC1: Expand API_Cookbook with more scenarios**
  - Currently only covers health check, quarantine, traffic queries; add: rule enable/disable, label operations

- [ ] **DOC2: Add Security_Rules_Reference threshold tuning guide**
  - Document B/L series rule thresholds and how to customize via report_config.yaml

- [ ] **DOC3: Document rule scheduler state machine**
  - 3-layer draft protection system not explained anywhere

- [ ] **DOC4: Add individual report module descriptions**
  - 15 traffic analysis modules listed in README but not described

---

## Staged Changes Awaiting Commit

- [ ] Commit `scripts/generate_assessment_docx.js` (new Node.js docx generator)
- [ ] Commit deletion of `CLAUDE.md` (removed from repo root)

---

## Recently Completed (reference)

- [x] Merge `codex/policy-usage-traffic-updates` — policy usage report, attack posture analysis
- [x] Deterministic attack summary text + UI polish
- [x] Traffic query cache invalidation and policy usage port insights
- [x] Vendor-aligned event engine refactor
- [x] i18n rebuild and unification across reports, GUI, alerts
- [x] **Full project code review (2026-04-13)** — 77 source files analyzed
- [x] **Code review fixes (2026-04-13)** — Phase 1 Security (S1–S5) + A4 partial + D1 implemented; 116/116 tests passing
