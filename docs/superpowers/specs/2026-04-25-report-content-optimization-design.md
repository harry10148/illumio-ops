# Report Content Optimization Design

**Date:** 2026-04-25
**Status:** Design approved (brainstorming session); R3 partially shipped — see deferred-modules note below.
**Target tags:** v3.18.0-report-semantics (R0+R1) → v3.19.0-report-compact (R2) → v3.20.0-report-intelligence (R3)

> **STATUS (as of 2026-05-07):** R3 is partially shipped. `mod_draft_actions`, `mod_draft_summary`, `mod_ringfence`, and `mod_change_impact` exist in `src/report/analysis/`. **`mod_enforcement_rollout` and `mod_exfiltration_intel` were deferred and have no implementation in the codebase**; references to them below describe the original design, not current code. The corresponding i18n keys have been removed.

## 1. Background

The illumio_ops report family (Traffic / Audit / Policy Usage / VEN Status) covers most data points an Illumio operator needs, but several reports treat raw inventory and risk findings with the same weight, mis-label `potentially_blocked` (PB) as "rules ready", and ship 18+ MB HTML files because Plotly JS is inlined per chart. The Traffic report in particular tries to serve both 資安/SOC and 網管/平台 audiences from one giant document.

NotebookLM analysis of the Illumio product manuals confirms two structural changes:
- Flow visibility serves multiple distinct personas (SecurityOps/SOC, NetworkOps, DevSecOps, AppOwner, executive). One-size-fits-all reports dilute every audience.
- Each report section should answer four explicit questions: purpose, signals to watch, interpretation method, recommended action.

This design fixes the semantic incorrectness, splits the Traffic report into two persona-specific profiles, compresses HTML output, and adds higher-value Illumio-aligned analyses.

## 2. Goals

- **G1** Correct `potentially_blocked` semantics across reports, docs, rule descriptions, and metadata: PB is uncovered exposure (would be blocked by default-deny once enforced), not staged/ready policy.
- **G2** Split the Traffic report into two profiles — `security_risk` (for 資安/SOC) and `network_inventory` (for 網管/平台) — sharing one analysis pipeline and one set of normalized DataFrames.
- **G3** Add three orthogonal `detail_level` modes (`executive`, `standard`, `full`) that control depth without overlapping the audience axis.
- **G4** Add a uniform per-section reader-guide block (purpose / watch_signals / how_to_read / recommended_actions) across all four report types.
- **G5** Compress HTML output (target: <5 MB for a typical Traffic standard report, vs current 18.7 MB) by loading Plotly JS once and demoting low-signal sections to collapsible appendix.
- **G6** Make XLSX exports useful (real DataFrames per sheet, not empty shells).
- **G7** Add five new high-value modules layered on the draft_policy_decision foundation already shipping in policy-decision-alignment B2:
  - Override Deny / Allowed Across Boundary actionable analysis (`mod_draft_actions`).
  - Enforcement Rollout Plan (`mod_enforcement_rollout`).
  - Application Ringfence view (`mod_ringfence`).
  - Change Impact via report snapshots (`mod_change_impact` + snapshot store).
  - Exfiltration / threat-intel hooks (`mod_exfiltration_intel`).

## 3. Non-Goals

- Not migrating Audit/Policy-Usage/VEN reports into the same persona-profile model. Only Traffic is split. Other reports get reader-guides and density modes only.
- Not removing existing modules; lower-value modules are demoted (appendix or conditional), not deleted.
- Not adding cross-report aggregation (e.g., a "single dashboard report" that merges all four). Out of scope.
- Not introducing a snapshot store for any report other than Traffic at this stage. R3.4 ships only Traffic snapshots; other reports can extend later.
- Not adding RBAC for who can request which profile / detail_level. Inherits existing report auth.
- Not making the report builder UI persona-aware in this cycle. Profile selection happens via CLI flag / API parameter / GUI dropdown only.

## 4. Prerequisite

