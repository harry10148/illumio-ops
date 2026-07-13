# Changelog

All notable changes to illumio-ops are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/) —
a plain `<major>.<minor>.<patch>` scheme. (Tags through v4.0.0 carried a
`-topic-slug` codename suffix; the codename was retired in 4.1.0.)

## [Unreleased]

### Added

- VEN report: policy sync tracking for VENs that report normally — a KPI, a
  dedicated section, and an XLSX sheet flag online VENs with agent health
  errors/warnings, a sync state stuck off `applied`, stale firewall config, or
  policy received but not applied (vendor-verified signals; the deprecated
  `security_policy_refresh_at` column was replaced by
  `security_policy_received_at` with a fallback for old PCEs).

### Fixed

- Policy Resolver report always produced "no resolvable ACTIVE policy": scope
  filtering compared actor label hrefs against scope label hrefs (role-type
  actors never match), deny rules were never expanded (rows now carry an
  `action` column: allow / deny / override_deny), and actor-level
  `exclusion: true` entries were unioned instead of subtracted.
- Rule Hit Count report rendered bare actor type names (Label/IPList) instead
  of object names — the enrichment now warms the label cache before resolving;
  missing CSV descriptions no longer render a literal `nan`.
- VEN report policy-sync badge treated the real-world `applied` state as
  unsynced (red) because it only recognized `synced`.

### Changed

- Report cards, generation modals, and the app header now use
  content-specific icons instead of a shared shield (shield stays with
  Security & Risk); the header carries an original micro-segmentation mark.

### Changed

