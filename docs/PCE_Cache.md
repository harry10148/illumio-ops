# PCE Cache

<!-- BEGIN:doc-map -->
| Document | EN | 中文 |
|---|---|---|
| README | [README.md](../README.md) | [README_zh.md](../README_zh.md) |
| Installation | [Installation.md](./Installation.md) | [Installation_zh.md](./Installation_zh.md) |
| User Manual | [User_Manual.md](./User_Manual.md) | [User_Manual_zh.md](./User_Manual_zh.md) |
| Report Modules | [Report_Modules.md](./Report_Modules.md) | [Report_Modules_zh.md](./Report_Modules_zh.md) |
| Security Rules | [Security_Rules_Reference.md](./Security_Rules_Reference.md) | [Security_Rules_Reference_zh.md](./Security_Rules_Reference_zh.md) |
| SIEM Integration | [SIEM_Integration.md](./SIEM_Integration.md) | [SIEM_Integration_zh.md](./SIEM_Integration_zh.md) |
| Architecture | [Architecture.md](./Architecture.md) | [Architecture_zh.md](./Architecture_zh.md) |
| PCE Cache | [PCE_Cache.md](./PCE_Cache.md) | [PCE_Cache_zh.md](./PCE_Cache_zh.md) |
| API Cookbook | [API_Cookbook.md](./API_Cookbook.md) | [API_Cookbook_zh.md](./API_Cookbook_zh.md) |
<!-- END:doc-map -->

> **[English](PCE_Cache.md)** | **[繁體中文](PCE_Cache_zh.md)**

---

## What It Is

The PCE cache is an optional local SQLite database that stores a rolling window of PCE audit events and traffic flows. It acts as a shared buffer between:

- **SIEM Forwarder** — reads from cache to forward events off-box
- **Reports** (Phase 14) — reads from cache to avoid repeated PCE API calls
- **Alerts/Monitor** (Phase 15) — subscribes to cache for 30-second tick cadence

## Why Use It

Without the cache, every report generation and monitor tick makes direct PCE API calls. The PCE enforces a 500 req/min rate limit. With the cache:

- Ingestors use a shared token-bucket rate limiter (default 400/min)
- Reports and alerts read from SQLite (zero PCE API calls for cached ranges)
- Traffic sampler reduces `allowed` flow volume (default: keep all; set `sample_ratio_allowed=10` for 1-in-10)

## Enabling

Add to `config/config.json`:

```json
"pce_cache": {
  "enabled": true,
  "db_path": "data/pce_cache.sqlite",
  "events_retention_days": 90,
  "traffic_raw_retention_days": 7,
  "traffic_agg_retention_days": 90,
  "events_poll_interval_seconds": 300,
  "traffic_poll_interval_seconds": 3600,
  "rate_limit_per_minute": 400
}
```

The cache starts on the next `--monitor` or `--monitor-gui` start. First poll may take a few minutes depending on event volume.

## Table Reference

| Table | Retention column | Default TTL | Notes |
|---|---|---|---|
| `pce_events` | `ingested_at` | 90 days | Full event JSON + indexes on type/severity/timestamp |
| `pce_traffic_flows_raw` | `ingested_at` | 7 days | Raw flow per unique src+dst+port+first_detected |
| `pce_traffic_flows_agg` | `bucket_day` | 90 days | Daily rollup; idempotent UPSERT |
| `ingestion_watermarks` | — | permanent | Per-source cursor; survives restarts |
| `siem_dispatch` | — | — | SIEM outbound queue; sent rows auto-age out |
| `dead_letter` | `quarantined_at` | 30 days (via purge) | Failed SIEM sends after max retries |

## Disk Sizing

Rough estimate (gzip-compressed JSON):
- 1,000 events/day × 90 days × ~1 KB/event ≈ **90 MB** for `pce_events`
- 50,000 flows/day × 7 days × ~0.5 KB/flow ≈ **175 MB** for raw flows
- Aggregated flows are much smaller; ~5 MB/year typical

Tune `traffic_raw_retention_days` first if disk pressure appears.

## Retention Tuning

The retention worker runs daily and purges rows older than the configured TTL. To view the current retention policy:

```bash
illumio-ops cache retention
```

The retention worker runs automatically as an APScheduler job; there is no `--run-now` flag. To force a purge manually, restart the daemon — the retention job fires on startup.

## Monitoring

