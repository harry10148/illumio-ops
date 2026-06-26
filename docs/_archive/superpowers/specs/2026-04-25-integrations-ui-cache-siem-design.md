# Integrations UI — Cache + SIEM Settings Coverage

**Date:** 2026-04-25
**Status:** Design approved (brainstorming session)
**Target version:** v3.14.x (after Phase 16 offline bundle; per user: scheduled last in queue after Q1/Q2/Q3)

## 1. Background & Motivation

Phase 13 shipped `pce_cache` and `siem` forwarder modules with complete backend APIs (`/api/cache/*`, `/api/siem/destinations`, `/api/siem/dlq`, `/api/siem/status`) but **zero frontend UI and zero CLI interactive menu**. Operators today must hand-edit `config.json` to:

- Toggle `pce_cache.enabled`, tune poll intervals, set retention days, configure `traffic_filter` / `traffic_sampling`
- Add/edit/remove SIEM destinations (11 fields each: name, transport, format, endpoint, TLS, batch, retry, source_types, etc.)
- Inspect SIEM DLQ (dead-letter queue) and replay/purge failed dispatches

This design closes that gap.

## 2. Goals

- **G1** Operators can manage all `pce_cache.*` and `siem.*` settings from the Web GUI.
- **G2** Operators can do the same from the CLI interactive menu (parity).
- **G3** SIEM destinations support CRUD + **connection test** from GUI and CLI.
- **G4** SIEM DLQ supports list/filter/replay/purge/**CSV export** from GUI and CLI.
- **G5** Saving settings persists to `config.json` via pydantic-validated endpoints, returns per-field errors, and prompts the user to restart the monitor when the change requires it.
- **G6** When the daemon is launched via Web GUI (`run_daemon_with_gui`), a `[Restart Monitor]` button works in-place; otherwise the button is disabled with an explanatory tooltip.
- **G7** All new user-facing text uses i18n keys in both `i18n_en.json` and `i18n_zh_TW.json`.

## 3. Non-Goals (Out of Scope)

- Hot-reload of scheduler jobs or SIEM destinations. Restart-required model only.
- Migration of existing `/api/settings` sections (`api`, `alerts`, `email`, `smtp`, `web_gui`, etc.) to per-module endpoints. Captured as future work; this design introduces a reusable `save_section()` helper but does NOT migrate existing consumers.
- Dashboard/overview charts beyond the four status cards. Advanced analytics stays in existing `Dashboard` tab.
- Bulk operations on SIEM destinations (import/export YAML).
- Fine-grained RBAC. Current Web GUI auth model (single `web_gui.username`) applies to all new endpoints.
- Integration with the `policy_decision` / `draft_pd` work — that is a separate plan.

## 4. Architecture Decisions (Recap)

| # | Question | Decision |
|---|----------|----------|
| D1 | Where do the new pages live in the navigation? | New top-level `Integrations` tab, inserted **before** `Settings`, so top nav becomes: Dashboard · Traffic · Events · Rules · Reports · Rule Scheduler · **Integrations** · Settings |
| D2 | How is Integrations subdivided? | 4 sub-tabs: `Overview` / `Cache` / `SIEM` / `DLQ` |
| D3 | How are SIEM destinations edited? | Table list + Modal editor (11 fields grouped into Basic / Transport / TLS / HEC / Batch sections) |
| D4 | How do settings changes take effect? | Restart-required. Response returns `requires_restart: bool`; GUI shows banner + `[Restart Monitor]` button |
| D5 | How is the CLI structured? | Mirror existing interactive-menu pattern (`manage_pce_cache_menu`, `manage_siem_menu`). Existing `illumio-ops siem test|status` and `cache backfill|status` subcommands remain as-is |
| D6 | `traffic_filter` / `traffic_sampling` UI? | Full field UI (checkbox groups, tag chips for ports/IPs, number inputs). Not JSON textarea. |
| D7 | SIEM connection test? | New endpoint `POST /api/siem/destinations/<name>/test` that reuses the `siem test <name>` CLI logic by extracting `_send_test_event(dest_cfg)` as shared helper |
| D8 | Save endpoint strategy? | **Path B**: new `/api/cache/settings`, `/api/siem/forwarder` endpoints, alongside existing per-resource endpoints. Do NOT extend `/api/settings`. Introduce `save_section()` helper for future reuse. |
| D9 | Restart button? | Implemented for GUI-integrated daemon only. Detect `_GUI_OWNS_DAEMON` flag; otherwise disable button with tooltip. |
| D10 | Scope expansion? | No — only Cache + SIEM migrate. `api`, `alerts`, `smtp`, `web_gui` migrations are deferred to future plans. |

## 5. Backend API

### 5.1 New Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/cache/settings` | Read `pce_cache.*` (all fields incl. `traffic_filter`, `traffic_sampling`) |
| `PUT` | `/api/cache/settings` | Validate + persist `pce_cache.*`; returns `{ok, requires_restart, errors?}` |
| `GET` | `/api/siem/forwarder` | Read `siem.enabled`, `siem.dispatch_tick_seconds`, `siem.dlq_max_per_dest` (NOT destinations) |
| `PUT` | `/api/siem/forwarder` | Validate + persist forwarder-level fields |
| `POST` | `/api/siem/destinations/<name>/test` | Send synthetic event via the destination's real transport; return `{ok, error?, latency_ms}` |
| `GET` | `/api/siem/dlq/export?destination=&reason=` | Stream CSV of filtered DLQ entries |
| `POST` | `/api/daemon/restart` | Restart scheduler (GUI-integrated daemon only); otherwise HTTP 409 with explanation |

### 5.2 Existing Endpoints (Reused As-Is)

- `GET /api/cache/status`, `POST /api/cache/backfill`
- `GET /api/siem/destinations`, `POST /api/siem/destinations`, `PUT /api/siem/destinations/<name>`, `DELETE /api/siem/destinations/<name>`
- `GET /api/siem/status`, `GET /api/siem/dlq`, `POST /api/siem/dlq/replay`, `POST /api/siem/dlq/purge`
- `GET/POST /api/settings` (untouched; still drives other Settings page sections)

### 5.3 Shared Helper — `save_section()`

New file: `src/gui/settings_helpers.py` (~40 lines)

```python
def save_section(cm, section_key, data_dict, pydantic_model):
    """Validate, merge, atomic-write a single settings section.
    Returns: {ok, requires_restart, errors?} dict suitable for jsonify.
    """
```

Used by `/api/cache/settings` (PUT) and `/api/siem/forwarder` (PUT). Future plans can migrate `api`, `alerts`, `smtp`, `web_gui` to this helper.

### 5.4 Shared Helper — `_send_test_event(dest_cfg)`

Extracted from `src/cli/siem.py:23` (the `siem test` command). New home: `src/siem/tester.py`. Both the CLI command and the new `POST /api/siem/destinations/<name>/test` endpoint call this.

### 5.5 `requires_restart` logic

- `pce_cache` section: `true` if any of `enabled`, `events_poll_interval_seconds`, `traffic_poll_interval_seconds`, `db_path` changed (these bind to APScheduler at startup).
- `siem.forwarder`: `true` if `enabled` or `dispatch_tick_seconds` changed.
- Simplification: compute diff vs current in-memory config. For this plan, if any diff exists, just return `true` (safer; matches D4 "always prompt restart").

### 5.6 IP Validator

Add `@field_validator` to `TrafficFilterSettings.exclude_src_ips` in `src/config_models.py`. Accept IPv4 or IPv6 (use `ipaddress` module). Invalid entries → 422 with field path.

## 6. Frontend — GUI

### 6.1 Top Navigation

Modify `src/templates/index.html` lines 162–198:

```
[Dashboard] [Traffic] [Events] [Rules] [Reports] [Rule Scheduler] [Integrations] [Settings]
```

Add new `<button class="tab" data-tab="integrations">` before the Settings tab. i18n key: `gui_tab_integrations`.

### 6.2 Integrations Panel (`#p-integrations`)

Single panel element with sub-tab bar (reuse `rs-tab-bar` CSS pattern from Rule Scheduler):

```
<div class="panel" id="p-integrations">
  <div class="sub-tab-bar">
    [Overview] [Cache] [SIEM] [DLQ]
  </div>
  <div id="it-pane-overview">...</div>
  <div id="it-pane-cache">...</div>
  <div id="it-pane-siem">...</div>
  <div id="it-pane-dlq">...</div>
</div>
```

### 6.3 Overview Sub-Tab

Four status cards (reuse existing `.cards` / `.card` CSS):

| Card | Source | Color rules |
|------|--------|-------------|
| Cache Lag | `/api/cache/status` `.events_lag_sec`, `.traffic_lag_sec` | 綠 < poll_interval · 黃 < 2× · 紅 ≥ 2× |
| Ingest Recency | `/api/cache/status` `.last_event_ingested_at`, `.last_traffic_ingested_at` | 綠 < 1h · 黃 < 6h · 紅 ≥ 6h |
| SIEM Queue | `/api/siem/status` aggregated pending/sent/failed | 綠 failed=0 · 黃 failed>0 but <10% · 紅 ≥10% |
| DLQ Total | `/api/siem/status` sum of per-dest DLQ counts | 綠 0 · 黃 <100 · 紅 ≥100 |

Below cards: "Last 10 dispatch events" table (from `/api/siem/status.recent`).

### 6.4 Cache Sub-Tab

Two sections:

**A. Cache Status Card** (read-only)
- Shows: `enabled`, events lag, traffic lag, db size, last events ingested, last traffic ingested
- Actions: `[Backfill...]` (opens existing modal pattern), `[Retention Now]`

**B. Settings Form** (grouped, matches pydantic `PceCacheSettings`):
- **Basic**: `enabled` (toggle), `db_path` (text)
- **Retention (days)**: `events_retention_days`, `traffic_raw_retention_days`, `traffic_agg_retention_days`
- **Polling (seconds)**: `events_poll_interval_seconds` (≥30), `traffic_poll_interval_seconds` (≥60)
- **Throughput**: `rate_limit_per_minute` (10-500), `async_threshold_events` (1-10000)
- **Traffic Filter** (sub-object):
  - `actions`: checkbox group — `[✓] blocked` `[✓] potentially_blocked` `[ ] allowed`
  - `workload_label_env`: tag input (free string chips)
  - `ports`: tag input (numeric chips, validate 1-65535)
  - `protocols`: checkbox group — TCP / UDP / ICMP
  - `exclude_src_ips`: tag input (IP chips; client-side IPv4/IPv6 regex + backend validator)
- **Traffic Sampling** (sub-object):
  - `sample_ratio_allowed` (≥1)
  - `max_rows_per_batch` (1-200000)

Save button → `PUT /api/cache/settings` → show restart banner if `requires_restart`.

### 6.5 SIEM Sub-Tab

Two sections:

**A. Forwarder Settings** (small form):
- `siem.enabled` (toggle), `dispatch_tick_seconds`, `dlq_max_per_dest`
- Save → `PUT /api/siem/forwarder`

**B. Destinations Table + Modal**:
- Columns: Name · Enabled · Transport · Format · Endpoint · Status (🟢/🟡/🔴 from `/api/siem/status`) · Actions
- Actions per row: `[Test]` `[Edit]` `[Delete]`
- Top bar: `[+ Add Destination]`
- Modal has 5 grouped sections (conditional fields via `transport` watch):
  - Basic: `name`, `enabled`, `source_types` (checkbox: audit/traffic)
  - Transport: `transport` (select: udp/tcp/tls/hec), `endpoint`, `format` (select: cef/json/syslog_cef/syslog_json)
  - TLS (shown when `transport` in `tls`/`hec`): `tls_verify`, `tls_ca_bundle` (file path)
  - HEC (shown when `transport=hec`): `hec_token` (password-style masked)
  - Batch: `batch_size` (1-10000), `max_retries` (≥0)
- Modal buttons: `[Save]` `[Test Connection]` `[Cancel]`
- `[Test Connection]` calls `POST /api/siem/destinations/<name>/test` and displays result inline in modal

### 6.6 DLQ Sub-Tab

- Filter bar: destination (select, from `/api/siem/destinations`), reason (free text), `[Search]`
- Table: checkbox · Dest · Event ID · Reason · Failed At · `[View]` `[Replay]`
- Pagination: 50 rows / page
- Bulk actions: `[Select All]` `[Replay Selected]` `[Purge Selected]`
- Danger zone: `[Purge ALL for <destination>]` — red button, confirmation modal with typed confirmation
- Export: `[Export CSV]` → GET `/api/siem/dlq/export` with current filters; browser downloads CSV
- `[View]` opens detail modal: full JSON payload (pygments-highlighted), error detail, retry history

### 6.7 Restart Banner

Reusable component (existing toast/banner infrastructure if any, else new `.banner` CSS):

```
⚠ 設定已儲存，排程相關欄位需重啟 monitor 才能生效
 [Restart Monitor]  [Dismiss]
```

- If `_GUI_OWNS_DAEMON=True`: button enabled → `POST /api/daemon/restart` → spinner → poll `/api/cache/status` until healthy (max 30s) → success toast
- If `_GUI_OWNS_DAEMON=False`: button disabled with tooltip (i18n key `gui_daemon_external_restart_hint`)
- Banner persists on the affected sub-tab until dismissed or daemon restart confirmed

### 6.8 JS File Structure

- New: `src/static/js/integrations.js` — sub-tab switcher, all 4 panes' rendering, API calls
- Modified: `src/static/js/main.js` (or equivalent tab switcher) — register new `integrations` tab
- Template: `src/templates/index.html` — add nav button, add `#p-integrations` panel (with 4 sub-panes inline)

## 7. CLI

### 7.1 Main Menu Updates

`src/main.py` main menu inserts two items before `Settings`:

```
Main menu:
  1. ... existing ...
  N. Manage PCE Cache        ← new
  N+1. Manage SIEM Forwarder ← new
  N+2. Settings              ← existing, shifted down
```

### 7.2 `manage_pce_cache_menu(cm)` — new file `src/pce_cache_cli.py`

```
PCE Cache Menu:
  1. View status
  2. Edit settings (basic + retention + polling + throughput)
  3. Edit traffic filter
  4. Edit traffic sampling
  5. Backfill (interactive: start/end date prompts)
  6. Run retention now
  0. Back
```

After option 2/3/4 saves → print `[!] Settings saved. Restart monitor to apply scheduling changes.`

### 7.3 `manage_siem_menu(cm)` — new file `src/siem_cli.py`

```
SIEM Forwarder Menu:
  1. View status
  2. Edit forwarder config (enabled / dispatch_tick / dlq_max_per_dest)
  3. List destinations
  4. Add destination        (sequential prompts; conditional TLS/HEC)
  5. Edit destination       (blank input keeps current value)
  6. Delete destination
  7. Test destination       (calls _send_test_event() directly, no HTTP)
  8. DLQ management →
     a. List entries (with filters)
     b. Replay selected
     c. Purge selected
     d. Purge ALL by destination (typed confirmation)
     e. Export to CSV (prompt for file path)
  0. Back
```

## 8. Validation

- **Backend**: pydantic validates all PUT payloads. `save_section()` catches `ValidationError` and returns HTTP 422 with `{errors: {field_path: message}}`.
- **Frontend**: lightweight client-side hints before submit (IP regex, number range); authoritative validation is backend.
- **IP validator**: new `@field_validator` on `TrafficFilterSettings.exclude_src_ips` using `ipaddress.ip_address()`.
- **Port validator**: new `@field_validator` on `TrafficFilterSettings.ports` (each in 1-65535).
- Error responses map back to form fields via `field_path` → field id convention.

## 9. i18n

All new strings added to both `src/i18n_en.json` and `src/i18n_zh_TW.json`. Key prefix convention:

- Top-level: `gui_tab_integrations`
- Sub-tabs: `gui_it_overview`, `gui_it_cache`, `gui_it_siem`, `gui_it_dlq`
- Cache page: `gui_cache_<field>` (e.g., `gui_cache_events_retention_days`, `gui_cache_actions_blocked`)
- SIEM page: `gui_siem_<field>`
- DLQ page: `gui_dlq_<field>`
- Banner: `gui_restart_required_banner`, `gui_restart_monitor_btn`, `gui_daemon_external_restart_hint`
- Validation: `gui_err_invalid_ip`, `gui_err_port_range`, `gui_err_field_required`
- Estimated total: **+60 keys** (Cache 20 · SIEM 25 · DLQ 10 · Overview 3 · common 2)

All new strings MUST pass `python3 scripts/audit_i18n_usage.py` (A–I = 0 findings) and `tests/test_i18n_audit.py`.

## 10. Testing

| Layer | New Test Files / Cases |
|-------|-----------------------|
| Backend unit | `tests/test_cache_settings_api.py` — GET/PUT round-trip, validation errors, requires_restart detection |
| Backend unit | `tests/test_siem_forwarder_api.py` — GET/PUT |
| Backend unit | `tests/test_siem_test_endpoint.py` — mock transport, success/failure, latency_ms |
| Backend unit | `tests/test_siem_dlq_export.py` — CSV format, filter application |
| Backend unit | `tests/test_daemon_restart_api.py` — with/without `_GUI_OWNS_DAEMON`, 409 case |
| Backend unit | Extend `tests/test_config_models.py` — IP validator, port range validator |
| Backend unit | `tests/test_settings_helpers.py` — `save_section()` helper (happy path + ValidationError) |
| CLI | `tests/test_pce_cache_cli.py` — menu routing, edit settings flow |
| CLI | `tests/test_siem_cli.py` — add/edit/delete destination, DLQ operations, test destination |
| Integration | `tests/test_integrations_e2e.py` — full save → restart → reload cycle with in-memory scheduler |
| i18n | Existing `tests/test_i18n_audit.py` and `tests/test_i18n_quality.py` must pass with new keys |

**Estimated new tests: ~25 cases across ~10 new files.** Current baseline: 582 passed + 1 skipped (post-Phase 15). Target after this plan: ~607 passed + 1 skipped.

## 11. File Changes Summary

### New files
- `src/gui/settings_helpers.py` — `save_section()` helper
- `src/gui/integrations_api.py` — all `/api/cache/settings`, `/api/siem/forwarder`, `/api/siem/destinations/<name>/test`, `/api/siem/dlq/export`, `/api/daemon/restart` handlers (or register as blueprint under existing `siem.web` / new `cache.web` blueprint)
- `src/siem/tester.py` — `_send_test_event(dest_cfg)` shared by CLI + API
- `src/pce_cache_cli.py` — interactive CLI menu
- `src/siem_cli.py` — interactive CLI menu (note: distinct from existing `src/cli/siem.py` click subcommands)
- `src/static/js/integrations.js` — frontend logic for all 4 sub-panes
- `tests/test_cache_settings_api.py`
- `tests/test_siem_forwarder_api.py`
- `tests/test_siem_test_endpoint.py`
- `tests/test_siem_dlq_export.py`
- `tests/test_daemon_restart_api.py`
- `tests/test_settings_helpers.py`
- `tests/test_pce_cache_cli.py`
- `tests/test_siem_cli.py`
- `tests/test_integrations_e2e.py`

### Modified files
- `src/templates/index.html` — add nav button, add `#p-integrations` panel
- `src/static/js/main.js` (or the file containing `switchTab`) — register integrations tab
- `src/config_models.py` — add IP / port validators
- `src/main.py` — add menu entries for Cache / SIEM
- `src/cli/siem.py` — refactor `siem_test` to call `_send_test_event()` from `src/siem/tester.py`
- `src/gui.py` — register new blueprint(s), initialize `_GUI_OWNS_DAEMON` flag, wire `/api/daemon/restart`
- `src/i18n_en.json`, `src/i18n_zh_TW.json` — +60 keys
- `tests/test_config_models.py` — new validator cases

## 12. Implementation Order (for plan writer)

Rough sequencing to minimize merge risk and allow early validation:

1. **Foundation** — IP/port validators, `save_section()` helper, `_send_test_event()` extraction, CLI tests (no UI yet)
2. **Backend API** — new endpoints (cache settings, siem forwarder, siem test, dlq export, daemon restart) with unit tests
3. **CLI menus** — `manage_pce_cache_menu`, `manage_siem_menu` wired into `main.py`
4. **Frontend foundation** — Integrations tab shell, sub-tab switcher, i18n keys
5. **Frontend — Cache sub-tab** (full field UI incl. traffic_filter/sampling)
6. **Frontend — SIEM sub-tab** (table + modal + test)
7. **Frontend — DLQ sub-tab** (list + filters + bulk + CSV export)
8. **Frontend — Overview sub-tab** (4 status cards + recent events)
9. **Restart banner + `/api/daemon/restart` + `_GUI_OWNS_DAEMON` detection**
10. **i18n audit + full pytest run + manual GUI walkthrough**

## 13. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| `/api/daemon/restart` leaves daemon in broken state | GUI hangs / loses scheduler | Keep previous scheduler alive until new one reports healthy; on failure, re-raise original; health-check poll has 30s timeout with rollback |
| Config.json write race (concurrent CLI + GUI edits) | Lost writes | `save_section()` uses atomic rename; optional: file lock on write. Document as edge case — not in MVP scope |
| SIEM test button leaks secrets in logs (HEC token) | Credential exposure | Mask `hec_token` in all log lines; only pass through transport object |
| Tag-input IP/port widgets are new UI elements | Complexity | Use minimal dependency-free implementation; fallback textarea (comma-separated) if time-pressed |
| Big CSS / JS additions affect existing pages | Regression | Scope all new CSS under `#p-integrations`; new JS in separate file loaded on-demand |
| `requires_restart` logic too eager (always true) annoys users | Banner fatigue | Document as MVP behavior. Phase 2 can add precise diff detection |

## 14. Future Work (Not in This Plan)

- Migrate `api`, `alerts`, `smtp`, `web_gui` sections to use `save_section()` + per-module endpoints
- Hot-reload for poll intervals without full daemon restart
- SIEM destination bulk import/export (YAML)
- RBAC for settings changes
- Test-connection buttons for SMTP, LINE webhook, PCE API (symmetrical with SIEM Test)