- Offline bundle / DB hardening: `_ADDED_COLUMNS` schema registry entries are now
  table-qualified (`("table", "column", "ddl")`) instead of column-name-only, closing
  a drift risk where two tables could share a column name. `install.sh`'s dependency
  refresh is now deterministic — the bundled Python runtime is restored to a pristine base and
  wheels are fully reinstalled (not merged/patched) on upgrade, with stale files left
  behind by the previous version cleaned up; the upgrade `rsync --delete` excludes
  (`config/`, `data/`, `logs/`, `reports/`, `python/`, `MIGRATED_FROM`, `uninstall.sh`)
  are now anchored to the transfer root so they can't accidentally match same-named
  paths nested deeper in the tree. `uninstall.sh` now preserves `data/` alongside
  `config/` by default; both are only removed with `--purge`. Docs: the upgrade SOP is
  aligned with actual installer behavior — the installer never restarts the service
  itself, so the documented steps now say so explicitly. The downgrade guard also
  falls back to the cache DB's `PRAGMA user_version` when the installed version
  string is unreadable (the uninstall-then-reinstall-older path), and the wrapper
  docs note that real operations need `sudo`. Windows: shipped PowerShell scripts
  now carry a UTF-8 BOM (PowerShell 5.1 misparsed the BOM-less files on CJK ANSI
  code pages), the bundle includes the Windows-only wheels (`colorama`,
  `win32-setctime`) that the Linux-side `pip download` silently skipped via
  environment markers, and `install.ps1` aborts on pip failure and runs the same
  `verify_deps.py --offline-bundle` post-install verification as Linux.
  `install.ps1` now also carries the same upgrade guards as `install.sh` —
  refuses downgrades unless `-AllowDowngrade` (version string with a cache-DB
  `PRAGMA user_version` fallback) and stops a running service before copying
  files — and its uninstall preserves `config\` and `data\` unless `-Purge`.
  `install.ps1` also creates the runtime dirs (`logs\`, `data\`, `reports\`)
  like `install.sh` does, and no longer fabricates a `MIGRATED_FROM` marker
  when reinstalling over a preserved `config\`/`data\` with no service present.
  `scripts/check_doc_coverage.sh` works again: retargeted to the split docs
  (`docs/reference/cli.md` for subcommands, `docs/getting-started.md` for
  deployment scripts); the analysis-module filename family was dropped as no
  longer operator-facing.
- `report traffic` now generates the new plain Traffic Flow Report (traffic facts only,
  no security scoring). Use `report security` / `report inventory` for the previous
  outputs; `--profile` on `report traffic` is deprecated.
- Trend and baseline-drift snapshots are now keyed per report profile
  (`traffic_security_risk`, `traffic_network_inventory`, `traffic_traffic`).
  The first run after upgrading has no previous baseline to compare against.
- Security report simplification (phase 2): the three former attack-summary chapters
  (boundary breaches, suspicious pivot behavior, blast radius, blind spots) and the
  hero key-findings block are consolidated into a single Findings & Actions chapter,
  with attack posture items merged by subject and quantified with real evidence text;
  the Lateral Movement chapter is trimmed to 4 summary tables (service view, fan-out
  sources, allowed lateral flows, attack paths), with host-level detail (IP talkers/
  pairs, bridge nodes, reachable nodes, app chains) trimmed from HTML (detail
  retained at the analysis layer and available in the XLSX export's Lateral
  Movement sheet); the
  Policy Decisions chapter folds sub-1% decisions into an "Other" row (with a note
  listing which decisions were folded) and now surfaces the audit-flags table
  (unmanaged-source allowed traffic); the Uncovered Flows chapter merges the port/
  service-gap view into one table with a Top Destination Apps column; the maturity,
  enforcement-readiness, and infrastructure-scoring sections each gained a
  plain-language "how to read this score" explanation; the dead mod05 (legacy IP
  host talkers) and mod10 (legacy allowed-traffic audit) modules were removed now
  that their outputs are covered by mod15 and mod02 respectively.
- Inventory report simplification (phase 3): refocused on asset/label governance —
  the traffic overview, traffic distribution, and bandwidth chapters are dropped
  from `report inventory` (still available via `report traffic`); the Cross-Label
  Matrix chapter keeps only the ENV/APP dimensions in HTML, with ROLE/LOC detail
  trimmed from HTML (detail retained at the analysis layer and available in the
  XLSX export's Cross-Label sheet); the Unmanaged Hosts chapter is
  merged to 3 tables, with the exposed-ports table gaining a Top Unmanaged Sources
  column; a date-range parsing fix means flows with no valid timestamps now show
  a single "N/A" instead of "N/A → N/A"; the Change Impact chapter is now wired to
  the real posture KPI snapshot — the first run after upgrading shows a "no
  previous snapshot" note, and subsequent runs render an actual delta table
  (previously this chapter never rendered deltas due to a snapshot key mismatch).
- XLSX export unification: the Audit, Policy Usage, VEN, and Traffic (all three
  profiles) XLSX exporters now build every sheet directly from the same
  `module_results` dict that drives the HTML report — no separate re-derivation
  or raw-dataframe recompute path, so HTML and XLSX are guaranteed same-source.
  Behavioral fixes that came with this: the Audit Correlations sheet, which was
  always empty under the old exporter, now carries real correlated-sequence/
  brute-force/off-hours data; the Policy Usage Unused Rules sheet now lists the
  complete unused-rule set from `module_results` instead of a separate
  recomputed-and-capped (500-row) query; the VEN XLSX sheets are renamed
  Lost Today / Lost Yesterday and now map correctly to the 24h/24-48h buckets
  (the old "Lost <24h" / "Lost 24-48h" sheet names were swapped relative to the
  data they contained); the Traffic XLSX gains the six Lateral Movement and four
  Cross-Label Matrix / three Unmanaged Hosts detail tables that phase 2/3 demoted
  out of HTML (see above), fulfilling the "available in the XLSX export" notes;
  the old from-raw-flows Top Talkers sheet is retired and superseded by the
  Lateral Movement sheet's `ip_top_talkers` table (same source, no duplicate
  recompute); every dataframe cell across all four XLSX exporters is now passed
  through the shared formula-injection guard (leading `=`/`+`/`-`/`@` neutralized)
  the same way the HTML exporters already were. Charts are an HTML-only feature —
  the curated XLSX workbooks keep only the Executive Summary chart (stacked-table
  sheets have no chart anchor point) and do not attempt chart parity with HTML.
- Report simplification (phase 5 — Audit / Policy Usage / VEN Status): the Audit
  report's Health, Users, and Policy Changes chapters now show only the 10 most
  recent events each in HTML (previously the full, up to 50-row, list), with a
  note pointing to the complete list; the XLSX export gained a Recent Events
  sub-table on each of those three sheets so the full (up to 50-row) list is
  still available there. Audit executive-summary KPI labels (and the XLSX
  Attention Required sheet) now resolve through their i18n key first, so zh_TW
  reports show real Chinese labels (e.g. "事件總數") instead of the English label
  leaking through; the traffic/VEN/policy-usage exec summaries, which already had
  localized labels, are unaffected. Embedded chart SVGs (used across audit,
  traffic, and policy-usage reports) no longer carry a `<metadata>` block
  (creation date/tool), for a small size reduction with no visual change. The
  Policy Usage report's Unused Rules chapter shows the first 50 rules in HTML
  (previously unbounded, up to the analysis layer's existing 1000-row cap) with a
  note giving the shown/total count and pointing to the full list in CSV/XLSX;
  the Hit Rules chapter is unaffected. The Policy Usage report's three separate
  Draft Policy Risk tables (visibility risk, draft conflicts, draft coverage) are
  merged into a single Top At-Risk Flow Pairs table with a new Risk Type column
  (each type keeps its own top-20 ranking); the by-subtype summary pills for all
  three categories are unchanged. The VEN Status report's Online chapter now
  shows a count plus a version-distribution summary instead of a per-host table;
  per-host online detail moved to the XLSX/CSV export only (the Offline / Lost
  Today / Lost Yesterday chapters, and the XLSX/CSV exports, are unaffected).
- Filter backend chain: the unified flow DataFrame (cache and report path) now
  carries `windows_service_name` and `transmission` flattened columns (empty
  string when the underlying flow has no value), enabling DataFrame-path
  filtering on cached/report data for the new filter keys below. This
  DataFrame-path filtering only applies to flows ingested at or after this
  release — rows cached before the upgrade were flattened by the old
  flattener and lack these columns, so an include filter on either key
  fails closed (matches nothing) until the flow is re-ingested.
- FilterBar v2: PCE-native three-column layout (Source / Destination / Service with
  is-not exclusion rows), AND/OR mode toggle with pill migration, source/destination
  swap, per-column category panels (Transmission is destination-only), and service
  input guidance (numeric input offers both/TCP/UDP with both as default; `-` extends
  to a range; text matches Process Name / Windows Service / Policy Services).
- The five GUI modals (instant report, scheduled report, saved query, traffic rule,
  bandwidth rule) no longer render bare Port / Protocol / Exclude Port fields; port
  and protocol filters are entered as FilterBar service pills. Saved configs with
  legacy scalar `port`/`proto`/`ex_port` are still read back as port pills and are
  normalized to `ports`/`ex_ports` tokens on next save.
- Known limitation (pre-existing): in OR mode the `any_*` filter keys remain
  single-valued on the backend, so multiple pills of the same category in the merged
  column still resolve to the last value.

### Added

- New filter keys, wired end-to-end across the full seven-layer chain (PCE-native
  query payload where the PCE API supports it, the async-query client-side
  matcher, and the cache/report DataFrame matcher): `process_name` /
  `ex_process_name`, `windows_service_name` / `ex_windows_service_name`, and a new
  `transmission` include key (`transmission` / `ex_transmission`;
  `transmission_excludes` remains a supported alias for the exclude side). All
  three match case-insensitively on the full string, accept a scalar or a list of
  values, and are null-tolerant: a flow row missing the underlying field fails
  closed for an include filter and is never excluded by an exclude filter.

- Fail-fast SQLite runtime check: entry points now refuse to start with a clear error
  when the linked SQLite is older than `3.35.0` (`src/runtime_checks.py`), instead of
  failing later with cryptic ALTER TABLE / window-function errors.
- `/usr/local/bin/illumio-ops` CLI wrapper installed by `install.sh` so the CLI is on
  `PATH` without manually activating the bundled venv.
- `preflight.sh` now checks the bundled SQLite version against the `3.35.0` floor and
  reports the existing cache DB's `user_version` before install/upgrade.
- Schema registry hardening: a frozen-baseline drift guard test now fails if a future
  column-migration entry silently rewrites `_ADDED_COLUMNS` history, and opening a
  cache DB with a newer `user_version` than the running code knows now emits a
  downgrade warning instead of proceeding silently.
- `install.sh` gained a downgrade guard (blocks installing an older bundle version
  unless `--allow-downgrade` is passed), a running-service guard (stops the service
  before overwriting files and prompts to restart it after), and post-install
  verification (`verify_deps` + a smoke check) that fails the install if the new
  environment is broken.
- Enforcement Readiness Report (`report readiness`, CLI + GUI + scheduler): a
  standalone report answering "which app (env) can safely move to enforcement
  next" — readiness score/grade, an advancement queue ranked ready-first with
  per-app blocking factor and recommended action, factor breakdown, remediation
  recommendations, and a trend chapter. Shares its scoring engine with the
  Security report's Enforcement Readiness chapter (same `enforcement_readiness`
  analysis, so the two reports never disagree on a given app's score). Available
  in HTML/CSV, in both English and Traditional Chinese.
- Plain Traffic Flow Report profile (`traffic`): overview, policy decision summary,
  app/env distribution, bandwidth, unmanaged overview. Runs only lightweight modules.
- Trend/drift credibility hardening (phase 6): the Baseline Drift chapter now excludes
  noise signatures (ICMP, port 0, ephemeral ports ≥49152) from both the new/disappeared
  tables and their counts, and collapses `(unlabeled)→(unlabeled)` pairs into a single
  summary line instead of listing them as individual pairs. Both the Baseline Drift
  chapter and the per-report Trend section now carry snapshot metadata (window/
  data_source/profile); when a run's window differs materially from the previous
  baseline/snapshot, drift comparison is refused (a note explains why, and a fresh
  baseline is still saved) and the Trend section shows a caveat naming the differing
  fields — snapshots saved before this metadata existed compare exactly as before (no
  refusal, no caveat). Also fixed an off-by-one in the trend snapshot lookup that made
  the Trend delta always compare against the run before the previous one instead of
  the previous run itself; it now appears from the very next report after a baseline
  exists. This closes out the 2026-07-02 traffic/security report-split spec — all six
  phases (report split, security/inventory simplification, XLSX unification, audit/
  policy-usage/VEN slimming, and this trend/drift hardening) have now shipped.

### Fixed

- Report generation no longer produces a silent empty/partial report when the PCE
  traffic query fails. `execute_traffic_query_stream` swallows a PCE failure (submit
  406, poll timeout, download error) into an empty yield and records it on
  `api.last_fetch_error` — the ingest and analyzer paths already surface this, but the
  report generator's traffic fetch did not, so a failed query looked identical to a
  genuine 0-row result. The report path now checks `last_fetch_error` after every PCE
  call (full and hybrid-gap fetches) and raises `TrafficQueryError`, matching
  `analyzer._raise_if_query_fetch_failed`; a failed hybrid gap fetch can no longer
  silently degrade to cache-only. Cache-only reads never call the PCE and are unaffected.
- `siem status` / `siem replay`: a schema mismatch or DB corruption (`OperationalError`)
  is no longer masked by the first-run zero-count fallback — only a genuinely missing
  cache DB (`no such table` / `unable to open database file`) takes the zero-count
  path; anything else now surfaces the real error and exits non-zero.
- Display-layer fixes (phase 4): actor names resolve to readable text instead of a raw
  Python dict literal across the report layer and the Rule Scheduler CLI — `ams` now
  renders as "All Workloads" (CLI live-view truncation width widened from 12 to 15 so
  it isn't cut mid-word), and any other unrecognized actor shape falls back to a
  human-readable `key:href-tail` form (or the shape's key names) rather than printing
  the dict.
- Attack posture badge removed from the GUI Reports list (it duplicated the Dashboard's
  Security Posture score without adding information); the underlying data chain
  (`attack_summary_counts`, the `reports.py` API field, email rendering) is untouched —
  only the reports-list badge markup and its now-orphaned i18n key were removed.
- Findings from the draft-policy rules (R01-R05) now render under a translated
  "Draft Policy" / "草稿 Policy" category card in the Security & Risk report instead of
  falling back to the raw internal category key.
- Port-value columns (`Port`) in HTML report tables no longer get a thousands
  separator (e.g. `8080`, not `8,080`); count columns that merely mention "port"
  (`Unique Ports`, `Top Hit Ports`, ...) are unaffected and keep grouping.
- Policy Diff and App Summary HTML reports gained a print/PDF button (they previously
  had no sidebar and no way to trigger print from the page); a guard test now scans
  all six HTML exporters for the button so this can't silently regress again.
- Long unbreakable strings (e.g. a 100+ character hostname) in report tables now wrap
  inside the cell on screen instead of forcing horizontal scroll; print layout was
  already unaffected and remains untouched.
- The GUI reports and dashboard endpoints were silently dropping the `ports` /
  `ex_ports` / `services` / `ex_services` FilterBar keys before forwarding to the
  analyzer — the filter pills appeared active in the UI but had no effect on the
  results. These keys are now forwarded like the rest of the filter set; a static
  source-contract test now checks every endpoint's forward-whitelist against the
  full filter key set so this class of silent-drop regression can't recur.
- Rule Hit Count HTML report: was missing the "print to PDF" sidebar button that
  every other report family has; it now renders it. The print-button guard test
  now scans all HTML exporter sources, so no report family can ship without it.

## [4.1.0] — 2026-06-21

### Changed

- Version management refactor: `src/__init__.py` `__version__` is now the
  single source of truth; offline bundle names are clean semver
  (`illumio-ops-<X.Y.Z>-offline-...`, or `<X.Y.Z>+<short-hash>` for dev builds)
  via `scripts/resolve_version.sh` instead of `git describe`.
- Added `scripts/bump_version.sh` to bump `__version__`, seed a CHANGELOG
  section, commit, and tag in one step.
- Retired the `-topic-slug` codename convention in favour of plain semver.

## [4.0.0] — 2026-05-23

### Changed

- UI/UX Modern SaaS overhaul, security-audit remediation, and timezone-aware
  datetime refactor. Tagged `v4.0.0-secure-modern-saas`; this entry backfills
  the 3.27.0 → 4.0.0 gap. See the git tag and history for the full commit set.

## [3.27.0-docs-refactor] — 2026-05-15

Documentation refactor — restructured the entire `docs/` tree to a 22-pair
bilingual layout mirroring `src/` modules, established YAML frontmatter
hygiene, added a bilingual audit tool, and removed 14 legacy doc pairs whose
content had drifted from the codebase.

### Documentation

- Restructured `docs/` to a 22-pair bilingual tree mapped to `src/` modules
- New entry point: `docs/INDEX.md` / `docs/INDEX_zh.md` with 4 reader-role entries (Operator / Developer / Integrator / Auditor)
- All docs now carry `last_verified` + `verified_against` YAML frontmatter
- Added `scripts/docs_check.py` audit tool (bilingual / freshness / links / frontmatter checks; `--exclude` glob support)
- 14 legacy doc pairs replaced; audit trail at `docs/_meta/migration-audit.json` (70 claims documented across 14 sources)
- `README.md` and `README_zh.md` slimmed to ≤100 lines, point to `docs/INDEX.md`
- 5-layer cross-linking model on every doc (language switch / breadcrumb / Related Docs / inline / INDEX entry)

### Breaking

- Removed `docs/Installation{,_zh}.md`, `docs/UPGRADE{,_zh}.md`, `docs/User_Manual{,_zh}.md`, `docs/Report_Modules{,_zh}.md`, `docs/Security_Rules_Reference{,_zh}.md`, `docs/SIEM_Integration{,_zh}.md`, `docs/Architecture{,_zh}.md`, `docs/PCE_Cache{,_zh}.md`, `docs/API_Cookbook{,_zh}.md`, `docs/Glossary{,_zh}.md`, `docs/Troubleshooting{,_zh}.md`, `docs/cli-command-map{,_zh}.md`, `docs/fonts-vendoring{,_zh}.md`. External links to these paths will 404 — use `docs/INDEX.md` to find new locations.

### Documentation hygiene findings (legacy doc claims found wrong)

The refactor surfaced these stale claims in legacy docs (full list in `docs/_meta/migration-audit.json`):

- PDF generation: legacy claimed ReportLab; current is HTML + browser-native `window.print()` (commit `92143a6`)
- Multi-PCE dashboard switcher: legacy referenced widget; not in current `index.html`
- SIEM `format: json`: legacy claimed `JSONLineFormatter`; current is `NormalizedJSONFormatter` (commit `edda47b`)
- SIEM endpoint: legacy used single `endpoint: "host:port"`; current splits into `host` + `port` (commit `7035f50`)
- `/health` endpoint: legacy referenced; actual is `/api/status`
- PCE cache path: legacy showed `cache/`; actual is `data/pce_cache.sqlite` (commit `a88e823`)
- CLI subcommands: legacy `pce`, `tls`, `rule-scheduler` as top-level CLI commands → actually only via interactive `shell` menu
- Offline bundle: legacy claimed pre-built `dist/`; `dist/` is empty, requires `scripts/build_offline_bundle.sh`

---

## [3.26.0-i18n-architecture] — 2026-05-09

i18n architecture refactor — consolidated three parallel translation
subsystems into one source of truth, retired the runtime regex auto-translator,
parameterized language at the call site, and migrated rule storage from
rendered text to keys. 35 commits, 22-task plan executed via
subagent-driven-development.

### R1 — Single Source of Truth

- Absorbed 467 only-`STRINGS` keys + 141 overlap differences into
  `src/i18n_*.json` (now ~2,767 keys per locale). `migrate_strings_to_json.py`
  drives the migration and is idempotent.
- Replaced 815-line static `_StringMap` literal with `_StringsView` thin
  wrapper that delegates to `t()` for JSON-backed keys and keeps a small
  runtime overlay (~198 dynamic-write keys for `rpt_cat_*` / `rpt_rule_*`).
- 9 HTML exporter callsites unchanged — the wrapper preserves the
  `STRINGS[k].get(lang)` shape they depend on.

### R2 — Glossary + Strict Prefixes Externalized

- New `src/i18n/data/glossary.json` is the single SoT for English terms
  that must remain English in zh_TW (Block, Allow, Manage, Unmanage, PCE,
  VEN, Workload, Service, Port, Policy, Ringfence, App, Label, SMTP,
  Online, Offline, Ruleset, Enforcement). 16 entries with explicit
  forbidden Chinese substitutes for programmatic detection.
- `_STRICT_PREFIXES` (28-element tuple) and the 2 humanize exceptions
  (`event_label_`, `cat_`) moved to `src/i18n/data/strict_prefixes.json`.
- `_translate_text()` regex chain (46 substitutions) retired from the
  `t()` runtime hot path — `_build_messages` is now a pure dictionary
  lookup. The function stays callable for the precompute migration script.
- AST-walking guard test asserts `_build_messages` no longer invokes
  `_translate_text`.
- Audit `Cat E` aligned with `glossary.json` SoT.

### R3 — `t(key, lang=...)` Parameter

- `t()` accepts an explicit, keyword-only `lang=` argument. Falls back to
  the process-global language when omitted (backward-compatible).
- `report_generator.py` and `gui/routes/events.py` no longer call
  `set_language()` — both thread `lang=` through 17+ `t()` calls. Removes
  the global-mutation race in concurrent rendering.
- New `tests/test_i18n_set_language_callers.py` lint guard: `set_language`
  is bootstrap-only (allowed in `src/config.py`, `src/i18n/`, and CLI
  startup; banned everywhere else).

### R4 — Rules Persist Keys, Not Text

- Rules schema accepts `desc_key` / `rec_key` fields. `ConfigManager.load()`
  resolves them via `t(key, lang=lang)` at read time; `save()` strips
  rendered `desc` / `rec` when keys are present. Disk holds keys as the
  canonical source.
- `_heal_stale_rule_i18n()` self-heal removed — its logic absorbed into
  the new `_resolve_rule_keys()` for backward compat with legacy
  `[MISSING:*]` markers.
- `migrate_rules_to_keys.py` upgrades older config.json rules in place;
  idempotent.

### Performance + Quality

- 217 pre-existing zh_TW glossary violations remediated (Manage→管理 (38),
  Allow→允許 (30), Block→封鎖 (21), Workload→工作負載 (19), Offline→離線
  (19), Policy→政策 (16), Label/Labels→標籤 (30), Service→服務 (12), …).
- Module-load cost on `report_i18n` dropped from ~86ms to ~9ms via
  `_StringsView.overlay_items()` for COL_I18N construction.
- `_ZH_EXPLICIT` (1,430 entries) lazy-loaded via PEP 562 `__getattr__`
  instead of eager module-level import.
- 4 pre-existing mypy errors on the i18n surface cleared (no `# type: ignore`
  suppressions — proper renames).