This design assumes the **policy-decision-alignment** plan (`docs/superpowers/plans/2026-04-24-policy-decision-alignment.md`) has shipped its B1+B2+B3 sub-plans, providing:
- `compute_draft=True` plumbing in `src/analyzer.py` and `src/api/traffic_query.py`.
- New rules R01–R05 in `src/report/rules_engine.py` consuming `draft_policy_decision`.
- New module `src/report/analysis/mod_draft_summary.py` (B2.2) — 7-subtype counts + top workload pairs.
- `mod02_policy_decisions` and `mod13_readiness` extended with draft cross-breakdowns (B2.3, B2.4).
- HTML "Draft Policy Decision: enabled" pill (B2.5).
- All draft i18n keys in EN + zh-TW.
- Dashboard / quarantine / report-builder GUI badges harmonized to all 7 subtypes.

If B1+B2+B3 has not shipped when this work starts, R3 tasks that build on the draft modules must be deferred or the prerequisite work pulled in first.

## 5. Decision Principles

These principles guide every task in R0/R1/R2/R3. Plans must defer to them when in doubt.

1. **Executive Summary answers management questions first.** What is the current microsegmentation maturity? Where are the biggest east-west risks? What changed since last report? What should be fixed first?
2. **Traffic Report is audience-specific.** Security Risk output helps 資安/SOC investigate dangerous east-west traffic. Network Inventory output helps 網管/平台 build label-based microsegmentation rules.
3. **Detail follows risk, not data availability.** A table belongs in the main report only if it directly drives a decision or remediation.
4. **Every module justifies its existence.** Each mod has a documented practical value, target audience, decision it supports, and a `keep` / `simplify` / `demote` / `remove` recommendation.
5. **Every section needs a reader guide.** Before charts/tables, the report explains what this section answers, what abnormal signals look like, how to interpret the metrics, and what action to take next.
6. **Illumio terminology is exact.** `potentially_blocked`, `blocked`, `allowed`, `draft_policy_decision`, `selective`, `full`, `visibility_only` match Illumio semantics. The `potentially_` prefix means visibility/test mode (no enforcement); no prefix means enforced (selective/full).
7. **Every new user-visible string uses i18n keys.** New keys go to both `src/i18n_en.json` and `src/i18n_zh_TW.json`. Audit (`python3 scripts/audit_i18n_usage.py`) must pass A–I = 0 findings before merge.
8. **HTML is for narrative; CSV/XLSX is for raw detail.** Self-contained HTML must not carry large raw tables unless they are top-tier findings.

## 6. Shared Contracts

These contracts are referenced by all three plans. Plans must use these names and shapes verbatim.

### 6.1 `traffic_report_profile` enum

Two values only (the `combined` profile from earlier drafts is dropped to limit the test matrix and force audience selection):

```
traffic_report_profile ∈ {"security_risk", "network_inventory"}
default = "security_risk"   # preserves current risk-oriented behavior for legacy callers
```

Backward compatibility: callers that omit the parameter receive `security_risk`. CLI/GUI/API surfaces add the parameter as optional with the default value. Existing test fixtures keep working without change.

### 6.2 `detail_level` enum

```
detail_level ∈ {"executive", "standard", "full"}
default = "standard"   # preserves usefulness while reducing noise
```

`detail_level` controls depth (which sections render, how many rows in tables). `traffic_report_profile` controls audience (which narrative and which sections are even relevant). The two axes are orthogonal — Traffic supports 6 combinations (2 × 3); Audit/Policy-Usage/VEN support 3 combinations (1 × 3).

### 6.3 `section_guidance` schema

A new module `src/report/section_guidance.py` exports a registry mapping module-id → guidance fields. Each entry:

```python
{
    "module_id": "mod03_uncovered_flows",            # str
    "purpose_key": "rpt_guidance_mod03_purpose",     # i18n key
    "watch_signals_key": "rpt_guidance_mod03_signals",
    "how_to_read_key": "rpt_guidance_mod03_how",
    "recommended_actions_key": "rpt_guidance_mod03_actions",
    "primary_audience": "security",                  # security|network|platform|app_owner|executive|mixed
    "profile_visibility": ["security_risk", "network_inventory"],  # list of profiles where this section appears
    "min_detail_level": "standard",                  # executive|standard|full — section visible at this depth and above
}
```

Render rules (in HTML exporters):
- `executive`: render only `purpose` + top 1–2 `recommended_actions` lines, in a tight box at the section header.
- `standard` and `full`: render all four fields in a guidance card before the section content.

### 6.4 KPI naming table

To prevent KPI sprawl and ensure dashboard consumers can rely on stable names, the executive summary uses exactly these KPIs.

