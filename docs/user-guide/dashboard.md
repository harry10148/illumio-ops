---
title: Dashboard
audience: [operator]
last_verified: 2026-05-15
verified_against:
  - src/gui/routes/dashboard.py
  - src/templates/index.html
  - src/static/js/dashboard.js
  - src/static/js/dashboard_v2.js
  - commit 519cf85
related_docs:
  - reports.md
  - alerts-and-quarantine.md
  - multi-pce.md
  - ../architecture/i18n-contract.md
---

> 🌐 **[English](dashboard.md)** | **[繁體中文](dashboard_zh.md)**
> 📍 [INDEX](../INDEX.md) › User Guide › Dashboard
> 🔍 Last verified **2026-05-15** against commit `519cf85` — see frontmatter for sources

# Dashboard

The Dashboard tab (`#p-dashboard`) is the primary real-time view of the connected PCE instance.
It shows live KPI cards, Plotly charts, a traffic-report snapshot panel, and sub-tabs for
Traffic Analyzer, Workload Search, and Legacy queries.

---

## Overview

The Dashboard displays the health and activity state of the PCE polled by Illumio PCE Ops.
It does **not** auto-navigate away; the operator stays on whichever tab they last selected.

**Auto-refresh:** Plotly charts refresh every 60 seconds via `setInterval(loadDashboardCharts, 60000)`.
Live KPI cards (`#d-rules`, `#d-health`, etc.) are populated on page load and whenever
`/api/status` or `/api/dashboard/snapshot` returns a new response. There is no page-level
polling loop for the KPI row; values update on initial load and on explicit user actions.

**Language switching:** The UI language is resolved from `window._uiLang` which is set in
`dashboard.js` from the `language` field of the API response:

```js
window._uiLang = (d.language === 'zh_TW') ? 'zh_TW' : 'en';
```

All `data-i18n` attributes are re-rendered client-side via `applyI18n()` on every snapshot
response. Snapshot KPI labels that carry a `label_key` are retranslated server-side at request
time (see `src/gui/routes/dashboard.py` lines 32–38 and the
[i18n Contract](../architecture/i18n-contract.md) for the retranslation pattern).

---

## KPI cards

The main `.cards` grid (`<div class="cards">` inside `#p-dashboard`) contains six `.card`
elements. Each has a `.label` (i18n key) and a `.value` (DOM id updated by JS).

| Label (i18n key) | DOM id | What it tracks |
|---|---|---|
| Rules (`gui_dashboard_rules`) | `d-rules` | Count of active rules in the connected PCE |
| Health Rule (`gui_card_health_rule`) | `d-health` | Whether the PCE health-check rule is passing (`ON` / `WARN`) |
| Event Poll (`gui_card_event_poll`) | `d-event-poll` | Status of the last PCE event poll (`OK` / `WARN` / `ERROR` / `UNKNOWN`) |
| Last Dispatch (`gui_card_last_dispatch`) | `d-dispatch` | Timestamp of the last alert dispatch |
| Unknown Types (`gui_card_unknown_types`) | `d-unknown` | Count of event types not mapped to any known category |
| Suppressed (`gui_card_suppressed`) | `d-suppressed` | Count of events suppressed by filter rules |

A seventh card, **Ransomware Exp** (`gui_card_ransomware_exp`, id `d-ransom`), exists in the
template but is hidden by default (`display:none` on `#card-ransom`). It only appears when the
snapshot data includes ransomware exposure data.

The KPI cards are implemented as the `.kpi-card` unified component (commit `88cdd5d`).

---

## Mini-KPI tiles

The `#cd-list` container (`<div id="cd-list" class="cards">`) inside `#cd-field` holds
dynamically injected mini-KPI tiles. This fieldset is hidden by default (`display:none`) and
is populated by `dashboard_v2.js` when the `/api/dashboard/snapshot` response includes
snapshot-level KPI data.

The snapshot KPI grid (`#snap-kpi-grid` inside `#snap-fieldset`) is a separate `.kpi-grid`
rendered from `s.kpis` — a list of `{label, value, label_key?}` dicts:

```js
(s.kpis || []).forEach((k) => {
  card.className = 'kpi-card';
  labelEl.className = 'kpi-label';
  valueEl.className = 'kpi-value';
  // label_key triggers server-side retranslation via /api/dashboard/snapshot
});
```

The `pd_*` i18n key family (`pd_1`, `pd_2`, `pd_3`, `pd_4`, `pd_allowed_*`, `pd_blocked_*`,
`pd_potentially_blocked_*`) describes **Policy Decision** filter options used in the Traffic
Analyzer and Workload Search sub-tabs. These are filter labels, not standalone mini-KPI tiles.

> [!TODO] @harry: confirm whether `#cd-list` is populated from a different code path than
> `#snap-kpi-grid`. As of this review both exist in `index.html` but only `snap-kpi-grid`
> has a clear population path in `dashboard_v2.js`. `cd-list` may be legacy.

---

## Action Matrix recommendations

The Action Matrix recommendations panel lives inside the **executive summary** section of
generated reports (`src/report/analysis/mod12_executive_summary.py`), not directly in the
dashboard template.