- `audit_i18n_usage.py` exits 0 across all 9 categories.

### Tests

- 1027 passing, 0 xfail (down from 1 xfail at the end of the 22-task
  plan — glossary remediation closed it).
- New tests: `test_i18n_strings_parity`, `test_i18n_lang_param`,
  `test_i18n_glossary`, `test_i18n_strict_prefixes`,
  `test_i18n_set_language_callers`, `test_i18n_translate_text_audit`,
  `test_i18n_consumers_smoke`, `test_config_rule_keys`,
  `test_report_generator_lang_param`, `test_gui_routes_lang_param`,
  plus subprocess tests for the 3 migration scripts.

### Migration

Users on older config.json files: run
`python scripts/migrate_rules_to_keys.py --config <path> --write` to
upgrade rule storage. The script is idempotent.

### R3 follow-up — Full lang= threading audit (TA1–TA4, TB1–TB3, TC1–TC3)

A subsequent codebase-wide audit identified ~256 additional `t()` calls in
non-CLI code paths that still relied on the process-global lang. All were
migrated across 10 follow-up tasks (10 commits, 2026-05-10):

- **GUI routes** (TA1–TA4, ~108 calls): `gui/routes/{reports,actions,rules,events,rule_scheduler,dashboard,config,admin,auth}.py`, `gui/_helpers.py`, `gui/__init__.py`, `pce_cache/web.py`, `siem/web.py`. Each handler now reads `lang` from the request (JSON body or session) and threads it explicitly. `gui/__init__.py` adds `_request_lang()` helper for `before_request` hooks.
- **Schedulers + alerts** (TB1–TB3, ~75 calls): `report_scheduler.py` adds `lang` to schedule schema (backward-compatible); `RulesEngine` accepts `lang` in `__init__`; alert plugin `.send()` and `metadata.resolved_*()` accessors gain keyword-only `lang` parameters.
- **Analysis modules** (TC1–TC3, ~114 calls): module adapter framework in `src/report/analysis/__init__.py` auto-detects `lang` support via `inspect.signature`; 10 traffic + policy_usage modules now accept `lang`; report generators (`html_exporter`, `ven_status_generator`, `policy_usage_generator`, `audit_generator`) thread `self._lang` through all internal `t()` calls.

