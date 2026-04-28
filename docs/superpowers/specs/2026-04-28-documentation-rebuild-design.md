# Documentation Rebuild Design — 2026-04-28

## Background

Commit `ed20df0` ("chore: consolidate docs and normalize report detail output", 2026-04-27) over-aggressively pruned the project documentation:

- Deleted **all** English docs in `docs/` (User_Manual.md, API_Cookbook.md, Project_Architecture.md, SIEM_Forwarder.md, Security_Rules_Reference.md, PCE_Cache.md, report_module_inventory_zh.md) — ~3,800 lines lost.
- Drastically shrunk the surviving Chinese docs (User_Manual_zh: 804 → ~400 lines; API_Cookbook_zh: 748 → ~280 lines; Security_Rules_Reference_zh: 742 → ~300 lines; etc.) — another ~1,700 lines lost.
- Deleted `Status.md` and `Task.md` (per-project working memory).
- Total impact: ~5,500 lines of documentation removed, leaving only Chinese stubs that no longer reflect the project.

Meanwhile the project has advanced to **v3.20.0-report-intelligence** with several user-visible features that have **never** been documented:

- **R3 report intelligence modules**: `mod_change_impact`, `mod_draft_actions`, `mod_draft_summary`, `mod_enforcement_rollout`, `mod_exfiltration_intel`, `mod_ringfence`.
- **Draft Policy Decision (draft_pd)**: rules R01–R05, GUI's 7 draft_pd subtypes (`draftPdMap` in `quarantine.js`), `compute_draft` auto-enable when ruleset uses draft_pd.
- **Policy Usage** subsystem: 6 modules (`pu_mod00_executive`, `pu_mod01_overview`, `pu_mod02_hit_detail`, `pu_mod03_unused_detail`, `pu_mod04_deny_effectiveness`, `pu_mod05_draft_pd`).
- **Offline Bundle**: `scripts/build_offline_bundle.sh`, `scripts/install.sh`, `scripts/uninstall.sh` with `--install-root`, config preservation on upgrade, systemd unit, default `illumio:illumio` web GUI credentials.
- **JSON snapshot store** with retention for Change Impact comparison.
- **Threat intel hook** (`threat_intel_csv_path`) and `draft_actions_enabled` config keys.

This spec defines a complete documentation rebuild: recover the pre-`ed20df0` content as a baseline, refresh it for the current code state, supplement with material extracted from the official Illumio 25.4 Admin Guide and REST API guide via NotebookLM, and produce fully aligned EN/ZH editions with cross-document navigation.

## Goals

- **Coverage parity**: every CLI subcommand, GUI page, report module, security rule, SIEM transport, and bundle script appears in the docs.
- **Language parity**: every English heading and example is mirrored 1:1 in Traditional Chinese (繁體中文).
- **Cross-linking**: every document has a Documentation Map header and a "See also" footer; the README links to all docs.
- **Accuracy to v3.20.0**: contents reflect the codebase at the rebuild start commit (no aspirational text).
- **Recoverable from git**: anyone can re-derive the rebuild plan from git history (the `ed20df0~1` snapshot is the recovery base).

## Non-Goals

- Not a redesign of any feature. Documentation only.
- No new code, no test changes, no i18n key changes, no behavior changes.
- Not extending docs beyond features that exist on the rebuild branch.
- Not building a separate `Illumio_Concepts` document — Illumio platform background lives inside `Architecture.md`.
- Not building a separate `PCE_Cache` document — cache layer lives inside `Architecture.md`.

## Final Document Inventory

10 files total: 4 doc pairs (EN/ZH) + 2 root-level files + Status/Task.

| Path | Purpose |
|---|---|
| `README.md` / `README_zh.md` | Project entry, Quickstart, Documentation Map. |
| `docs/User_Manual.md` / `docs/User_Manual_zh.md` | Installation (Offline Bundle build / install / upgrade / uninstall / systemd) → Configuration → Operations (CLI / GUI / Daemon) → Reports (all 22+ modules including R3 and Policy Usage) → SIEM Integration (CEF/JSON, UDP/TCP/TLS/HEC). |
| `docs/Architecture.md` / `docs/Architecture_zh.md` | Illumio Platform Background → System Overview → Module Map → Data Flow → PCE Cache (SQLite WAL) → PCE REST API Integration Cookbook. |
| `docs/Security_Rules_Reference.md` / `docs/Security_Rules_Reference_zh.md` | Rule catalogue R01–R05, severity model, draft_pd auto-enable behaviour, ruleset configuration. |
| `Status.md` | Restored from commit `6518f10`, refreshed to v3.20.0 plus the rebuild status. |
| `Task.md` | Restored from commit `6518f10`, refreshed to reflect the rebuild work-in-progress. |

