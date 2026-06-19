# Unified Report Data-Source & Option Alignment — Design

Date: 2026-06-19
Status: Approved (pending spec review)
Scope decided with user: (1) make the cache option **presentation consistent** across
surfaces, and (2) **align options** across CLI / interactive shell / Web GUI **for the
report types each surface already supports**. NOT in scope: adding a cache backend to
report types that don't have one; full feature parity (adding new report types to a surface).

## Problem

Report generation exposes the "where does the data come from" choice inconsistently:

- The traffic report is actually driven by **two orthogonal flags** — `use_cache` and
  `clip_to_cache` — which combine into **three meaningful behaviors**, but the UI presents
  them as a 2-way dropdown plus a separate checkbox.
- The CLI offers `--cache/--no-cache` (2 modes, no clip), the GUI offers a cache/api
  dropdown **plus** a clip-to-cache checkbox (3 effective modes via 2 controls), and the
  interactive shell offers **nothing** (backend default).
- When `pce_cache.enabled = False` (or the cache is empty), selecting a cache mode
  **silently falls back to live PCE** with no warning. The worst case: "Cache only
  (fastest)" silently becomes a full live query (the slowest), with no signal to the user.
- Secondary option drift: shell traffic lacks `profile` and `source`; GUI policy-usage
  lacks `source`; cache wording differs per surface (`--no-cache` vs `cache/api`).

## The three data-source modes (the core model)

The backend already implements all three (`src/report/report_generator.py:294` and the
`_fetch_traffic_df` hybrid logic). We are **naming and exposing** them consistently, not
changing fetch behavior.

| Mode | Flags | Behavior | Trade-off |
|---|---|---|---|
| **hybrid** (default) | `use_cache=True, clip_to_cache=False` | Read cached portion; query PCE API for the leading gap the cache doesn't cover. Full requested window, cache-accelerated. | Balanced; default. |
| **live** | `use_cache=False` | Pure PCE query for the whole window; ignore cache. | Freshest, slowest. |
| **cache-only** | `use_cache=True, clip_to_cache=True` | Use cache; clip window start to the cache's earliest data so no gap-fill API call is made. | Fastest; window limited to what the cache holds. |

A single `data_source` value (`hybrid|live|cache-only`) maps to the `(use_cache,
clip_to_cache)` pair at the call boundary. The two boolean flags remain the internal
contract of `ReportGenerator`; only the surfaces change.

## Cache-capable report types

The unified 3-mode selector applies **only** to report types whose generator performs
cache-accelerated hybrid fetch AND already exposes a cache choice today:

- **traffic** (security_risk / network_inventory profiles)
- **app-summary**

All other types (audit, ven-status, policy-usage, policy-diff, policy-resolver) are
**always live** and show **no** data-source control. (Audit's generator has internal
hybrid logic but exposes no option today; leaving it internal keeps us within the agreed
scope — it is not "giving a new type a cache option".)

## 防呆 / Safeguard: cache unavailable

A shared helper decides whether cache modes are offerable:

```
cache_available(cm) -> bool
    True  iff pce_cache.enabled is True AND the cache db is reachable
          AND it holds at least some traffic data (earliest_data_timestamp is not None).
```

Behavior when `cache_available(cm)` is False:

- **GUI** and **interactive shell**: the data-source selector shows **only "Live PCE"**;
  the hybrid / cache-only options are hidden (or disabled with the hint "Enable PCE Cache
  to use cache-accelerated modes"). The user cannot pick a mode that won't work.
- **CLI**: the `--data-source` flag is still accepted (scriptability), but if `hybrid` or
  `cache-only` is requested while the cache is unavailable, print a clear **warning** and
  **fall back to live** — never silently. `cache-only` gets a louder warning because its
  intent (fastest) inverts to full-live.

This removes the current silent-degradation footgun.

## Per-surface changes

### CLI (`src/cli/report.py`)
- Replace `--cache/--no-cache` on `traffic` (and its `security`/`inventory` aliases) and
  `app-summary` with `--data-source [hybrid|live|cache-only]` (default `hybrid`).
- Keep `--no-cache` as a **deprecated alias** mapping to `--data-source live` (emit a
  one-line deprecation note); keep `--cache` as alias for `hybrid`. Back-compat for scripts.
- Map `data_source` → `(use_cache, clip_to_cache)` before calling the generator.
- Apply the 防呆 warning+fallback via `cache_available(cm)`.
- **Option alignment**: ensure `traffic` exposes `--profile` and `--source` (already does);
  no new types added.

### Web GUI (`src/gui/routes/reports.py`, `src/templates/index.html`, `src/static/js/dashboard.js`)
- Replace the cache dropdown (`m-gen-cache-mode`) **and** the clip-to-cache checkbox
  (`m-gen-clip-to-cache`) with a **single "Data source" dropdown** (`hybrid|live|cache-only`)
  shown for `traffic` and `app_summary` only.
- The existing cache-row visibility logic (`dashboard.js:701`) extends to also gate on a
  `cacheAvailable` flag returned by the page/init endpoint; when false, the dropdown is
  fixed to "Live PCE" (cache options hidden).
- The generate route maps `data_source` → `(use_cache, clip_to_cache)` server-side and
  re-applies the 防呆 fallback as defense-in-depth.
- **Option alignment**: add a `source` (api/csv) control to the **policy-usage** form to
  match the CLI (`/api/policy_usage_report/generate` already supports `source`).

### Interactive shell (`src/cli/menus/` traffic generate + `report_schedule.py`)
- Add a **Data source** prompt (`hybrid|live|cache-only`) to the traffic generate flow and
  the traffic branch of the schedule wizard, shown only when `cache_available(cm)`.
- **Option alignment**: add `profile` (security_risk/network_inventory) and `source`
  (api/csv) prompts to the shell traffic flow to match CLI/GUI.

## Shared building blocks (isolation & reuse)

- `cache_available(cm) -> bool` — one helper, used by all three surfaces. Lives next to
  `_make_cache_reader` (likely `src/main.py` or a small `src/report/cache_support.py`).
- `resolve_data_source(value, cache_available) -> tuple[bool, bool, str|None]` — pure
  function returning `(use_cache, clip_to_cache, warning_message)` from a `data_source`
  string + availability. Single source of truth for the mode→flags mapping and the 防呆
  fallback decision; unit-testable in isolation; reused by CLI + GUI route.

## Testing

- Unit: `resolve_data_source` for all 3 modes × {cache available, unavailable} → correct
  `(use_cache, clip_to_cache)` and warning presence. `cache-only` + unavailable → live +
  loud warning.
- Unit: `cache_available` for enabled+data, enabled+empty, disabled.
- CLI: `report traffic --data-source live|hybrid|cache-only` parses; `--no-cache` still
  works (deprecated → live); cache-unavailable path warns + falls back.
- GUI route: POST with `data_source` maps to correct flags; cache-unavailable → live.
- Regression: existing report tests still pass; `--no-cache` back-compat preserved.

## Out of scope (explicit)
- Adding a cache backend to audit/ven/policy-usage/policy-diff/resolver.
- Adding new report types to any surface (shell stays at its current type set).
- Changing the actual hybrid/clip fetch algorithm.