**Final state:** 0 unmigrated `t()` calls in non-CLI `src/`. CLI menus deliberately retain global lang (single-process deployment, lang set at bootstrap from config). Tests still 1027 passed; audit exit 0.

### Plan + Implementation Status

- Plan: `docs/superpowers/plans/2026-05-09-i18n-architecture-refactor.md`
- 22 plan tasks complete (T1–T22), plus 5 first-round follow-ups (P1 glossary,
  P2 mypy, P3 perf, P4 docs, P5 push) and 10 audit-driven follow-ups
  (TA1–TA4, TB1–TB3, TC1–TC3). All commits on `main`.

## [3.25.0-tracks-abcd] — 2026-05-07

UX/CLI/Report/Email global-assessment sprint — Tracks A, B, C, D were
planned, implemented, and merged to `main`. All 16 assessment cards
(a1–d3) reached the ≥2 rubric target; sprint closed. Track E (Flask →
FastAPI/Starlette + SSE migration) was gated and dead-lettered as
over-engineering once a1/c1 reached ≥2 through cheaper paths.

### Track A — Visual System

- Vendored variable woff2 fonts: Space Grotesk (header), Inter (body),
  JetBrains Mono (mono) — ~140 KB total, served from `src/static/`.
- Migrated GUI `--header-font` / `--body-font` / `--mono-font` and
  `templates/login.html` to the new vendored families.
