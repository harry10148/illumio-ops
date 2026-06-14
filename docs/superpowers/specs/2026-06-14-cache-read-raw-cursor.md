# Spec — `read_flows_df` raw-cursor fetch (supersedes Route 2)

**Date** 2026-06-14 · **Status** approved, implementing · **Scope** `src/pce_cache/reader.py`

## Problem

Full unfiltered traffic report (7-day window, 242,459 rows) reads the cache in
**~20s** (handoff reported ~23s cold). The parked "Route 2" plan attributed this
to per-row Python in `read_flows_df` and proposed denormalizing the 4 standard
labels into columns + `pandas.read_sql`.

## Measurement (test machine, 242,459 rows, warm cache)

Profiling **refuted Route 2's premise**:

| Path | Time |
|------|------|
| **Actual `read_flows_df`** (SQLAlchemy ORM session) | **19.81s** |
| Raw sqlite3: blob fetch + orjson + `build_unified_df` | 12.04s |
| Route 2 (`read_sql` of 41 denormalized columns) | 11.70s |
| Decomposition (raw): fetch 5.66s · orjson 3.79s · build 3.27s | |

- **Not I/O**: blob fetch with vs without `ORDER BY` = 5.66s vs 6.26s → data is
  cached; cost is the sqlite3 driver's per-row × per-column Python object build.
- **Route 2 ≈ 0 gain**: `read_sql` removes orjson (3.79s) but pays it back
  fetching 41 columns instead of 1 blob (7.01s vs 5.66s). 11.70s vs raw 12.04s =
  3% — for a 16-column schema change + 242k-row backfill + 41-column maintenance.
- **The real tax is SQLAlchemy**: the ORM-session result wrapping adds ~7.8s
  (~40%) over the identical raw-sqlite3 logic.

## Decision

Do **not** do Route 2. Replace the SQLAlchemy session fetch in `read_flows_df`
with a raw DBAPI cursor obtained from the same engine (so the connect-listener
PRAGMAs — `cache_size`, `mmap_size`, `busy_timeout`, WAL — still apply).

- Keep `report_json`, `orjson`, `build_unified_df`, the NULL→raw_json fallback,
  and the report_json-not-null / is-null two-query split **unchanged**.
- Push the same filters to SQL as today: `last_detected` window, `workload_hrefs`
  (src OR dst IN), `policy_decisions` (action IN), `ORDER BY last_detected`.
- Datetime bounds are formatted to the exact string SQLite stores
  (`%Y-%m-%d %H:%M:%S.%f`, UTC-naive) so string comparison matches what
  SQLAlchemy bound before. (Bonus: avoids the Python 3.12 sqlite3
  datetime-adapter deprecation, since we pass strings not datetimes.)

**Expected**: ~20s → ~12s (~40%). Zero schema change, zero backfill, zero
offline-bundle impact, identical output DataFrame.

## Verification

1. New equivalence test: `read_flows_df` (mixed report_json/NULL rows, with
   window + workload + decision filters) produces a frame equal (`check_like`)
   to `APIParser().parse()` of the matching flows.
2. Existing `test_cache_flatten_vectorized.py` read_flows_df tests stay green
   (report_json path, raw_json fallback, decision pushdown).
3. Re-profile actual `read_flows_df` on the test machine; confirm ~12s.
