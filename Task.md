# Active Tasks — illumio_ops

**As of:** 2026-04-23  
**Source:** Code Review (full project analysis) + Upgrade Roadmap

---

## Stability Code Review Follow-up (2026-04-22)

- [x] Regression baseline re-check: `TMPDIR=/tmp TEMP=/tmp TMP=/tmp pytest -q -s` → `523 passed, 1 skipped`.
- [ ] **P1 — Wire SIEM runtime pipeline end-to-end**: runtime path currently lacks automatic enqueue on ingest and scheduler `run_siem_dispatch` consumer execution.
- [ ] **P1 — Prevent SIEM `pending` queue starvation**: when payload build fails (`_build_payload` returns `None`), mark dispatch rows as failed/quarantined (or retry with bounded backoff) instead of leaving them forever pending.
- [ ] **P2 — Fix `cron_expr` timezone drift**: `ReportScheduler.should_run()` currently evaluates cron with `timezone="UTC"` regardless of schedule timezone.
- [ ] **P2 — Remove silent scheduler init failure**: `build_scheduler()` currently swallows cache/SIEM registration exceptions (`except Exception: pass`), which can disable jobs without visibility.
- [x] **P0 — SIEM Preview positioning (compat mode)**: keep existing SIEM deployments runnable, add startup/runtime preview warnings, and mark SIEM docs as Preview until P1 runtime gaps are closed.

---

## i18n System Review Follow-up (2026-04-22)

- [x] Verified current i18n gate still passes: `python scripts/audit_i18n_usage.py` → 0 findings.
- [x] **P1a — Eliminate silent JS fallback literals**: replaced `_translations[key] || 'English...'` with strict `_t(key)` across `src/static/js/*.js` (missing keys now surface as `[MISSING:key]`).
- [x] **P1b — Add CI guard for fallback literals**: `scripts/audit_i18n_usage.py` now includes Category `H` to fail on `_translations[...] || '...'` patterns in JS/HTML.
- [x] Validation after P1a/P1b: `node --check` on modified JS files, `python scripts/audit_i18n_usage.py` (`A–H = 0`), and `TMPDIR=/tmp TEMP=/tmp TMP=/tmp pytest -q --basetemp=/tmp/pytest-illumio tests/test_i18n_audit.py tests/test_i18n_quality.py tests/test_gui_security.py` (`42 passed`).
- [x] **P1c — Eliminate remaining hardcoded UI literals**: migrated remaining JS-generated/template plain-English text nodes to translation keys (`data-i18n` / `_t(...)`), including dashboard/query widget residuals, report-generation source selector labels, apply/query actions, throttle labels, skip-link text, and floating quarantine action text.
- [x] **P1 — Introduce strict i18n mode for UI surface**: `src/i18n.py` now marks missing tracked keys with `[MISSING:key]` (does not silently fall back), covering Web UI/CLI/report/alert key prefixes; dynamic `event_label_*`/`cat_*` remain fallback-safe.
- [x] **P2 — Replace heuristic zh generation with explicit source-of-truth table**: added `src/i18n_zh_TW.json` (1583 keys) and wired `src/i18n.py` to prefer explicit zh values.
- [x] **P2 — Strengthen key extraction coverage**: audit added Category `I` for tracked EN↔zh parity and now treats `[MISSING:key]` as failure.
- [x] Cross-surface verification (Web UI/CLI/report/message alert paths): `TMPDIR=/tmp TEMP=/tmp TMP=/tmp pytest -q --basetemp=/tmp/pytest-illumio tests/test_i18n_audit.py tests/test_i18n_quality.py tests/test_gui_security.py tests/test_report_generator.py tests/test_policy_usage_report.py tests/test_audit.py tests/test_cli_report_commands.py tests/test_main_menu.py tests/test_event_monitoring.py` (`71 passed`).
- [x] **P1c-2 — Web UI hardcoded literal cleanup (high-risk JS paths)**: migrated remaining action/event/module-log/quarantine/rule-scheduler/settings/dashboard runtime messages to `_t(...)`, removed translation fallback patterns from `events.js`/`quarantine.js`, and added 83 new explicit GUI keys to `i18n_en.json` + `i18n_zh_TW.json`.
- [x] Re-verified after P1c-2: `node --check` on updated JS modules + `python scripts/audit_i18n_usage.py` (`A–I = 0`) + cross-surface regression (`71 passed`).
- [x] **P1c-3 — dashboard snapshot/report-data label normalization**: dashboard snapshot readers now normalize payload aliases (`Port`, `Flow Count`, `Bytes Total`, `Src IP`, `Dst IP` + snake_case variants) in both `dashboard.js` and `dashboard_v2.js`, and policy-usage summary labels are key-based.
- [x] **P1c-4 — dashboard query widget residual literals**: query table headers/tooltips (`First/Last Seen`, `Source`, `Destination`, `Service`, `Actions`, edit aria-label/title), PD prefix, and draft badge labels are now key-based in `dashboard.js`.
- [x] **P1d — include `_t(...)` in i18n key discovery/audit**: `src/i18n.py::_discover_keys()` and `scripts/audit_i18n_usage.py` now scan `_t(...)`, preventing false-green audits when keys are used only in runtime JS helpers.

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