- D.3 signal palette applied across surfaces:
  `success #2D9B5E`, `warning #C47A00`, `danger #D93025`, `info #0077CC`.
- Email CTAs and `chart_renderer` adopt the same palette so reports,
  GUI, and email stay visually consistent.

### Track B — CLI Output Layer

- New shared helpers:
  - `src/cli/_exit_codes.py` — sysexits.h-aligned exit code map and
    `exit_for_exception()` dispatcher; SIGTERM now exits 143.
  - `src/cli/_output.py` — `echo_info` / `echo_warning` / `echo_error`
    / `echo_json`, plus `is_json` / `is_quiet` / `is_verbose` flag
    accessors with TTY / `NO_COLOR` awareness.
- 20 commands migrated across `cache`, `rule`, `workload`, `status`,
  `report`, `monitor`, `gui`, `siem`, `config` to the new helpers.
- Top-level excepthook routes uncaught exceptions through the typed
  exit-code dispatcher so error reporting and shell wrappers behave
  consistently.

### Track C — CLI Entry Unification

- `did-you-mean` suggester at the root: `_GroupWithSuggestions`
  overrides `resolve_command` and surfaces close subcommand matches
  for typos.
- `report generate-{traffic,audit,ven-status,policy-usage}` verb
  aliases; bare-noun forms still work but emit a deprecation hint.
