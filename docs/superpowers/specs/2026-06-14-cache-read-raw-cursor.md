# Spec — `read_flows_df` fallback-scan fix (supersedes Route 2)

**Date** 2026-06-14 · **Status** done · **Scope** `src/pce_cache/schema.py`

> Title kept for history. The investigated lever (raw cursor) was **refuted by
> measurement**; the shipped fix is a **partial index**. See the journey below —
> it documents two dead ends so they aren't re-attempted.

## Problem

Full unfiltered traffic report (7-day window, ~242k rows) read the cache in
~16s clean (~20s under live-service contention). Parked "Route 2" blamed per-row
Python and proposed denormalizing labels + `pandas.read_sql`.

## What measurement showed (test machine, ~242k rows)

Each hypothesis was tested and **two were refuted**:

1. **Route 2 (denormalize + read_sql): refuted.** `read_sql` of 41 columns
   (11.70s) beat the raw blob+orjson+build path (12.04s) by only 3% — it trades
   the orjson parse (3.79s) for a 41-column fetch (7.01s vs the 1-blob 5.66s).
   Not worth a 16-column schema change + 242k backfill. Cost is the sqlite3
   driver's per-row × per-column object build (CPU, not I/O: `ORDER BY` made no
   difference).

2. **"SQLAlchemy ORM adds ~40%": refuted.** That gap was an artifact of (a) the
   fallback double-scan below and (b) live-service contention. Clean, with the
   fix in place: SQLAlchemy path **7.26s** vs a raw DBAPI cursor **11.41s** — the
   raw cursor was *slower*. Reverted.

3. **The real cause: the fallback query.** `read_flows_df` runs two queries —
   `report_json IS NOT NULL` (fast path) then `report_json IS NULL` (fallback for
   pre-Tier-2a rows). On a backfilled DB the fallback matches **0 rows**, but
   `report_json` is in no index, so it **full-scanned the 242k-row last_detected
   range** checking each row — ~8s for nothing.

## Fix (shipped)

Add a **partial index**:
`ix_raw_report_json_null ON pce_traffic_flows_raw(last_detected) WHERE report_json IS NULL`.

The fallback query now hits this index, which contains only null-`report_json`
rows (none, on a backfilled DB) → returns instantly. **Zero write cost**: ingest
always sets `report_json`, so new rows never enter the partial index. Created
idempotently in `init_schema` (`CREATE INDEX IF NOT EXISTS … WHERE …`), so it
appears on the next service restart with no manual migration.

**Result: ~16s → ~7s clean (~2.3×).** No schema/column change, no backfill, no
offline-bundle impact, `read_flows_df` logic and output unchanged.

## Verification

1. `test_schema_creates_report_json_null_partial_index` — index exists and is
   partial (carries the `report_json IS NULL` predicate).
2. `test_read_flows_df_matches_apiparser_with_filters` — read_flows_df output
   equals `APIParser().parse()` across report_json + raw_json-fallback rows with
   window + workload + decision filters (regression guard; added this session).
3. Re-profile on the test machine, service stopped: ~7s confirmed.

## Floor / not pursued

~7s for materializing 242k rows × 41 cols into a pandas DataFrame is near the
SQLite+pandas floor. The painful case is the *unfiltered* full report (242k rows
inherent — the 6/12 weak-scan burst), so row-reducing pushdown can't help it.
Further wins would need a columnar engine (DuckDB) — parked, see the architecture
decision in the session handoff.
