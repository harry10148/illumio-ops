# Tier 2a — Flatten-at-ingest + vectorized cache read (kill the parse wall)

**Date:** 2026-06-14
**Status:** DESIGN — awaiting approval before implementation

## Problem

Reports build their DataFrame by reading every cached flow as `orjson.loads(raw_json)`
then `_flatten(r)` (per-record, nested-JSON extraction of ~40 fields) →
`pd.DataFrame(rows)`. Measured throughput ≈ **1,435 rows/s** → a full-estate
report over hundreds of thousands of flows takes **minutes**. App Summary
(scoped) is already fast via the cache app-filter; the wall remains for
full-estate reports and is the binding constraint at the prod scale the user
expects (几十万笔/週 sustained).

## Goal

Make the report DataFrame come from **typed columns via a single vectorized
read** (`pandas.read_sql_query`) instead of per-row Python JSON flattening —
turning minutes into seconds — without changing report output.

## Approach

1. **Flatten at ingest (once), not at every report (N times).**
   Extend `PceTrafficFlowRaw` with the report-ready columns the parser produces,
   and populate them in the ingestor from the same flow dict. `raw_json` stays
   as the source of truth (fidelity / debugging / SIEM); it just stops being the
   report parse path.

2. **Vectorized read.** New `CacheReader.read_flows_df(start, end, workload_hrefs)`
   issues one `SELECT <cols> WHERE last_detected BETWEEN … [AND workload filter]`
   and returns a DataFrame via `pandas.read_sql_query` (C-level, no per-row
   Python). Column names map directly to the unified schema `_flatten` emits.

3. **Report path uses it.** `ReportGenerator.fetch_traffic_df` /
   `generate_from_api` consume `read_flows_df` when the cache is the source.
   The existing `_parse_api(orjson+_flatten)` path stays for the **API/live**
   source and as a fallback.

## New columns on `pce_traffic_flows_raw`

Already present (reuse): `src_ip, dst_ip, port, protocol(→proto), action(→policy_decision),
flow_count(→num_connections), bytes_in, bytes_out, first_detected, last_detected,
src_workload, dst_workload`.

Add (denormalized from the flow JSON at ingest):
`src_hostname, src_managed, src_enforcement, src_os_type, src_app, src_env, src_loc, src_role,
dst_hostname, dst_managed, dst_enforcement, dst_os_type, dst_fqdn, dst_app, dst_env, dst_loc, dst_role,
process_name, user_name, state, bytes_total, bandwidth_mbps`,
plus `src_extra_labels` / `dst_extra_labels` as JSON-text columns (preserve
non-standard labels; rarely read but keeps schema parity).

All new columns nullable with sane defaults (''/0) so existing rows and the
transition period don't break.

## Key decisions (need your call)

1. **Backfill existing rows?**
   - (a) **No backfill — rely on 7-day retention turnover** (recommended for
     simplicity): new rows get columns immediately; within ≤7 days every row
     has them. During transition, `read_flows_df` detects NULL denormalized
     columns and falls back to parsing those rows' `raw_json`. Zero migration
     risk, self-healing.
   - (b) One-time backfill: re-parse the ~240k `raw_json` once (~3 min) to fill
     columns. Immediate full benefit, but a heavier migration step.
   - **Recommendation: (a)** — with 7-day retention the transition is short and
     the fallback keeps correctness.

2. **Share the flatten logic.** Extract the `_flatten` field mapping into a
   shared pure helper used by BOTH the ingestor (write) and `_parse_api`
   (fallback read) so they can't drift. (Recommended.)

3. **Computed fields** (`bytes_total`, `bandwidth_mbps`): compute at ingest from
   the raw byte/duration fields (reuse `calculate_mbps`/`calculate_volume_mb`).
   Keep the raw byte fields only inside `raw_json` (not as columns) — the report
   only needs the computed values.

## Out of scope (later tiers)
- top10/analyzer SQL-filter pushdown (Tier 2b).
- DuckDB columnar read path (Tier 3).
- Postgres/Timescale (Tier 4).

## Risks & mitigations
- **Schema change**: additive, nullable columns only; `create_all` adds them on
  existing SQLite tables? NO — `create_all` does not ALTER existing tables. So
  new columns need explicit `ALTER TABLE … ADD COLUMN` (idempotent) in
  `init_schema` (like the index add/drop helpers). Each is a cheap metadata-only
  op in SQLite.
- **Drift** between ingest-flatten and report-flatten → shared helper (decision 2).
- **Correctness** → fallback path + the existing report tests must stay green;
  add a test asserting `read_flows_df` output equals the `_parse_api` output for
  the same flows.
- **Forward-compat**: same denormalized columns map cleanly to a future
  Postgres/DuckDB schema.

## Success criteria
- Full-estate report DataFrame build drops from minutes to single-digit seconds
  for ~200k flows.
- Report output (sections, numbers) unchanged vs the orjson+_flatten path
  (verified by a column-equality test on a sample).
- Existing tests green; new rows carry denormalized columns; transition rows
  fall back correctly.
