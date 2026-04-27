# illumio_ops Status

**Version:** v3.20.0-report-intelligence  
**Branch:** main  
**Last updated:** 2026-04-27  
**Tests:** 772 passed, 1 skipped

## Completed phases

| Tag | Phase | Description |
|-----|-------|-------------|
| v3.15.0-draft-pd-rules | B1 | 5 new security rules (R01–R05) using draft_policy_decision |
| v3.16.0-draft-pd-reports | B2 | Report analysis modules for draft_pd (mod_draft_summary) |
| v3.17.0-draft-pd-gui | B3 | GUI harmonization to 7 draft_pd subtypes |
| v3.18.0-report-semantics | R0+R1 | Traffic report profiles + section_guidance + KPI redesign |
| v3.19.0-report-compact | R2 | detail_level, appendix, single-bundle Plotly |
| v3.20.0-report-intelligence | R3 | 5 new analysis modules + Change Impact snapshot store |

## R3 deliverables (v3.20.0)

- `src/report/analysis/mod_draft_actions.py` — Override Deny / Allowed Across Boundary remediation
- `src/report/analysis/mod_enforcement_rollout.py` — Rank apps by enforcement readiness
- `src/report/analysis/mod_ringfence.py` — Per-app dependency profile + candidate allow rules
- `src/report/analysis/mod_change_impact.py` — KPI comparison vs previous snapshot
- `src/report/analysis/mod_exfiltration_intel.py` — Managed→unmanaged exfil + threat intel join
- `src/report/snapshot_store.py` — JSON KPI snapshots at `reports/snapshots/<type>/<YYYY-MM-DD>_<profile>.json`
- Config: `report.snapshot_retention_days=90`, `threat_intel_csv_path`, `draft_actions_enabled`
- 27 new i18n keys (EN + zh_TW), i18n audit 0 findings

## Next

R4 or other roadmap items TBD.

---

## 2026-04-28 — Documentation rebuild complete (branch `docs-rebuild`)

- Rebuilt 10 user-facing files (README × 2, User_Manual × 2, Architecture × 2, Security_Rules_Reference × 2, Status, Task) to v3.20.0.
- 9,499 total lines across the 10 files (EN floor met for User_Manual ≥ 1700, Architecture ≥ 800, Security_Rules ≥ 700).
- EN/ZH heading-structure parity verified for all 4 doc pairs (`diff` returns empty); ZH/EN line ratio 0.99–1.00.
- Coverage gates passed: `scripts/check_doc_coverage.sh` (every report module + subcommand + bundle script), `scripts/check_doc_links.py` (zero broken local links), i18n audit (0 findings), `tests/test_i18n_audit.py` + `tests/test_i18n_quality.py` (10/10 pass).
- NotebookLM-distilled Illumio platform background added to `docs/Architecture.md` Background.1–5; raw excerpts in gitignored `docs/_notebooklm_excerpts/`.
- Latest rebuild commit: `0ee2eef` (37 commits since `ed20df0`).
- Plan: `docs/superpowers/plans/2026-04-28-documentation-rebuild.md`
- Spec: `docs/superpowers/specs/2026-04-28-documentation-rebuild-design.md`