**Security Risk Traffic Report (6 KPIs):**

| Field | Source | Display label key |
|-------|--------|-------------------|
| `microsegmentation_maturity` | derived from coverage + enforcement | `rpt_kpi_seg_maturity` |
| `active_allow_coverage` | `mod02_policy_decisions.allowed_pct` | `rpt_kpi_active_allow` |
| `pb_uncovered_exposure` | `mod03_uncovered_flows.pb_count` | `rpt_kpi_pb_exposure` |
| `blocked_flows` | `mod02_policy_decisions.blocked_count` | `rpt_kpi_blocked_flows` |
| `high_risk_lateral_paths` | `mod15_lateral_movement.high_risk_path_count` | `rpt_kpi_lateral_paths` |
| `top_remediation_action` | `attack_posture.action_matrix.top1` | `rpt_kpi_top_action` |

**Network Inventory Traffic Report (6 KPIs):**

| Field | Source | Display label key |
|-------|--------|-------------------|
| `observed_apps_envs` | distinct count from labels | `rpt_kpi_obs_apps` |
| `known_dependency_coverage` | known label-pair flows / total | `rpt_kpi_dep_coverage` |
| `label_completeness` | workload label fill rate | `rpt_kpi_label_complete` |
| `rule_candidate_count` | `mod_ringfence.candidate_rules_count` (or rollout if ringfence not yet shipped) | `rpt_kpi_rule_candidates` |
| `unmanaged_unknown_dependencies` | `mod08_unmanaged_hosts.count` + unknown-label flows | `rpt_kpi_unmanaged_deps` |
| `top_rule_building_gap` | derived: highest-volume label pair lacking a candidate rule | `rpt_kpi_top_gap` |

Backward-compatible aliases: legacy field name `staged_coverage` is renamed in display to `pb_uncovered_exposure`, but the `metadata.json` export keeps `staged_coverage` as a deprecated alias for one release cycle. Removal scheduled for v3.21.

### 6.5 JSON snapshot schema (R3.4)

For the Change Impact module:

```
Path: reports/snapshots/traffic/<YYYY-MM-DD>.json
```

```json
{
  "schema_version": 1,
  "report_type": "traffic",
  "profile": "security_risk",
  "generated_at": "2026-04-25T08:00:00Z",
  "query_window": {"start": "2026-04-18", "end": "2026-04-25"},
  "kpis": {
    "microsegmentation_maturity": 0.62,
    "active_allow_coverage": 0.71,
    "pb_uncovered_exposure": 1234,
    "blocked_flows": 87,
    "high_risk_lateral_paths": 14,
    "top_remediation_action": {"code": "QUARANTINE", "count": 3}
  },
  "policy_changes_since_previous": []
}
```

Storage details:
- One file per (report_type, profile, date). Same date overwrites.
- Retention: configurable via `report.snapshot_retention_days` (default 90). Cleanup runs at end of each report generation.
- Schema is versioned; readers must check `schema_version` and fall back gracefully.
- Snapshots are KPI-only — no raw flow data, no PII. Safe for git-tracking if user opts in (default: gitignored under `reports/`).

### 6.6 Report-section disposition map

This map (refined from the original R0.3 table) is the authoritative recommendation that R0/R1/R2 work follows. The `Affected by B2?` column flags modules that B2 (policy-decision-alignment) already touches; tasks must coordinate with B2 deliverables.