- Explicit `illumio-ops shell` subcommand for the interactive REPL;
  bare invocation now hints rather than silently falling through.
- `illumio-ops completion install [bash|zsh|fish]` for shell
  autocompletion install.
- Dispatcher heuristic: when `argv[1]` does not start with `-`, route
  to click — including unknown names — so typos benefit from
  `did-you-mean` instead of argparse's `unrecognized arguments` error.
- New entry-equivalence reference: `docs/cli-command-map.md`.

### Track D — Email Quick Patches

- `multipart/alternative` with plaintext fallback (`reporter.py`
  dual-render path) so non-HTML mail clients render a usable text
  body.
- Bulletproof CTA buttons with MSO/VML conditional wraps for Outlook.
- Per-issue severity badge inline component wired into 4 sections
  (the `Why` block of each issue type).
- Inline runbook link wired into 4 sections (the `Action` block).
- Caught and fixed a real bug: `_gui_base_url()` was missing
  `web_gui.public_url` config-key fallback.
- MJML pipeline intentionally **not** adopted — for 3 templates
  totalling ~3 KB, adding a Node.js dependency is YAGNI; manual
  patches reach the same rubric target.

### Tools

- `scripts/a6_https_smoke.py` — DevTools-driven HTTPS layout-break
  smoke verifier (Playwright + Chromium); confirmed Track A vendoring
  resolved hypotheses 1–3 of the a6 hand-off (0 mixed-content, 0 page
  errors, 0 network failures, fonts all local-loaded).

### Verified

- Tests: 968 passed, 1 skipped (the pre-existing `test_i18n_audit.py`
  skip is unrelated to this sprint).
- Assessment §3 rubric: all 16 cards (a1–d3) at ≥2.
- 0 regressions across CLI / GUI / Report / Email surfaces.

## [3.24.0-h6-cli-menus] — 2026-05-02

H6 sub-plan from Batch 4 — final code-review-fixes item: split
`src/settings.py` (2218 lines, a grab-bag of CLI wizard menus + event
catalog data) into focused modules. The misnamed `settings.py` is gone.

### Added
- `src/settings/__init__.py` (47 lines) — backwards-compat shim that
  re-exports every public symbol so all `from src.settings import X`
  keep working unchanged.
- `src/events/catalog.py` — `FULL_EVENT_CATALOG`, `ACTION_EVENTS`,
  `SEVERITY_FILTER_EVENTS`, `DISCOVERY_EVENTS`, `EVENT_DESCRIPTION_KEYS`,
  `EVENT_TIPS_KEYS`, plus the catalog builder + override dicts. Catalog
  now lives next to the existing `src/events/` package, not buried in
  `settings`.
- `src/cli/menus/` package — interactive wizard functions, one file each:
  - `_helpers.py` — `_menu_hints`, `_wizard_step`, `_wizard_confirm`,
    `_tz_offset_info`, `_utc_to_local_hour`, `_local_to_utc_hour`,
    `_empty_uses_default`
  - `event.py` — `add_event_menu`
  - `system_health.py` — `add_system_health_menu`
  - `traffic.py` — `add_traffic_menu`
  - `bandwidth.py` — `add_bandwidth_volume_menu`
  - `manage_rules.py` — `manage_rules_menu` + `_parse_manage_rules_command`
  - `alert.py` — `alert_settings_menu`
  - `web_gui.py` — `web_gui_security_menu`, `_web_gui_tls_menu`,
    `_clear_screen`
  - `report_schedule.py` — `manage_report_schedules_menu`
  - `_root.py` — `settings_menu` (top-level wizard)

