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