### User_Manual section skeleton

1. Installation
   - 1.1 Offline Bundle build (`scripts/build_offline_bundle.sh`)
   - 1.2 Install on target host (`scripts/install.sh`, `--install-root`)
   - 1.3 Upgrade behaviour (config preservation)
   - 1.4 Uninstall (`scripts/uninstall.sh`, `--purge`)
   - 1.5 systemd service (`illumio-ops.service`, `--monitor-gui`)
2. Configuration
   - 2.1 `config/config.json` keys (per `config.json.example`)
   - 2.2 TLS materials under `config/tls/`
   - 2.3 Web GUI credentials (`web_gui` section, default `illumio:illumio`)
   - 2.4 Scheduling (`rule_schedules.json`)
   - 2.5 Report config (`report_config.yaml`, `snapshot_retention_days`, `threat_intel_csv_path`, `draft_actions_enabled`)
3. Operations
   - 3.1 CLI subcommands (`monitor`, `gui`, `report`, `rule`, `workload`, `config`, `status`, `version`, `cache`, `siem`)
   - 3.2 GUI walkthrough (Dashboard, Quarantine, Integrations, Reports)
   - 3.3 Daemon mode (`--monitor`, `--monitor-gui`)
   - 3.4 Logs and log rotation
4. Reports
   - 4.1 Report types (Traffic, Audit, Policy Usage, VEN Status)
   - 4.2 Standard modules (mod01–mod15)
   - 4.3 R3 intelligence modules (`mod_change_impact`, `mod_draft_actions`, `mod_draft_summary`, `mod_enforcement_rollout`, `mod_exfiltration_intel`, `mod_ringfence`)
   - 4.4 Policy Usage modules (`pu_mod00`–`pu_mod05`)
   - 4.5 Draft Policy Decision behaviour (`compute_draft` auto-enable, draft pill in HTML header, draft_breakdown cross-tab)
   - 4.6 Output formats (HTML, JSON, CSV, Markdown)
5. SIEM Integration
   - 5.1 Transports (UDP, TCP, TLS, HEC)
   - 5.2 Formats (CEF, JSON)
   - 5.3 Forwarder configuration (`siem` section in config.json)
   - 5.4 Field mapping reference

### Architecture section skeleton

1. Illumio Platform Background (NotebookLM-sourced)
   - 1.1 PCE (Policy Compute Engine) and VEN (Virtual Enforcement Node)
   - 1.2 Label dimensions (Role / App / Env / Loc)
   - 1.3 Workload types (Managed / Unmanaged / Container)
   - 1.4 Policy lifecycle (Draft → Pending → Active)
   - 1.5 Enforcement modes (Idle / Visibility Only / Selective / Full)
2. System Overview
   - 2.1 Topology diagram (PCE ⇄ illumio_ops ⇄ Cache / SIEM / GUI / Reports)
   - 2.2 Process model (CLI vs Daemon vs Web GUI)
3. Module Map
   - 3.1 Entry: `illumio_ops.py` → `src/main.py`
   - 3.2 `src/api_client.py` and `src/api/` domain classes
   - 3.3 `src/analyzer.py` traffic/event analysis
   - 3.4 `src/report/` (generators, exporters, analysis modules)
   - 3.5 `src/events/` event pipeline
   - 3.6 `src/siem/` forwarder
   - 3.7 `src/scheduler/` (APScheduler integration)
   - 3.8 `src/gui/` Flask web GUI
   - 3.9 `src/i18n.py` i18n engine
4. Data Flow
   - 4.1 Traffic ingestion → analyzer → events → reports / SIEM
   - 4.2 JSON snapshot store and Change Impact comparison