### Changed
- `tests/test_wizard_default_enter.py` — `safe_input` patches updated
  to target the new module locations (`_traffic_module.safe_input`
  / `_bandwidth_module.safe_input`) since the new modules import at
  module level rather than lazily.

### Removed
- `src/settings.py` (the 2218-line monolith). `src/settings/_legacy.py`
  was used as a transitional shim during Tasks 5-10 and is now deleted.

### Verified
- Tests: 824 passed, 1 skipped.
- i18n audit: 0 findings.
- mypy strict on the typed core: 0 errors.
- Catalog baseline snapshot guarded every move; no drift detected.

## Batch 4 (H4 + H5 + H6) summary

The three large refactors are complete; Batch 4 of the 2026-05-01 code
review is done. Combined impact:
- `src/i18n.py` (2275 lines) → package with 338-line engine + JSON data.
- `src/gui/__init__.py` (3821 lines) → 627-line shell + 9 Blueprints
  (~2720 lines total) + `_helpers.py` (871 lines).
- `src/settings.py` (2218 lines) → 47-line shim + `src/cli/menus/`
  (10 files, ~2100 lines total) + catalog moved to `src/events/`.

Net structural improvement: 8000+ lines of code that lived in three
giant files now live in 25+ focused modules. Public APIs unchanged;
all test coverage preserved.

## [3.23.0-h5-gui-blueprints] — 2026-05-02

H5 sub-plan from Batch 4: split `src/gui/__init__.py` (3821 lines, 76 routes
in one giant `_create_app` factory) into Flask Blueprints organised by topic.

### Added
- `src/gui/_helpers.py` (871 lines) — shared utilities (`_ok`, `_err`,
  `_err_with_log`, `_redact_secrets`, `_validate_allowed_ips`, TLS helpers,
  chart-spec builders, etc.). Re-exported from `src.gui` for backwards
  compat.
- `src/gui/routes/` package with 9 Blueprint factories (each
  `make_<topic>_blueprint(cm, csrf, limiter, login_required) -> Blueprint`):
  - `auth.py` (5 routes) — login/logout/CSRF/index
  - `dashboard.py` (10 routes) — dashboard charts, status, UI translations
  - `config.py` (10 routes) — settings, security, PCE profiles, TLS
  - `rules.py` (9 routes) — rules CRUD
  - `events.py` (4 routes) — events viewer + catalog
  - `reports.py` (15 routes) — reports + report-schedules
  - `actions.py` (10 routes) — quarantine, run-once, debug, test-alert,
    best-practices, test-conn, workloads search
  - `rule_scheduler.py` (10 routes) — rule scheduler + log history
  - `admin.py` (3 routes) — logs, shutdown
- 1 residual app-level route (`api_daemon_restart`) stays in
  `_create_app` because it reads module-level `_GUI_OWNS_DAEMON` /
  `_DAEMON_RESTART_FN` state assigned by `cli/_runtime.py`.

### Changed
- `src/gui/__init__.py` shrunk from **3821 lines → 627 lines**.
- Endpoint names gain Blueprint prefix (e.g. `auth.api_login`,
  `dashboard.api_status`). `security_check` and `login_manager.login_view`
  updated to use the new prefixed names; literal-path checks unaffected.
- `tests/test_web_security_contracts.py`, `tests/test_gui_dashboard.py`,
  `tests/test_gui_rules.py` — monkeypatch targets follow symbols into
  their new Blueprint modules.

### Verified
- Tests: 824 passed, 1 skipped (no behaviour change).
- Route-map baseline snapshot test guarded every Blueprint move.
- i18n audit: 0 findings; mypy strict on the typed core: 0 errors.

## [3.22.0-h4-i18n] — 2026-05-02

H4 sub-plan from Batch 4 of the code review: convert `src/i18n.py`
(2275 lines, dominated by ~2000 lines of literal Chinese-translation
data) into the package `src/i18n/` with engine code in `engine.py`
(~340 lines) and data in `data/*.json` (~78 KB across four JSON files).
Public API (`t`, `get_messages`, `set_language`, `get_language`)
unchanged; 59 importers continue to use `from src.i18n import …`
without modification.

### Added
- `src/i18n/__init__.py` — re-exports the public API plus 5 engine
  internals (`EN_MESSAGES`, `ZH_MESSAGES`, `_ZH_EXPLICIT`,
  `_humanize_key_en`, `_humanize_key_zh`) needed by
  `scripts/audit_i18n_usage.py` and `tests/test_i18n_quality.py`.
- `src/i18n/engine.py` — pure engine code (state, humanize, translate,
  build_messages, public API).
- `src/i18n/data/zh_explicit.json` — 1432 keys, merged from a
  four-stage in-code merge (initial literal + 3 individual patches +
  2 `.update()` blocks).
- `src/i18n/data/token_map_en.json` (115 entries),
  `src/i18n/data/token_map_zh.json` (306 entries).
- `src/i18n/data/phrase_overrides.json` (32 entries).
- `src/i18n/.gitignore` — un-ignores `data/` against the root
  `.gitignore`'s blanket exclusion.

### Changed
- `tests/test_reader_guide_render.py` — monkeypatch target updated to
  `src.i18n.engine` (the test patches private symbols `_build_messages`,
  `EN_MESSAGES`, `_normalized_en_messages`).
- `scripts/audit_i18n_usage.py` — `I18N_SOURCE_FILES` entry updated
  from `SRC / "i18n.py"` to `SRC / "i18n" / "engine.py"`.

