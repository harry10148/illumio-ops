# PCE Cache

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

The retention worker runs daily and purges rows older than the configured TTL. To force a purge:

```bash
# Coming in Phase 14: illumio-ops cache retention --run-now
```

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