5. PCE Cache
   - 5.1 SQLite WAL design rationale
   - 5.2 Cache invalidation and refresh policy
   - 5.3 Operator commands (`illumio-ops cache *`)
6. PCE REST API Integration Cookbook (Admin_25_4 + REST_APIs_25_4 sourced)
   - 6.1 Authentication (API key, header format)
   - 6.2 Pagination (`Link` header, `max_results`)
   - 6.3 Async job pattern (job poll, `done`/`failed` status)
   - 6.4 Common endpoints used by illumio_ops (workloads, traffic_flows, rule_sets, services, ip_lists)
   - 6.5 Error handling and retry strategy
   - 6.6 Rate limiting

### Security_Rules_Reference section skeleton

1. Rule severity model
2. Rule catalogue (R01 – R05) with: trigger, draft_pd dependency, severity, remediation hint, sample finding row
3. `compute_draft` auto-enable behaviour (`requires_draft_pd` propagation through `query_spec`, `params`, `analyzer`)
4. Operator how-to (enable / disable rules, `rule` CLI subcommand)
5. Test coverage references (`tests/test_phase34_attack_summaries.py`, etc.)

## Cross-Linking Mechanism

Every document gets two boilerplate blocks:

**Header — Documentation Map** (immediately after H1):
```markdown
<!-- BEGIN:doc-map -->
| Document | EN | 中文 |
|---|---|---|
| README | [README.md](README.md) | [README_zh.md](README_zh.md) |
| User Manual | [User_Manual.md](docs/User_Manual.md) | [User_Manual_zh.md](docs/User_Manual_zh.md) |
| Architecture | [Architecture.md](docs/Architecture.md) | [Architecture_zh.md](docs/Architecture_zh.md) |
| Security Rules Reference | [Security_Rules_Reference.md](docs/Security_Rules_Reference.md) | [Security_Rules_Reference_zh.md](docs/Security_Rules_Reference_zh.md) |
<!-- END:doc-map -->
```

Paths inside `docs/*` use `./<file>.md` and `../README.md` instead of repo-root paths so links work both on GitHub and locally rendered.

**Footer — See also** (last section before EOF):
```markdown
## See also

- [Other Document Title](./Other.md) — one-line description
```

The block is delimited by `<!-- BEGIN:doc-map -->` / `<!-- END:doc-map -->` so future updates can be applied uniformly with sed across all 10 files.

## NotebookLM Workflow

The existing notebook `8c325126-bc83-4c86-8c6e-8759a242928e` (title: "Illumio") already contains 103 sources, including the two we need:

- `124672a6-…` — `Admin_25_4.pdf` (Illumio Admin Guide 25.4)
- `210bfabd-…` — `REST_APIs_25_4.pdf` (Illumio REST API Guide 25.4)

For each topic below, run `notebooklm ask "<question>" -s 124672a6 -s 210bfabd --json -n 8c325126` and persist the raw answer + citations to `docs/_notebooklm_excerpts/<topic>.md`.

Topics (7, scoped to what we actually need):

1. PCE architecture and supported VEN deployment modes
2. Label dimensions (Role / App / Env / Loc) and label-based policy
3. Workload types: Managed / Unmanaged / Container
4. Policy lifecycle (Draft → Pending → Active)
5. Enforcement modes (Idle / Visibility Only / Selective / Full)
6. REST API authentication and pagination semantics
7. REST API async job pattern and Traffic Explorer query semantics

The `_notebooklm_excerpts/` directory is intermediate material only and **must be added to `.gitignore`** (it contains substantial third-party content). After distillation, only the synthesized prose lands in the committed docs, and citations to the official Illumio guides are noted as references in `Architecture.md` and `Security_Rules_Reference.md`.

Distribution of NotebookLM material:
- Architecture §1 (Illumio Platform Background): topics 1, 2, 3, 4, 5
- Architecture §6 (REST API Cookbook): topics 6, 7
- User_Manual §4 (Reports): brief callouts referencing label dimensions / enforcement modes where relevant
- Security_Rules_Reference §3 (compute_draft): brief callout referencing policy lifecycle

## Content Sourcing Matrix