### Verified
- Tests: 824 passed, 1 skipped (back to pre-H4 baseline).
- i18n audit: 0 findings.
- mypy strict on the typed core: 0 errors.

## [3.21.0-code-review-fixes] — 2026-05-02

Resolves 24 of 27 findings from the 2026-05-01 全面 code review (H1–H3,
M1–M11, L1–L10). The remaining three high-impact items (H4 i18n extraction,
H5 GUI Blueprint split, H6 settings rename) are deferred to dedicated
sub-plans. Final test count: 824 passed, 1 skipped; mypy strict-clean on
the typed core; matplotlib glyph-missing warnings reduced from 20 to 0.

### Added
- `src/cli/_render.py` — TUI / terminal helpers relocated from `utils.py`
  (`Colors`, `safe_input`, `draw_panel`, `draw_table`, `Spinner`,
  `format_unit`, `get_terminal_width`, …).
- `src/cli/_runtime.py` — shared `run_daemon_loop`, `run_gui_only`,
  `run_daemon_with_gui` so the legacy argparse path and the click
  subcommands stop duplicating daemon-startup logic.
- `src/report/rules/` — per-rule subpackage (`_base` + `r01`–`r05`).
- `src/static/fonts/NotoSansCJKtc-Regular.otf` — bundled CJK font
  (SIL OFL 1.1, see `src/static/fonts/LICENSE-NotoSansCJK.txt`) so
  matplotlib chart PNGs render Chinese without OS-level font installs.
- `src/py.typed` (PEP 561 marker) and `mypy.ini` (lenient defaults,
  `disallow_untyped_defs` on `api_client`, `analyzer`, `reporter`).
- `POST /api/cache/retention/run` — manual retention sweep endpoint.
- `tests/conftest.py` shared fixtures (`header_client`, `temp_config_file`,
  `app_persistent`, `client`).
- 8 split GUI-test files (`test_gui_auth`, `test_gui_event_viewer`,
  `test_gui_quarantine`, `test_gui_ip_allowlist`, `test_gui_alert_plugins`,
  `test_gui_dashboard`, `test_gui_rules`, `test_gui_misc`) replacing the
  1325-line `test_gui_security.py`.

### Changed
- **Authentication**: an authenticated session is now sufficient for
  credential / settings changes; `old_password` is no longer required.
  `PasswordChangeForm` removed; the CLI `web_gui_security_menu` (option 1)
  is the canonical forgot-password recovery path.
- **First-run UX**: default admin password is `illumio` with a
  must-change banner and a forced inline change on first login.
- Configuration split: `alerts` payload moves to
  `config/alerts.json` (auto-derived sibling of `config.json`),
  added to `.gitignore`.
- CSP relaxed: `style-src 'unsafe-inline'` enabled (no nonce, since
  any nonce in CSP Level 3 suppresses `unsafe-inline`); Montserrat
  font bundled locally.
- `src/main.py` daemon branches now delegate to `src.cli._runtime`.
- `src/utils.py` shrunk from 525 lines to a thin re-export shim.
- `src/report/rules_engine.py` shrunk from 1076 lines (rules moved
  to `src/report/rules/`); kept as a backwards-compat re-export shim.
- `setup_logger` moved to `src/loguru_config.py`.
- `print()` calls in `src/analyzer.py` and `src/reporter.py` replaced
  with the `loguru` logger.
- Type hints added across `src/api_client.py` (49 defs),
  `src/analyzer.py` (17), and `src/reporter.py` (23) — every `def`
  passes `disallow_untyped_defs`.

### Fixed
- **H1** Constant-time login (no username enumeration).
- **H3** Stop leaking exception strings to API clients.
- **L1** `secret_key` empty-string fallback now uses `or` to keep a
  generated default.
- **L4** Loguru sink-level secret redaction.
- **M1** Inline `onclick` handlers replaced with delegated
  dispatcher (CSP cleanup, change/input/keydown follow-up).
- **M2** `rule-scheduler.js` now uses the DOM API; `jsStr` removed.
- **M3** `BuiltinSSLAdapter` receives the hardened SSL context at
  construction time.
- **M7** Bare `except Exception: pass` blocks in `src/gui/__init__.py`
  now log silenced exceptions.
- **M8** `/api/logout` requires a CSRF token.
- **L2** Initial password banner shown once at startup, then erased.
- **L3** Graceful shutdown via SIGINT (replaces `os._exit`).
- **L6** Mark SIEM `TestResult` dataclass as not-a-test for pytest
  collection.
- **L5** Alert templates (`line_digest`, `mail_wrapper`) honour i18n.
- SIEM forwarder promoted to GA with inline-enqueue ingest path.
- GUI re-POST of masked secrets no longer overwrites the real value.
- Integrations Overview auto-renders; TLS-warn spam suppressed.
- `tests/test_api_client.py` — `update_label_cache` stubbed in
  `setUp` so cache-miss tests stay offline (pre-existing flaky on
  `main`, fixed as a hot-fix during the Batch 5 run).

### Deferred
- **H2** A previous attempt that re-introduced `old_password`
  enforcement was reversed once the simpler authenticated-session
  policy was adopted.
- **H4** `src/i18n.py` JSON extraction (~2300 lines) — sub-plan needed.
- **H5** `src/gui/__init__.py` Blueprint split (~3700 lines) — sub-plan
  needed.
- **H6** `src/settings.py` → `src/cli/menus/*` rename (~2200 lines)
  — sub-plan needed.

### Out-of-plan items completed on this branch
SIEM forwarder GA, Montserrat local bundling, CSP `style-src` policy
adjustments, Integrations Overview auto-render, `alerts.json` split
+ gitignore, default-admin first-run UX, cache-retention endpoint.
