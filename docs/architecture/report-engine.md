---
title: Report Engine Architecture
audience: [developer]
last_verified: 2026-05-15
verified_against:
  - src/report/
  - src/report/analysis/
  - src/report/parsers/
  - src/report/exporters/
  - src/report/rules/
  - commit 92143a6 (ReportLab removal plan)
  - commit 268d055
related_docs:
  - overview.md
  - ../user-guide/reports.md
  - ../reference/cli.md
  - i18n-contract.md
---

> **[English](report-engine.md)** | [繁體中文](report-engine_zh.md)
> 📍 [INDEX](../INDEX.md) › Architecture › Report Engine
> 🔍 Last verified **2026-05-15** against commit `268d055` — see frontmatter for sources

# Report Engine Architecture

This document covers the developer-facing internals of `src/report/` (72 files).
For operator-level usage (running reports, output locations, email delivery) see
[Reports User Guide](../user-guide/reports.md).

---

## Pipeline stages

The engine runs the same five-stage pipeline regardless of data source (API or
CSV). Each generator class (`ReportGenerator`, `AuditGenerator`,
`PolicyUsageGenerator`, `VenStatusGenerator`) drives its own variant.

```
┌──────────┐     ┌─────────┐     ┌──────────┐     ┌────────┐     ┌──────────┐
│  Fetch   │────▶│  Parse  │────▶│ Analyze  │────▶│ Render │────▶│  Export  │
└──────────┘     └─────────┘     └──────────┘     └────────┘     └──────────┘
```

| Stage | Input | Output | Key code |
|-------|-------|--------|----------|
| **Fetch** | date range + optional filters | raw JSON flow list or CSV path | `ReportGenerator._fetch_traffic()` |
| **Parse** | raw JSON list / CSV file | Unified DataFrame (shared schema) | `src/report/parsers/` |
| **Analyze** | Unified DataFrame | `module_results` dict + `findings` list | `_run_pipeline()` → `_run_modules()` + `RulesEngine.evaluate()` |
| **Render** | `module_results` + `findings` | HTML string with embedded charts/CSS | `HtmlExporter.export()` |
| **Export** | rendered HTML / module_results | `.html`, `.xlsx`, `.csv` files on disk | `ReportGenerator.export(fmt=...)` |

**Fetch** supports three modes selected automatically:

- `"api"` — live PCE API call via `api_client.fetch_traffic_for_report()`
- `"cache"` — fully served from `cache_reader` (snapshot store)
- `"mixed"` — API fills the uncovered gap, merged with cached tail

**Analyze** runs in two sub-passes:

1. `RulesEngine.evaluate(df)` — security rule findings (see [Rules engine](#rules-engine))
2. `_run_modules(df, findings)` — 15+ analysis modules run sequentially; `mod12`
   (executive summary) always runs last and depends on all other results.

---

## Parsers

Location: `src/report/parsers/`

| File | Purpose |
|------|---------|
| `api_parser.py` | Converts PCE API JSON flow records into the Unified DataFrame; reuses `calculate_mbps()` / `calculate_volume_mb()` from `src.analyzer` so bandwidth logic stays consistent with the monitoring engine. |
| `csv_parser.py` | Reads a CSV exported from the Illumio PCE UI and normalises column names to the Unified DataFrame schema. |
| `validators.py` | Schema validation and coercion: checks required columns and compatible dtypes so both parsers feed identical structure to analysis modules. |

Both parsers produce the same **Unified DataFrame schema** — every analysis
module consumes this schema without knowing the original data source.

---

## Analysis modules

Location: `src/report/analysis/`

Modules are registered in `TRAFFIC_MODULES` (in `src/report/analysis/__init__.py`)
and loaded lazily via `importlib` at runtime. `get_traffic_modules()` returns the
active list; `get_summary_module()` returns `mod12`.

### Traffic flow modules (mod01–mod15)

| Module | Entry function | Computes |
|--------|---------------|---------|
| `mod01_traffic_overview.py` | `traffic_overview` | Overall flow counts, top talkers, protocol breakdown |
| `mod02_policy_decisions.py` | `policy_decision_analysis` | Allow/deny/potentially-blocked distribution |
| `mod03_uncovered_flows.py` | `uncovered_flows` | Flows with no matching policy rule |
| `mod04_ransomware_exposure.py` | `ransomware_exposure` | Per-port ransomware risk scoring |
| `mod05_remote_access.py` | _(consolidated into mod15)_ | Remote access paths — file kept for reference |
| `mod06_user_process.py` | `user_process_analysis` | User-space process-level traffic breakdown |
| `mod07_cross_label_matrix.py` | `cross_label_flow_matrix` | Cross-environment label-to-label flow matrix |
| `mod08_unmanaged_hosts.py` | `unmanaged_traffic` | Flows involving unmanaged (VEN-less) hosts |
| `mod09_traffic_distribution.py` | `traffic_distribution` | Traffic distribution by app/env/location |
| `mod10_allowed_traffic.py` | `allowed_traffic` | Breakdown of explicitly allowed flow patterns |
| `mod11_bandwidth.py` | `bandwidth_analysis` | Bandwidth and data volume aggregation |
| `mod12_executive_summary.py` | `executive_summary` | Aggregates all module results into KPIs + grade |
| `mod13_readiness.py` | `enforcement_readiness` | Per-app/env enforcement mode readiness scoring |
| `mod14_infrastructure.py` | `infrastructure_scoring` | Infrastructure asset type scoring |
| `mod15_lateral_movement.py` | `lateral_movement_risk` | Lateral movement reachability graph analysis |
| `mod_change_impact.py` | — | Change-impact diff between two report snapshots |
| `mod_draft_actions.py` | — | Draft policy action recommendations |
| `mod_draft_summary.py` | `analyze` | Summary of draft policy decision flows |
| `mod_ringfence.py` | `analyze` | Ring-fence segmentation gap detection |
| `attack_posture.py` | — | Shared attack posture helpers used by mod12 |

### Policy usage sub-modules (`analysis/policy_usage/`)

| File | Computes |
|------|---------|
| `pu_mod00_executive.py` | Executive KPIs for policy usage report |
| `pu_mod01_overview.py` | Policy rule hit overview |
| `pu_mod02_hit_detail.py` | Per-rule hit detail breakdown |
| `pu_mod03_unused_detail.py` | Unused rule detail list |
| `pu_mod04_deny_effectiveness.py` | Deny rule effectiveness metrics |
| `pu_mod05_draft_pd.py` | Draft policy-decision coverage |

### Audit sub-modules (`analysis/audit/`)

| File | Computes |
|------|---------|
| `audit_mod00_executive.py` | Executive KPIs for audit log report |
| `audit_mod01_health.py` | PCE health event summary |
| `audit_mod02_users.py` | User action breakdown |
| `audit_mod03_policy.py` | Policy change event analysis |
| `audit_mod04_correlation.py` | Cross-event correlation |
| `audit_risk.py` | Risk scoring helpers |

---

## Rules engine

Location: `src/report/rules/` + `src/report/rules_engine.py`

### Rule file structure

Each rule file in `src/report/rules/` defines a single rule class that inherits
from `_base.Finding` (dataclass) and optionally `_DraftPdRuleMixin`:

```
_base.py                         — Finding dataclass + _DraftPdRuleMixin base
r01_draft_deny_detected.py
r02_override_deny_detected.py
r03_visibility_boundary_breach.py
r04_allowed_across_boundary.py
r05_draft_reported_mismatch.py
```

`_DraftPdRuleMixin.needs_draft_pd() → bool` signals that the rule requires the
`draft_policy_decision` column in the DataFrame.

### Evaluation

`RulesEngine.evaluate(df) → list[Finding]` in `rules_engine.py` runs two
categories of built-in rules:

**Behavioural rules (`_b001`–`_b009`)** — ranked CRITICAL / HIGH / MEDIUM:

| Rule | Finding |
|------|---------|
| `_b001_ransomware_critical` | Ransomware-port traffic within a /24 subnet |
| `_b002_ransomware_high` | Ransomware-port traffic across subnets |
| `_b003_ransomware_medium_uncovered` | Ransomware-port flows with no policy |
| `_b004_unmanaged_high_activity` | Unmanaged hosts with high flow volume |
| `_b005_low_policy_coverage` | Policy coverage below configured threshold |
| `_b006_lateral_movement` | Lateral movement reachability graph |
| `_b007_user_high_destinations` | User processes reaching many destinations |
| `_b008_bandwidth_anomaly` | Statistical bandwidth outliers |
| `_b009_cross_env_volume` | High data volume crossing environment boundaries |

**Library/protocol rules (`_l001`–`_l008`)** — protocol and topology checks:

| Rule | Finding |
|------|---------|
| `_l001_cleartext_protocols` | Cleartext credential-carrying protocols (Telnet, FTP, …) |
| `_l002_legacy_discovery_protocols` | Legacy broadcast/discovery protocols |
| `_l003_database_port_wide_exposure` | Database ports reachable from broad scope |
| `_l004_cross_env_database_access` | Database access crossing environment boundaries |
| `_l005_identity_infrastructure_exposure` | AD/LDAP/Kerberos wide exposure |
| `_l006_high_reachability_lateral_path` | BFS-based lateral reachability path |
| `_l007_unmanaged_targeting_critical_services` | Unmanaged hosts hitting critical ports |
| `_l008_enforcement_mode_gap` | Weak enforcement mode near critical services |

Each rule method returns `Optional[Finding]`. The engine collects non-None results
and passes the full `findings` list to all analysis modules.

---

## Exporters

Location: `src/report/exporters/`

| File | Purpose |
|------|---------|
| `html_exporter.py` | Main HTML report renderer; embeds charts, tables, CSS, nav sidebar, cover page |
| `audit_html_exporter.py` | HTML renderer for audit log reports |
| `policy_usage_html_exporter.py` | HTML renderer for policy usage reports |
| `ven_html_exporter.py` | HTML renderer for VEN status reports |
| `csv_exporter.py` | Flattens `module_results` into per-module CSV files bundled in a ZIP |
| `xlsx_exporter.py` | Writes per-module Excel sheets via `openpyxl` |
| `table_renderer.py` | Shared HTML table rendering; handles wide-table splitting |
| `chart_renderer.py` | Renders Plotly charts as interactive HTML divs |
| `cover_page.py` | Generates the cover page HTML (title, grade, date, maturity score) |
| `report_css.py` | All report CSS including `@media print` and `@page` rules |
| `report_i18n.py` | Report-level i18n helpers (label lookup, language routing) |
| `_exec_summary.py` | Executive summary section builder |
| `code_highlighter.py` | Syntax-highlight code blocks in report output |
| `grade_colors.py` | Shared semantic grade colour palette (A/B green, C orange, D/F red) |

### Export formats

`ReportGenerator.export(result, fmt=...)` accepts:

| `fmt` | Output |
|-------|--------|
| `'html'` | Single `.html` file |
| `'pdf'` | Alias for `'html'` — PDF via browser print (see below) |
| `'xlsx'` | `.xlsx` via `openpyxl` |
| `'csv'` | Per-module CSVs bundled in a `.zip` |
| `'all'` | HTML + XLSX + CSV |

### PDF generation — current path

**ReportLab has been removed** (plan documented in commit `92143a6`). PDF output
is produced by the browser's native `window.print()` triggered by the
"Print / PDF" button rendered in the HTML nav bar
(`html_exporter.py:593`). The `.html` file carries a complete `@media print`
stylesheet in `report_css.py` that controls page breaks, margins, and table
layout for A4 output.

No server-side PDF library (WeasyPrint, pdfkit, wkhtmltopdf) is used in the
current codebase.

> **TODO:** Confirm whether a headless-browser PDF path (Playwright / Chromium
> headless) was added after commit `92143a6`. The current code only shows
> `window.print()` in `html_exporter.py`.

A `.metadata.json` sidecar is written alongside every HTML and XLSX output by
`_write_report_metadata()`.

---

## Print layout & wide-table handling

All print layout lives in `src/report/exporters/report_css.py` under `@media print`
and `@page` rules.

### Page rules

```css
@page { /* A4 landscape */ }
@page { /* A4 portrait */ }
@media print {
  section              { page-break-before: always; }
  section#summary      { page-break-before: avoid; }
  section.report-cover { page-break-before: avoid !important; page-break-after: always; }
  tr                   { page-break-inside: avoid; }
  .chart-container     { page-break-inside: avoid; overflow: hidden; }
  .finding-card        { page-break-inside: avoid; }
}
```

### Wide-table splitting (commit `f935717`)

Tables with many columns (`part_b_per_port` in mod04, `app_env_scores` in mod13,
`top_apps` in mod14) are split into 2–3 vertically-stacked sub-tables sharing an
anchor column, eliminating horizontal scrolling in print. Each sub-table gets a
`.subtable-label` heading. Eight i18n keys were added for the sub-table labels.

### CSS specificity fix (commit `9db21d5`)

`autoFitColumns()` in JavaScript sets `data-auto-fitted="true"` on tables, giving
the rule `.report-table[data-auto-fitted=true]` specificity `(0,2,0)`. The print
override uses `table-layout: auto !important` to win over the JS-applied
`table-layout: fixed`.

### Print hardening history

| Commit | Fix |
|--------|-----|
| `0eabc30` | `overflow-wrap: break-word` instead of `anywhere` for print tables |
| `ac0ae02` | Dropped `table-layout: fixed` from wide tables globally |
| `36f46d8` | Applied `table-layout: fixed` only to wide tables |
| `caa1349` | Footer hidden in print (cover page already provides title/date) |
| `959ca91` | JS inline table widths overridden with `!important` in print |

---

## Caching of intermediate results

### 1. Traffic fetch cache (`cache_reader`)

`ReportGenerator` accepts an optional `cache_reader` constructor argument.
`_fetch_traffic()` calls `cache_reader.cover_state("traffic", start, end)` and
selects one of three paths:

| `cover_state` result | Behaviour |
|---------------------|-----------|
| `"full"` | Returns raw + agg flows from cache; no API call |
| `"partial"` | Hybrid: API fills `[start, cache_start)` gap, merged with cached tail; source tagged `"mixed"` or `"cache"` |
| anything else | Full live API fetch |

### 2. KPI snapshot stores

Two lightweight JSON stores persist KPIs between runs:

- **`snapshot_store.py`** — KPI-only JSON snapshots for Change Impact analysis.
  Key functions: `write_snapshot`, `list_snapshots`, `read_latest`, `cleanup_old`.
- **`trend_store.py`** — KPI trend history per report type.
  Key functions: `save_snapshot`, `load_previous`, `compute_deltas`,
  `build_kpi_dict_from_metadata`.

### 3. In-run caches

- `mod15_lateral_movement.py` uses `reach_cache: dict[str, dict]` during BFS
  traversal to avoid redundant graph walks within a single run.
- `policy_usage` execution context tracks `cached_rules` (async completed
  summaries reused from a prior run).

There is **no cross-run in-memory cache** — each `generate_from_*()` call
re-fetches and re-analyses from scratch unless `cache_reader` is supplied.

---

## How to add a new report module

This recipe applies to adding a new **traffic analysis module** (mod01–mod15 family).
For audit or policy-usage sub-modules follow the same pattern in the appropriate
sub-package.

1. **Find a similar module** — pick the existing module whose signature and output
   structure most resembles your new one (e.g. `mod08_unmanaged_hosts.py` for a
   host-centric module, `mod11_bandwidth.py` for a numeric aggregation module).

2. **Create the module file** — add
   `src/report/analysis/mod{NN}_{name}.py`. Implement the entry function with the
   signature `(df: pd.DataFrame, top_n: int, *, lang: str = "en") -> dict`.
   The returned dict must include at least `"title"`, `"chart_spec"` (or `None`),
   and `"table"` keys to render correctly in `HtmlExporter`.

3. **Register in `TRAFFIC_MODULES`** — add a tuple to the list in
   `src/report/analysis/__init__.py`:
   ```python
   ('modNN', 'src.report.analysis.modNN_name', 'entry_function', _call_df_n),
   ```
   Choose the appropriate `_call_*` adapter: `_call_df`, `_call_df_n`,
   `_call_df_cfg_n`, or `_call_readiness` based on your function's signature.

4. **Write tests** — add `tests/report/analysis/test_modNN_name.py`. Construct a
   minimal Unified DataFrame using fixtures from existing tests and assert on output
   dict keys and data types.

5. **Add i18n keys** — add every user-visible string as a key in
   `src/i18n_en.json` and `src/i18n_zh_TW.json`. Use
   `from src.i18n import t, get_language` inside the module and pass `lang=lang`
   to every `t()` call. See [i18n Contract](i18n-contract.md).

6. **Handle wide tables** — if the module produces a table wider than ~8 columns,
   register it in `table_renderer.py` for the grouped sub-table split (see
   commit `f935717`). Add the sub-table label i18n keys to both locale files.

7. **Verify output** — run the report locally and confirm the new section appears
   in the TOC sidebar, renders correctly on screen, and page-breaks cleanly when
   printed to PDF from the browser.

---

## Related Docs
- [Architecture Overview](overview.md) — bigger picture
- [Reports User Guide](../user-guide/reports.md) — operator-level usage
- [CLI Reference](../reference/cli.md) — `report` subcommands
- [i18n Contract](i18n-contract.md) — how report labels stay in sync with language