## Phase 13: PCE Cache + SIEM Forwarder ✅ DONE (v3.11.0-siem-cache, 2026-04-20)

Plan: [docs/superpowers/plans/2026-04-19-phase-13-pce-cache-and-siem.md](docs/superpowers/plans/2026-04-19-phase-13-pce-cache-and-siem.md) • Target tag: `v3.11.0-siem-cache` • Branch: `feature/phase-13-siem-cache`

- [x] **T1**: Branch + baseline (465 passed, branch `feature/phase-13-siem-cache` created, package skeleton scaffolded)
- [x] **T2**: SQLAlchemy models + WAL schema (6 tables: events / traffic_raw / traffic_agg / watermarks / dispatch / dead_letter)
- [x] **T3**: Global rate limiter (token bucket, 400/min default) + `ApiClient._request(rate_limit=...)` feature flag
- [x] **T4**: Watermark store (per-source cursor with error recording)
- [x] **T5**: Events ingestor (sync ≤ 10k, async via `Prefer: respond-async` beyond)
- [x] **T6**: Traffic filter + deterministic sampler (`hash(src,dst,port)` for idempotent drops)
- [x] **T7**: Traffic ingestor (async `/traffic_flows/async_queries`, 200k cap, filter+sample applied)
- [x] **T8**: Traffic aggregator (daily rollup to `pce_traffic_flows_agg`, idempotent UPSERT)
- [x] **T9**: Retention worker (per-table TTL purge)
- [x] **T10**: Formatters — CEF + JSON Lines + RFC5424 syslog header wrapper (3 test files, 9 tests, 499 total pass)
- [x] **T11**: Transports — UDP / TCP / TCP+TLS / Splunk HEC (stdlib `socket`/`ssl` + `requests`) — 6 tests, 505 total pass
- [x] **T12**: Dispatcher + DLQ with exponential backoff (cap 1h) and quarantine after N retries
- [x] **T13**: Config models (pydantic v2) + APScheduler job registration behind flags
- [x] **T14**: CLI `illumio-ops siem test|status|replay|purge|dlq` — `src/cli/siem.py`, registered in root.py + illumio_ops.py, i18n EN+ZH, 4 tests, 518 total pass
- [x] **T15**: Flask blueprint `/api/siem/` — destinations CRUD + DLQ admin + UDP warning banner
- [x] **T16**: Docs — `docs/PCE_Cache.md`, `docs/SIEM_Forwarder.md`, update `docs/SIEM_Integration.md`
- [x] **T17**: E2E test (523 passed) + i18n audit (0 findings) + Status/Task updates + PR + tag

---

## Phase 14: Reports on PCE Cache ✅ DONE (2026-04-24)