Search loguru output for:
- `Events ingest: N rows inserted` — healthy ingest
- `Traffic ingest: N rows inserted` — healthy ingest
- `Cache retention purged:` — daily cleanup ran
- `Global rate limiter timeout` — PCE budget exhausted; lower `rate_limit_per_minute`

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `429` errors in log | PCE rate limit hit | Lower `rate_limit_per_minute` to 200–300 |
| DB growing fast | `traffic_raw_retention_days` too high | Drop to 3–5 days |
| Watermark not advancing | Events ingest error | Check log for `Events ingest failed` |
| Cache DB locked | Multiple processes | Ensure only one `--monitor` runs |

## Cache-miss semantics

When a report generator requests data for a time range, `CacheReader.cover_state()` returns one of three states:

- **`full`** — the entire range lies within the configured retention window; data is served from cache, no API call is made.
- **`partial`** — the range start precedes the retention cutoff but the end is within it; the generator falls back to the API for the full range.
- **`miss`** — the entire range predates the retention window; the generator falls back to the API.

### Backfill

To populate the cache for historical ranges use the CLI:

```bash
illumio-ops cache backfill --source events --since 2026-01-01 --until 2026-03-01
illumio-ops cache backfill --source traffic --since 2026-01-01 --until 2026-03-01
```

Backfill writes directly into `pce_events` / `pce_traffic_flows_raw`, bypassing the normal ingestor watermark. The retention worker will purge backfilled data on its next tick if it falls outside the configured retention window.

Check cache status and retention policy:

```bash
illumio-ops cache status
illumio-ops cache retention
```

### Data source indicator

Generated HTML reports display a colored pill in the report header indicating the data source:
- **Green** — data served from local cache
- **Blue** — data fetched from live PCE API
- **Yellow** — mixed (partial cache + API)

## Operator CLI Commands

The `illumio-ops cache` subcommand group (implemented in `src/cli/cache.py`) provides all cache management operations.

### `illumio-ops cache status`

```
illumio-ops cache status
```

Displays a table of row counts and last-ingested timestamps for each cache table (`events`, `traffic_raw`, `traffic_agg`). Reads directly from the SQLite DB; does not require the daemon to be running.

### `illumio-ops cache retention`

```
illumio-ops cache retention
```

Shows the configured retention policy as a table of TTL values:

| Setting | Default |
|---|---|
| `events_retention_days` | 90 |
| `traffic_raw_retention_days` | 7 |
| `traffic_agg_retention_days` | 90 |

### `illumio-ops cache backfill`

```
illumio-ops cache backfill --source events --since YYYY-MM-DD [--until YYYY-MM-DD]
illumio-ops cache backfill --source traffic --since YYYY-MM-DD [--until YYYY-MM-DD]
```

Populates the cache for historical date ranges by fetching from the PCE API. Writes directly to `pce_events` / `pce_traffic_flows_raw`, bypassing the normal ingestor watermark. On completion, prints rows inserted, duplicates skipped, and elapsed time. The retention worker will purge backfilled data on its next tick if it falls outside the configured retention window.

---

## Alerts on Cache

When `pce_cache.enabled = true`, the Analyzer subscribes to the PCE cache
via `CacheSubscriber` instead of querying the PCE API directly. This enables:

- **30-second alert latency** — the monitor tick drops from `interval_minutes`
  (default 10 min) to 30 seconds when cache is enabled.
- **No API budget impact** — each tick reads local SQLite only; PCE API calls
  happen only via the ingestor on its own schedule.

### How it works

```
PCE API  →  Ingestor  →  pce_cache.db
                              ↓
                        CacheSubscriber
                              ↓
                          Analyzer  →  Reporter  →  Alerts
```

Each consumer (analyzer) holds an independent cursor in the `ingestion_cursors`
table. On each 30-second tick, the Analyzer reads only rows inserted since the
last cursor position.

### Cache lag monitoring

A separate APScheduler job (`cache_lag_monitor`) runs every 60 seconds and
checks `ingestion_watermarks.last_sync_at`. If the ingestor has not synced
within `3 × max(events_poll_interval, traffic_poll_interval)` seconds, it
emits a `WARNING` log. If lag exceeds twice that threshold, it emits `ERROR`.
This catches ingestor stalls before alerts silently drift.

### Fallback

When `pce_cache.enabled = false` (default), every code path reverts to the
original PCE API behaviour. No configuration change is needed for existing
deployments.

---

## See also

- [Architecture](./Architecture.md) — system context and module deep dive
- [User Manual](./User_Manual.md) — `cache` CLI subcommand operator commands
- [README](../README.md) — project entry and Quickstart