| Module | Practical Value (1-5) | Disposition | Profile visibility | Affected by B2? |
|--------|----------------------:|-------------|-------------------|-----------------|
| `mod01_traffic_overview` | 3 | simplify | both | no |
| `mod02_policy_decisions` | 5 | keep-profile-specific | both | **yes (B2.3)** |
| `mod03_uncovered_flows` | 5 | keep-main | both | no (PB wording fix in R1.1) |
| `mod04_ransomware_exposure` | 5 | keep-profile-specific | security_risk | no |
| `mod05_remote_access` | 2 | merge into mod15 | — | no |
| `mod06_user_process` | 3 | conditional | both, conditional on data | no |
| `mod07_cross_label_matrix` | 4 | keep-profile-specific | network_inventory primary; security_risk filtered | no |
| `mod08_unmanaged_hosts` | 5 | keep-main | both | no |
| `mod09_traffic_distribution` | 2 | appendix | both, appendix | no |
| `mod10_allowed_traffic` | 4 | keep-profile-specific | both, with risk-filtered view in security_risk | no |
| `mod11_bandwidth` | 3 | conditional | both, conditional on anomaly | no |
| `mod12_executive_summary` | 5 | redesign | both, profile-specific KPIs | no |
| `mod13_readiness` | 5 | keep-main | both | **yes (B2.4)** |
| `mod14_infrastructure` | 5 | keep-profile-specific | both | no |
| `mod15_lateral_movement` | 5 | keep-profile-specific | security_risk primary | no |
| `attack_posture` | 5 | keep-supporting | both | no |
| `mod_draft_summary` (B2.2) | 5 | keep-main | both | **shipped by B2** |
| `mod_draft_actions` (R3.1) | 5 | keep-main | security_risk primary | depends on B2 |
| `mod_enforcement_rollout` (R3.2) | 5 | keep-main | both | depends on B2 |
| `mod_ringfence` (R3.3) | 5 | keep-main | network_inventory primary | depends on B2 |
| `mod_change_impact` (R3.4) | 4 | keep-main | both | no |
| `mod_exfiltration_intel` (R3.5) | 4 | conditional | security_risk | no |
| `audit_mod00_executive` | 4 | keep-main | n/a | no |
| `audit_mod01_health` | 4 | keep-main | n/a | no |
| `audit_mod02_users` | 3 | conditional | n/a | no |
| `audit_mod03_policy` | 5 | keep-main | n/a | no |
| `audit_mod04_correlation` | 5 | keep-main | n/a | no (Change Impact builds on top in R3.4) |
| `pu_mod00_executive` | 4 | redesign | n/a | no |
| `pu_mod01_overview` | 3 | simplify | n/a | no |
| `pu_mod02_hit_detail` | 4 | appendix/main-summary | n/a | no |
| `pu_mod03_unused_detail` | 5 | keep-main | n/a | no |
| `pu_mod04_deny_effectiveness` | 5 | keep-main | n/a | no |
| VEN status generator | 5 | keep-main | n/a | no |

## 7. Phase Outlines

### 7.1 Phase R0+R1 — Semantics, Reader Guide, Profile Split

**Plan:** `docs/superpowers/plans/2026-04-25-report-r01-semantics-and-profiles.md`
**Target tag:** `v3.18.0-report-semantics`
**Branch suggestion:** `feat/report-r01-semantics`

Foundation work that fixes incorrectness and reshapes the Traffic report's audience model. Must ship before R2 (compression assumes new sections exist) and R3 (new modules consume the profile axis).

Task groups:
- R0.1 inventory verification against `docs/report_module_inventory_zh.md`.
- R0.2 build `section_guidance.py` registry skeleton + i18n key infrastructure.
- R0.3 add reader-guide rendering to all four HTML exporters.
- R0.4 populate guidance content for high-priority modules (12 modules listed in original R0.4).
- R1.1 PB semantic correction across mod03, mod12, mod13, html_exporter, both Security Rules Reference docs, and rule descriptions for B003 + L008.
- R1.2 Executive Summary 6+6 KPI redesign, with Top-3-Actions block.
- R1.3 Date Range fallback in report_generator + mod01.
- R1.4 Traffic profile split (security_risk + network_inventory; share one analysis pipeline; exporter selects sections + ordering).

### 7.2 Phase R2 — Content Compression, Density Modes, XLSX

**Plan:** `docs/superpowers/plans/2026-04-25-report-r02-compression-and-appendix.md`
**Target tag:** `v3.19.0-report-compact`
**Branch suggestion:** `feat/report-r02-compact`
**Depends on:** R1 merged (sections must exist with new layout before being demoted).

Task groups:
- R2.1 `detail_level` enum + per-section gating.
- R2.2 Demote low-signal Traffic sections to collapsible Appendix (mod06, mod07 detail rows, mod09).
- R2.3 Plotly JS load-once optimization (one bundle per HTML, charts use `include_plotlyjs=False`).
- R2.4 XLSX real-content tasks split per report type (4 tasks: Traffic, Audit, Policy Usage, VEN).

### 7.3 Phase R3 — New High-Value Analyses