| Section | Primary Source | Refresh Source |
|---|---|---|
| Pre-`ed20df0` baseline content | `git show ed20df0~1:<path>` | — |
| R3 modules, draft_pd, policy_usage modules | `src/report/analysis/` and `src/report/analysis/policy_usage/` | git log on those files |
| Offline bundle | `scripts/build_offline_bundle.sh`, `scripts/install.sh`, `scripts/uninstall.sh`, `docs/superpowers/plans/2026-04-20-phase-16-offline-bundle.md` | — |
| Web GUI defaults | `config/config.json.example`, `src/gui/__init__.py` | — |
| Subcommands | `src/cli/*.py` | `--help` output |
| Illumio platform background | NotebookLM (Admin_25_4 + REST_APIs_25_4) | — |
| REST API patterns | NotebookLM (REST_APIs_25_4) + `src/api_client.py` | — |
| Status / Task | `git show 6518f10:Status.md`, `git show 6518f10:Task.md` | refreshed for v3.20.0 |

## EN/ZH Alignment Rules

- English is the source of truth; Traditional Chinese mirrors it section-by-section.
- Section heading numbering and order are identical in both languages.
- All code blocks (CLI invocations, JSON, YAML, CEF samples) are byte-identical.
- All i18n keys, file paths, env var names, config keys, and class/function names appear unchanged in both editions.
- Glossary terms in `_ZH_EXPLICIT` (`src/i18n.py`) are not translated in either edition (this preserves the existing convention).
- Verification command (used by acceptance gate G3): `diff <(grep -E '^#{1,6} ' <EN>) <(grep -E '^#{1,6} ' <ZH>)` must show only the heading text differences, never structural differences.

## Implementation Phases

These phases define **what** must be done, in **what order**, with **what verification**. The implementation plan generated by `writing-plans` will turn each phase into a concrete task sequence.

- **Phase A — Skeleton restore.** For each target file, recover the closest pre-`ed20df0` ancestor with `git show`. Place restored content under the planned path (merging where the new structure consolidates old files: User_Manual ← User_Manual + SIEM_Forwarder + report_module_inventory; Architecture ← Project_Architecture + API_Cookbook + PCE_Cache). At the end of Phase A every planned file exists and contains a valid restored baseline.
  - **Verify:** `ls README.md README_zh.md docs/User_Manual.md docs/User_Manual_zh.md docs/Architecture.md docs/Architecture_zh.md docs/Security_Rules_Reference.md docs/Security_Rules_Reference_zh.md Status.md Task.md` returns 10 files.

- **Phase B — Refresh to v3.20.0.** Update User_Manual to cover R3 modules, Policy Usage modules, draft_pd, web_gui defaults, all current subcommands, and the offline bundle scripts. Update Architecture to cover the JSON snapshot store, the new analysis modules, and the actual current `src/` layout. Update Security_Rules_Reference to document R01–R05 and `compute_draft` auto-enable.
  - **Verify:** for every entry under `src/report/analysis/mod_*.py` and `src/report/analysis/policy_usage/pu_*.py`, the module name appears at least once in `docs/User_Manual.md`. For every subcommand listed in `_CLICK_SUBCOMMANDS` in `illumio_ops.py`, the subcommand appears in `docs/User_Manual.md`. For each script in `scripts/{build_offline_bundle.sh,install.sh,uninstall.sh}`, the filename appears in `docs/User_Manual.md`. Run via `scripts/check_doc_coverage.sh` (created in Phase B).

- **Phase C — NotebookLM extraction.** Add `docs/_notebooklm_excerpts/` to `.gitignore`. Run the 7 ask queries, save raw answers locally, distill into Architecture §1 and §6 with brief callouts in User_Manual §4 and Security_Rules_Reference §3. Citations to Admin_25_4 / REST_APIs_25_4 noted as a "References" footer in Architecture.
  - **Verify:** `grep -c "^# " docs/_notebooklm_excerpts/*.md` shows 7 files; Architecture §1 and §6 contain non-stub content (≥ 80 lines each).

- **Phase D — Documentation Map and cross-linking.** Insert the `<!-- BEGIN:doc-map --> … <!-- END:doc-map -->` block at the top of each of the 10 files. Add a "See also" footer to each. Update `README.md` and `README_zh.md` to link to all docs. Replace any `docs/...` links inside `docs/*.md` with relative `./<file>.md` paths.
  - **Verify:** `grep -L "BEGIN:doc-map" README.md README_zh.md docs/*.md` returns empty (every file has the block). A simple Python markdown link checker (added under `scripts/check_doc_links.py` in Phase D) reports zero broken local links.

