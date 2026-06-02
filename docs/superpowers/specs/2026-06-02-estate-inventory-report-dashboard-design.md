# Estate Inventory & Posture — Report + Dashboard Enhancement (Design Spec)

**Status:** Draft for review (no implementation yet)
**Date:** 2026-06-02
**Origin:** Concepts distilled from `alexgoller/illumio-reporter-library` (the AI half is intentionally excluded — offline deployment). These are the *non-AI, fully-offline* workload-attribute analyses worth folding into our existing reports/dashboard.

## Why
Our report engine is strong on **traffic & policy analysis** (mod01–15: uncovered flows, ransomware, lateral movement, cross-label matrix, readiness…) and on **audit**. The gap is a high-level **workload-attribute inventory / posture snapshot** — "what does the estate look like" independent of traffic. The reporter-library's useful ideas are exactly that. All three below compute purely from **managed-workload attributes** (already fetched for the VEN summary / VEN Status report) — **no traffic, no PCE-live dependency beyond the existing workload fetch, no AI** → safe for air-gapped installs.

## The three concepts
1. **OS distribution** — workload counts by `os_id` (Windows/Linux/flavours).
2. **Enforcement posture distribution** — workload counts by `enforcement_mode` (idle / visibility_only / selective / full) and `enforcement_state`; plus **by network** (per-network workload count + enforcement-mode breakdown) to show *where* segmentation is weak.
3. **Open-ports attack surface** — top listening ports across workloads from `workload.services.open_service_ports` (static attack surface; complements traffic-flow analysis — an unused open port shows no flow but is still exposure).

## Data source (offline-safe) — VERIFIED against live PCE 2026-06-02
`fetch_managed_workloads()` calls `GET /workloads?managed=true` (no `representation` param). Inspecting a live workload object confirmed:
- ✅ **Present in the bulk fetch** (so ①② need NO fetch change): `os_id`, `os_detail`, `online`, `enforcement_mode` (e.g. `selective`), `visibility_level` (bonus posture dimension), `interfaces[].network.name` (e.g. `Corporate`), `labels`, `risk_summary`, `ven`, `data_center`.
- ❌ **NOT present**: `services` comes back **empty (`{}`)** in the collection response → **`open_service_ports` is unavailable in bulk**. Obtaining it requires a per-workload `GET /workloads/{id}` (N requests) or a detailed representation.

**Implication:** ①② are ready now, zero fetch changes. ③ has a real data cost — see its section.

---

## Where each goes (the placement question)

### Reports
**① OS Distribution + ② Enforcement Posture → `VEN Status Inventory Report` (`ven_status_generator.py`)** — already the workload-inventory report (online/offline/active classification). Reframe its title to **"Estate Inventory & Posture"** and add two sections:

| New section | Concept | Notes |
|---|---|---|
| OS Distribution | ① | pie/bar + table; sits beside existing online/offline |
| Enforcement Posture (overall + by network) | ② | stacked bar per network + overall mode pie |

**③ Open-Ports Attack Surface → `Traffic Report` *security* cluster** (reviewer decision, 2026-06-02). Open listening ports are attack surface — a *security* concern — so ③ belongs alongside **mod04 (ransomware exposure)** / **mod15 (lateral movement)** in the Traffic Report, NOT the inventory report. Register in `TRAFFIC_MODULES` as `mod16_open_ports_surface`. Its value is the contrast *static open ports* (workload attribute) vs *observed flows*: an open port with no flow shows no traffic finding but is still exposure. ② may *additionally* enrich **mod13 (enforcement_readiness)** in the Traffic Report.

**③ data cost (verified):** `open_service_ports` is NOT in the bulk workload fetch — it needs a per-workload `GET /workloads/{id}`. So ③ must be **opt-in** and **cached** (the data changes slowly): a bounded enrichment pass (respect `rate_limit_per_minute`, cap workloads, persist into the pce_cache or state) rather than N live calls per report. Recommend implementing ①② first; gate ③ behind a config flag and a cached enrichment step.

**Not in:** Audit Report (event-centric) or Policy Usage Report (rule-centric) — wrong altitude.

### Dashboard
Add a **"Estate Posture" card cluster** on the 總覽 (overview) tab, beside the existing VEN Health card (which already shows online/offline):
- **OS distribution** mini-card (compact donut or top-3 list)
- **Enforcement mode distribution** mini-card (full / selective / visibility / idle as a stacked bar or % chips)
Reuse the existing card/dot/`sw` icon idioms and the dashboard data path (`run_ven_summary` → `state.json` → `_buildOvCards`-style render). These are instant, cached, offline.

---

## Module / file structure
- Shared analysis (pure functions, testable): `src/report/analysis/estate_inventory.py` exposing `os_distribution(workloads)`, `enforcement_distribution(workloads)`, `enforcement_by_network(workloads)` → for the VEN report + dashboard. Plain dicts/DataFrames, no I/O.
- ③ as a Traffic module: `src/report/analysis/mod16_open_ports_surface.py` exposing `open_ports_surface(...)`, registered in `TRAFFIC_MODULES` (auto-imported, auto-run), rendered in the Traffic Report security cluster next to mod04/mod15.
- `ven_status_generator.py`: call the shared analyses, render the 2 new sections (OS, enforcement posture) via existing exporters (HTML/Excel/PDF chart helpers already in the repo — matplotlib).
- Dashboard: extend `run_ven_summary` (scheduler/jobs) to also compute os/enforcement distributions into `state.json`; render two cards in `dashboard.js`.
- i18n: add section/card labels to `i18n_en.json` + `i18n_zh_TW.json` (parity). Keep product terms (Workload/PCE/VEN/enforcement modes) English per glossary.
- Charts: reuse existing matplotlib chart helpers (do NOT add plotly/ReportLab — the upstream's engines are not needed).

## Effort
Medium. One shared analysis module (offline, unit-testable) + VEN-report rendering + 2 dashboard cards + i18n. No new dependencies, no network/AI, no new data pipeline (reuses the workload fetch).

## Explicitly excluded (from reporter-library)
- AI advisor / `ai_models` (offline constraint).
- plotly / ReportLab / cairosvg (we use matplotlib).
- cross-environment treemap (we already have mod07 cross-label matrix).
- top-hostnames (low value).

## Data prerequisite — RESOLVED (2026-06-02)
- ①② : `os_id`, `enforcement_mode`, `interfaces[].network.name`, `visibility_level` all confirmed present in the existing bulk fetch → **no change, ready to build**.
- ③ : `open_service_ports` confirmed ABSENT from bulk → needs opt-in + cached per-workload enrichment (see ③ section). Build ①② first.