**Plan:** `docs/superpowers/plans/2026-04-25-report-r03-new-analysis.md`
**Target tag:** `v3.20.0-report-intelligence`
**Branch suggestion:** `feat/report-r03-intelligence`
**Depends on:** R1 merged + policy-decision-alignment B2 shipped (provides `mod_draft_summary`).

Task groups:
- R3.1 `mod_draft_actions.py` — Override Deny remediation suggestions, Allowed Across Boundary review workflow, what-if assumptions (does NOT duplicate B2.2).
- R3.2 `mod_enforcement_rollout.py` — ranked rollout plan consuming `mod_draft_summary` + readiness signals.
- R3.3 `mod_ringfence.py` — per-app dependency profile, candidate allowlist, boundary deny suggestions.
- R3.4 `mod_change_impact.py` + JSON snapshot store + retention worker. Snapshots in `reports/snapshots/traffic/<YYYY-MM-DD>.json`.
- R3.5 `mod_exfiltration_intel.py` — managed→unmanaged exfil, optional threat-intel CSV/API hook (default off).

## 8. Validation & Verification (cross-cutting)

Each plan must include these gates at phase boundaries:

- `python3 -m pytest tests/ -q` — full suite passes.
- `python3 scripts/audit_i18n_usage.py` — A–I = 0 findings.
- `python3 -m pytest tests/test_i18n_audit.py tests/test_i18n_quality.py -q` — i18n suite passes.
- New tests cover: PB semantics (R1.1), profile output differences (R1.4), HTML size reduction (R2.3), XLSX content presence (R2.4), each new R3 module behavior, snapshot read/write (R3.4).

**Baseline:** as of brainstorming session, suite is 582 passed + 1 skipped (post-Phase 15). Plans must record their own baseline at start and target at end.

**Backward compatibility checks:**
- Run `grep -rn "Staged Coverage\|staged_coverage" src/ reports/` before R1.1 to enumerate consumers; preserve `staged_coverage` JSON field as deprecated alias.
- Run sample report generation before/after each phase, diff metadata.json output to confirm only intended fields changed.

## 9. Rollback Strategy

- Each phase ships on its own branch and gets its own tag (`v3.18` / `v3.19` / `v3.20`). If any phase regresses production, revert to previous tag.
- R1 semantic changes that break a dashboard consumer: keep the old field name internally for one release; swap only the rendered label.
- R2.3 single-bundle Plotly: if reports break offline, revert R2.3 alone and keep R2.1+R2.2+R2.4.
- R3.1 `mod_draft_actions` increases API runtime significantly: gate behind `compute_draft=True` (already required), and add `report.draft_actions_enabled` config flag default-true (so users can disable if needed).
- R3.4 snapshot store: if disk pressure becomes an issue, retention can drop to 30 days via config; module degrades to "no comparison available" gracefully.

## 10. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Profile split duplicates analysis logic | Maintenance burden | Strict rule: shared modules produce normalized DataFrames; only exporter selects sections per profile. Reviewer must reject any duplicated analysis code. |
| `detail_level=executive` removes too much context | Users miss data they expect | Always render `purpose` and top remediation; never render an empty section. Document the executive contract. |
| KPI rename breaks dashboards | Dashboard alarms / API consumers fail | Step 1 of R1.2 audits dashboard / API consumers; preserve `staged_coverage` alias for one release. |
| Snapshot store accumulates files | Disk usage | Retention worker runs at end of each report generation; default 90 days; configurable. |
| Plotly single-bundle breaks offline reports | Reports unusable when not online | Keep `include_plotlyjs="inline"` for the FIRST chart only; subsequent charts reuse the loaded global. Test with `file://` URL scheme. |
| R3 modules depend on B2 not yet shipped | R3 tasks blocked | Plan header pins prerequisite version; if B2 slips, R3 plan execution waits. |
| `mod_draft_actions` overlap with B2 reports | Wasted effort | This spec defines clear scope: B2.2 = counts + top pairs; R3.1 = remediation actions + workflow. Reviewers enforce the boundary. |

## 11. Out-of-Spec / Future Work

- Persona-aware GUI report builder (currently profile is a CLI/API/dropdown parameter).
- Snapshot store extension to Audit / Policy Usage / VEN reports.
- Cross-report aggregated dashboard.
- Threat intel feed integration (R3.5 only adds the hook; the actual feed source is out of scope).
- ML-based anomaly detection on flow patterns.
