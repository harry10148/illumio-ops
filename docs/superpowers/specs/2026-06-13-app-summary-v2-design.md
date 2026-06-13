# App Summary v2 — Design Spec (2026-06-13)

## Goal

Evolve the existing App Summary report (single-app view, scoped by one App Label)
from a free-text, synchronous, content-thin v1 into a v2 that:

1. Lets the user **select the App Label from a real PCE-derived dropdown** instead
   of typing it free-form.
2. Aligns content to the Illumio **App Group Summary** methodology (sourced from
   the "Illumio" NotebookLM notebook): inbound/outbound services, **Security
   Policy Impact**, **per-workload enforcement state**, connection baselines.
3. Generates **asynchronously** in the GUI (job + polling) so the heavy estate
   fetch no longer times out (v1 was killed at 200s on a real PCE).

This is a v2 enrichment of the shipped App Summary, not a rewrite. The shared
report styling (`build_css` + `cover_page` + `report-shell`) landed in the
2026-06-13 report-QA batch and is reused unchanged.

## Confirmed decisions

- **Scope = "B" (align to methodology)**: v1 sections + a Security Policy Impact
  section + an Enforcement State section. NOT "C": no V-E vulnerability scoring,
  no ransomware-port audit, no agent-tampering/port-scan event log, no separate
  App-Owner/Auditor view split. (Those remain a possible v3.)
- **GUI generation is async** (job_id + polling), mirroring the traffic report's
  existing pattern. CLI and scheduler stay synchronous (no HTTP timeout there).
- **Coverage / policy-impact is derived from traffic `policy_decision`** (the
  established pattern in this tool), NOT from the dedicated
  `POST /sec_policy/rule_coverage` PCE endpoint. Simpler, no new integration.
- Per-app **drift / baseline-signature is still excluded** (carried from v1 — an
  estate signature does not align to a single-app scope).

## Grounding (verified)

| Fact | Source |
|------|--------|
| `api.get_labels(key: str)` returns labels for a dimension; `get_labels("app")` returned 18 app labels on the test PCE | api_client.py:550; live test |
| Per-workload enforcement mode comes from the workloads endpoint; `api.fetch_managed_workloads()` already wraps it (used by the policy resolver) | api_client.py; policy_resolver_report.resolve() |
| Rule/policy coverage is derived from Explorer traffic + `policy_decisions` (allowed / potentially_blocked / blocked / unknown); a dedicated `POST /api/v2/orgs/{org}/sec_policy/rule_coverage` exists but is not required | NotebookLM Illumio API guide |
| App Summary facade already fetches the estate traffic df via `ReportGenerator.fetch_traffic_df` and scopes it with `filter_app_flows`; runs mod01/02/03 + RulesEngine findings + app_baseline | app_summary_report.py |
| Traffic async pattern (job_id + daemon thread + state.json `adhoc_report_jobs` + `/api/reports/jobs/<id>` polling) already exists for the traffic report | gui/routes/reports.py (`_run_adhoc`), dashboard.js (`_pollTrafficJob`) |
| Standalone exporters use the shared shell via `build_css(type)` + `build_cover_page`; App Summary exporter already converted | app_summary_html_exporter.py |

## Architecture

No new analysis engine. The `AppSummaryReport` facade gains one additional
data fetch (managed workloads, for enforcement state) and two derived result
blocks (policy impact, enforcement summary). A new GUI labels endpoint feeds the
app dropdown. The GUI generate path is refactored to the async job pattern.

### A. App selection (API-driven)

- **New backend endpoint** `GET /api/labels?key=app` (reports or a shared GUI
  blueprint): calls `api.get_labels("app")`, returns
  `{"ok": true, "labels": ["DemoApp", "ERP", ...]}` (sorted, de-duplicated by
  value). Short in-process cache (e.g. 60s) to avoid hammering the PCE on every
  modal open. Optional `key` param so the same endpoint can serve `env` too.
- **GUI modal** (`index.html` + `dashboard.js`): the `m-gen-app` field becomes a
  `<select>` populated on modal open from the endpoint (loading state while it
  fetches); `m-gen-env` becomes an optional `<select>` (blank = all envs). If the
  endpoint fails, fall back to a free-text `<input>` so generation still works.
- **CLI** (`cli/report.py`): `--app` stays free-text (no dropdown in a CLI), but
  add a soft validation — if the value isn't among `get_labels("app")`, print a
  warning with the closest matches and still proceed (lab PCEs / typos shouldn't
  hard-fail).
- **Scheduler**: unchanged — stores the `app` (and optional `env`) value already.

### B. Content sections

Order and content of the exported report:

1. **Cover + KPI row** — existing KPIs (flow_count / inbound / outbound /
   coverage%) **plus** an enforcement KPI: share of this app's workloads in
   full/selective enforcement (e.g. "6 / 9 enforced").