Plan: [docs/superpowers/plans/2026-04-19-phase-14-reports-on-cache.md](docs/superpowers/plans/2026-04-19-phase-14-reports-on-cache.md) • Target tag: `v3.12.0-reports-cache` • Branch: `feature/phase-14-reports-cache`

- [x] **T1**: Branch + baseline (≥ 470 passed post-Phase 13)
- [x] **T2**: `CacheReader` facade with full/partial/miss coverage semantics
- [x] **T3**: `AuditGenerator` cache-first + API fallback
- [x] **T4**: `ReportGenerator` traffic cache-first + API fallback (raw + agg)
- [x] **T5**: `BackfillRunner` + `illumio-ops cache backfill|status|retention` + GUI modal
- [x] **T6**: HTML report "Data source" pill (cache / API / mixed) in both audit + traffic exporters
- [x] **T7**: Docs (user manual section) + E2E + final validation + PR + tag

---

## Phase 15: Alerts on PCE Cache ✅ DONE (v3.13.0-alerts-cache, 2026-04-24)

Plan: [docs/superpowers/plans/2026-04-19-phase-15-alerts-on-cache.md](docs/superpowers/plans/2026-04-19-phase-15-alerts-on-cache.md) • Target tag: `v3.13.0-alerts-cache` • Branch: `feature/phase-15-alerts-cache` (independent of Phase 14)

- [x] **T1**: Branch + baseline
- [x] **T2**: `IngestionCursor` additive table (per-consumer cursor with `(ingested_at, id)` tuple)
- [x] **T3**: `CacheSubscriber` with persistent cursor
- [x] **T4**: `Analyzer` event/flow paths read from subscriber when cache enabled
- [x] **T5**: `EventPoller` adapter delegates to subscriber
- [x] **T6**: 30s monitor tick when `pce_cache.enabled` (drops from `interval_minutes`)
- [x] **T7**: Cache lag monitor — warns on stalled ingestor
- [x] **T8**: Docs (`PCE_Cache.md` Alerts on Cache section) + E2E test (4 tests) + full validation (≥582 passed) + Status/Task update

---

## Phase 16: Offline Bundle 📋 PLANNED (2026-04-20) — FINAL PHASE

Plan: [docs/superpowers/plans/2026-04-20-phase-16-offline-bundle.md](docs/superpowers/plans/2026-04-20-phase-16-offline-bundle.md) • Target tag: `v3.14.0-offline-bundle` • Branch: `feature/phase-16-offline-bundle`

**Goal:** Any developer can `git clone` → run `bash scripts/build_offline_bundle.sh` → hand the tarball to an operator → operator installs on air-gapped RHEL 8 or 9 via `sudo ./install.sh`. No internet required on the target host.

**Decisions locked:** single artifact (EL8 + EL9), drop PDF from offline build, PBS CPython 3.12, manylinux_2_17_x86_64 wheels, no RPM required.

- [ ] **T1**: `requirements-offline.txt` + `PDF_AVAILABLE` flag in `pdf_exporter.py` + 2 new tests
- [ ] **T2**: CLI guard — `_check_pdf_available()` in `src/cli/report.py` applied to all 4 report commands + 4 new tests
- [ ] **T3**: `verify_deps.py --offline-bundle` mode + 1 new test (total tests: 523 → 530)
- [ ] **T4**: `scripts/build_offline_bundle.sh` (Linux+Windows) + `scripts/preflight.sh` + `scripts/preflight.ps1` (pre-install host checks) + `scripts/setup.sh` (git-clone Linux) + `scripts/install.sh` (offline Linux) + `scripts/install.ps1` (offline Windows) + `deploy/illumio-ops.service` + `deploy/install_service.ps1` (PBS priority) — all scripts support install **and** uninstall
- [ ] **T5**: `docs/User_Manual.md` — §1.2 Offline Bundle install steps + troubleshooting row
- [ ] **T6**: Fix `requirements.txt` header comment + final `pytest` baseline (≥530) + i18n audit
- [ ] **T7**: Manual E2E smoke test on Rocky 8 + Rocky 9 (same tarball), tag `v3.14.0-offline-bundle`

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