- **Phase E — ZH translation pass.** Translate each EN doc into Traditional Chinese, preserving headings/structure/code blocks. `Status.md` and `Task.md` are excluded from EN/ZH parity — they stay in their original mixed-language operator-notes style.
  - **Verify:** for each EN/ZH pair, `diff <(grep -E '^#{1,6} ' EN) <(grep -E '^#{1,6} ' ZH) | wc -l` shows zero structural drift (heading text differs but heading count and depth match).

- **Phase F — Acceptance gate.** Run the full acceptance checklist (below). Restore-from-baseline check: pick a random sentence from `git show ed20df0~1:docs/User_Manual.md` and confirm a content equivalent exists in the new `docs/User_Manual.md`.

## Acceptance Checklist

The rebuild is **done** when **all** of the following hold:

- **G1** — All 10 planned files exist with non-empty content (`wc -l` ≥ 100 for each doc; ≥ 30 for README files).
- **G2** — Line-count floors (each EN file): `docs/User_Manual.md` ≥ 1,700; `docs/Architecture.md` ≥ 800; `docs/Security_Rules_Reference.md` ≥ 700; `README.md` ≥ 100. ZH counterparts must be within ±15 % of their EN sibling. Sum across all 10 files ≥ 6,500 lines, restoring the pre-`ed20df0` baseline.
- **G3** — Heading-structure parity: for each EN/ZH pair, `diff <(grep -E '^#{1,6} ' EN | sed 's/[^# ].*//') <(grep -E '^#{1,6} ' ZH | sed 's/[^# ].*//')` is empty.
- **G4** — Coverage: every report module under `src/report/analysis/mod_*.py` and `src/report/analysis/policy_usage/pu_*.py`, every subcommand in `_CLICK_SUBCOMMANDS`, and every offline-bundle script appears in `docs/User_Manual.md`. Verified by `scripts/check_doc_coverage.sh`.
- **G5** — Documentation Map present in all 10 files (`grep -L "BEGIN:doc-map" README.md README_zh.md docs/*.md` empty).
- **G6** — Markdown link checker reports zero broken local links across README + docs.
- **G7** — i18n guardrails unaffected: `python3 scripts/audit_i18n_usage.py` exits 0 and `python3 -m pytest tests/test_i18n_audit.py tests/test_i18n_quality.py` passes.
- **G8** — `_notebooklm_excerpts/` is gitignored; no third-party Illumio PDF text appears verbatim in committed files (spot-checked with `git diff --stat | grep _notebooklm_excerpts` returning empty).
- **G9** — `Status.md` and `Task.md` exist at repo root and reflect v3.20.0 plus the rebuild commit hash.

## Risks and Mitigations

- **R1: NotebookLM rate limiting / failed ask** — mitigation: use `--retry 2` on each ask, fall back to a manual summarized paragraph if a query fails; do not block the rebuild on a single missing topic.
- **R2: ZH translation drift over time** — mitigation: structural-parity diff (G3) is part of the acceptance gate and can be re-run by reviewers.
- **R3: Bundle script changes after spec is written** — mitigation: pin the rebuild to the start commit hash; if scripts change during the rebuild, re-run Phase B for User_Manual §1.
- **R4: Embedding licensed Illumio content** — mitigation: only synthesized prose lands in committed files; raw NotebookLM excerpts stay in gitignored `_notebooklm_excerpts/`; references cite the Illumio guides by name.
- **R5: Stale README links elsewhere in repo** — mitigation: Phase D's link checker (`scripts/check_doc_links.py`) walks every `*.md` under repo root and reports any broken local link, not just inside the new docs.

## Out of Scope (explicit)

- Updating `docs/superpowers/plans/*.md` or `docs/superpowers/specs/*.md` — those are working artefacts, not user docs.
- Updating `AGENTS.md` or `CLAUDE.md` — they are agent instructions, separately maintained.
- Updating in-code docstrings.
- Generating PDF / EPUB / HTML render of the docs.
- Adding any new feature to the project itself.