2. **Inbound Services Baseline** — existing (`app_baseline.inbound`).
3. **Outbound Dependencies** — existing (`app_baseline.outbound`).
4. **Security Policy Impact** (new section) — for this app's scoped flows:
   - The `policy_decision` distribution: allowed / potentially_blocked / blocked
     / unknown (counts + a small bar).
   - **Rule coverage %** = `allowed ÷ total` (allowed = a rule already permits the
     flow). The headline impact line uses `potentially_blocked` (flows allowed
     today only because the workload is in visibility/test mode — i.e. **no rule
     covers them, so they would be dropped under Full Enforcement**): "if moved to
     Full Enforcement, **N flows would be blocked**" where N = potentially_blocked
     count. `blocked` flows are already denied; shown separately, not in N.
   - Derived from mod02 (policy-decision distribution) on the scoped df — no new
     fetch. (mod03's uncovered-flow detail can feed a "top would-be-blocked
     flows" sub-list.)
5. **Enforcement State** (new section) — table of this app's managed workloads
   with their `enforcement_mode` (idle / visibility_only / selective / full) and
   a one-line summary. Requires the new `fetch_managed_workloads` call, filtered
   to workloads carrying this app label (+ optional env).
6. **Findings involving this app** — existing (RulesEngine on the scoped df).
7. **Appendix / data scope** — existing; note that the inbound/outbound baselines
   are the connection baseline an owner can turn into rules.

Connection "normalcy" is conveyed by the existing baselines (optionally a light
"unusual peer/port" flag); no separate drift signature.

The existing empty-state behavior (valid single-page report with the
`rpt_app_empty` note) is preserved for apps with no observed flows.

### C. Async delivery (GUI)

Refactor `POST /api/app_report/generate` to mirror the traffic report:
- Validate synchronously (required app, lang) and return 400 on bad input.
- Create `job_id`, run `AppSummaryReport.run(...)` in a daemon thread, persist
  job state to `state.json` (reuse the existing `adhoc_report_jobs` store +
  `/api/reports/jobs/<job_id>` status endpoint from the traffic async work).
- Frontend `_doGenerateAppSummary` POSTs, gets `job_id`, polls the job endpoint
  (reuse `_pollTrafficJob`'s mechanism), then runs the success/empty/error path.
- CLI `run()` and the scheduler branch stay synchronous (unchanged).

### D. Data sources

| Section | Source |
|---------|--------|
| Inbound/outbound baseline, policy impact, coverage%, findings | existing scoped traffic df (`fetch_traffic_df` → `filter_app_flows`) + mod01/02/03 + RulesEngine |
| Enforcement state | **new**: `api.fetch_managed_workloads()`, filtered to this app's workloads |
| App dropdown | **new endpoint**: `api.get_labels("app")` (and `"env"`) |
| Styling | shared `build_css("app_summary")` + `cover_page` (already in place) |

## Components / file touch points

- `src/report/app_summary_report.py` — facade: add workloads fetch + filter;
  add `policy_impact` + `enforcement` result blocks to `build()`.
- `src/report/analysis/mod_app_baseline.py` (or a new small pure module) —
  pure functions for the policy-impact summary and enforcement summary
  (kept testable, independent of the facade).
- `src/report/exporters/app_summary_html_exporter.py` — render the two new
  sections (reuse `.card`/`.report-table`/`.kpi-card`).
- `src/gui/routes/reports.py` — new `GET /api/labels` endpoint; refactor
  `/api/app_report/generate` to async (job_id + polling).
- `src/static/js/dashboard.js` — app/env `<select>` population + loading/fallback;
  async polling in `_doGenerateAppSummary`.
- `src/templates/index.html` — `m-gen-app` / `m-gen-env` become `<select>`.
- `src/cli/report.py` — soft app-label validation.
- `src/i18n_en.json`, `src/i18n_zh_TW.json` — new section/label keys (dual-file,
  glossary-clean, App/Policy/enforcement terms English in zh).
- Tests: `tests/test_mod_app_baseline.py` (policy-impact + enforcement pure fns),
  `tests/test_app_summary_report.py` (facade build adds the new blocks),
  `tests/test_gui_app_report_generate.py` (async job flow + labels endpoint),
  exporter section assertions.

## Error handling

- Labels endpoint failure → frontend falls back to a free-text app input; CLI
  validation degrades to a warning.
- Workloads fetch failure → the Enforcement State section renders a "data
  unavailable" note (the rest of the report still generates).
- Empty app (no flows) → existing empty-state page (unchanged).
- Async job failure → existing job error path (toast + job status = error).

## Out of scope (possible v3)

- V-E vulnerability exposure scoring per workload.
- Ransomware-port (RDP/SMB/Telnet) audit table.
- Operational/incident event log (agent.tampering, port scans, heartbeat).
- Separate App-Owner vs Auditor rendered views.
- Per-app drift / baseline signature.
- Calling the dedicated `sec_policy/rule_coverage` PCE endpoint (we derive).

## Success criteria

- GUI: open the App Summary modal → app dropdown lists the PCE's app labels →
  pick one → generate runs async (no timeout) → report opens with all sections,
  including Policy Impact and Enforcement State, in the shared styling.
- The report content matches the App Group Summary intent (inbound/outbound
  baseline + policy impact + enforcement + findings).
- CLI and scheduler still produce the same report synchronously.
- Verified live on the test machine against a real app label.