On the dashboard, the `#snap-fieldset` (under sub-tab **Legacy**, `#q-panel-legacy`) shows
the "Latest Traffic Report Summary" snapshot, which includes:

- A **Key Findings** table (severity / finding / action columns)
- A **Policy Breakdown** column and **Top Ports** column

The Action Matrix recommendation text was previously hardcoded as Python tuples with
low-quality zh strings. As of commit `f970d39`, these 4 recommendation pairs were migrated
to 8 i18n keys (`rpt_actmtx_*`) so that `mod12` calls `_t(key).format(...)` through the
standard i18n pipeline. The dashboard snapshot panel inherits correctly translated
recommendation text when the snapshot was generated after `f970d39`.

---

## Operations menu (header)

The **Operations** button (`#hdr-menu-btn`, i18n key `gui_hdr_operations`) in the top-right
of the page header opens a dropdown panel (`#hdr-menu-panel`, class `.hdr-menu`).

The menu was added in commit `f679f3a` ("Operations dropdown menu collects Theme/Density/Logs/Stop").
It contains four controls:

| Control | i18n key | Behaviour |
|---|---|---|
| Theme | `gui_theme` | `<select id="ui-theme-mode">` — Auto / Dark / Light |
| Density | `gui_density` | `<select id="ui-density">` — Compact / Comfortable |
| Logs | `gui_ml_logs_btn` | Opens the maintenance log modal (`data-action="mlOpen"`) |
| Stop | `gui_stop` | Calls `stopGui()` which shows a `confirm()` dialog before stopping the server |

The menu is keyboard-accessible: it closes on outside click or <kbd>Esc</kbd>. Clicking Logs
or Stop also auto-closes the menu. The button uses `aria-expanded` / `aria-haspopup="menu"`.

```html
<button id="hdr-menu-btn" type="button" class="btn btn-secondary btn-sm"
        data-action="hdrMenuToggle" aria-haspopup="menu" aria-expanded="false">
```

---

## Status chip & health dot

The `#hdr-chip` element (class `.pce-chip`, role `status`) in the page header is a unified
status chip introduced in commit `753b753` ("merge URL+stats into single status chip with
health dot"). It replaced two separate divs (`hdr-meta` for URL and `hdr-stats` for KPI spans).

The chip contains:

| Element | id / class | What it shows |
|---|---|---|
| Health dot | `#hdr-chip-dot` (`.status-dot`) | Colour-coded PCE event poll status: `ok` (green), `warn` (amber), `err` (red), `unknown` (grey) |
| PCE host | `#hdr-chip-host` (`.pce-host`) | Compressed PCE hostname from `pce_url` |
| Rules | `.chip-kpi` | Active rule count (server-rendered + updated by JS) |
| Schedules | `.chip-kpi` | Active schedule count |
| Loaded | `.chip-kpi` | Config load time (human-readable, e.g. "3 min ago") |

The dot status is derived from `pce_stats.event_poll_status` in the snapshot response:

```js
// dashboard.js ~line 1178
const polled = String((d.pce_stats || {}).event_poll_status || 'unknown').toLowerCase();
if (polled === 'ok') status = 'ok';
else if (polled === 'warn' || polled === 'degraded') status = 'warn';
else if (polled && polled !== 'unknown') status = 'err';
```

The chip's `aria-label` is server-rendered via Jinja2 and the `title` attribute is
updated by JS to include the PCE version (`| v{d.version}`).

---

## Multi-PCE switcher

No PCE switcher UI is present in the current `index.html` template. A search for
`pce_switcher`, `pce-profile`, `switchPce`, and related selectors returns no results.

Multi-PCE profile management is documented in the legacy User Manual (§6) as a Settings →
PCE Profiles workflow (add, edit, delete, activate), but that UI is under the Settings tab,
not the Dashboard header.

For documentation of the multi-PCE architecture, see [Multi-PCE](multi-pce.md).

---

## Language switching

The dashboard supports runtime EN ↔ zh_TW switching without a page reload.

**How it works:**

1. On each `/api/status` or `/api/dashboard/snapshot` response, the `language` field sets
   `window._uiLang`.
2. `applyI18n()` walks every `[data-i18n]`, `[data-i18n-placeholder]`, and
   `[data-i18n-title]` element and replaces their text/attribute from the translation bundle
   served by `/api/ui_translations`.
3. Snapshot KPI labels that carry a `label_key` are **retranslated at request time** on the
   server: `dashboard.py` overwrites `label` with `_t(label_key, lang=lang)` before returning
   JSON. This means KPI labels in an old snapshot reflect the *current* UI language, not the
   language at snapshot generation time.

Legacy snapshots without `label_key` retain their original language labels (noted in
`src/gui/routes/dashboard.py` line 38).

For the full contract governing i18n keys, retranslation, and zh_TW approved-translation
regression gate, see [i18n Contract](../architecture/i18n-contract.md).

---

## Related Docs

- [Reports](reports.md) — exporting + scheduling reports from dashboard data
- [Alerts & Quarantine](alerts-and-quarantine.md) — KPIs that drive alerting
- [Multi-PCE](multi-pce.md) — switching between PCEs
- [i18n Contract](../architecture/i18n-contract.md) — why labels re-render on language switch
