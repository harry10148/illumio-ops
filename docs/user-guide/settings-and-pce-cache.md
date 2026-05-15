---
title: Settings and PCE Cache
audience: [operator]
last_verified: 2026-05-15
verified_against:
  - src/pce_cache/
  - src/settings/
  - data/pce_cache.sqlite (path)
  - python illumio-ops.py cache --help
  - commit 2437209
related_docs:
  - getting-started.md
  - multi-pce.md
  - ../architecture/overview.md
  - troubleshooting.md
---

> **[English](settings-and-pce-cache.md)** | **[繁體中文](settings-and-pce-cache_zh.md)**
> 📍 [INDEX](../INDEX.md) › User Guide › Settings & PCE Cache
> 🔍 Last verified **2026-05-15** against commit `2437209` — see frontmatter for sources

# Settings and PCE Cache

---

## Settings overview

The Settings page is split into four sub-tabs. Each sub-tab tracks its own
dirty state; the **Save** button label updates to show which tab has pending
changes (e.g. "Save PCE Settings"). Deep-linking is supported via the `stab`
URL parameter — `?stab=security` opens directly to the Security tab.

| Sub-tab | Contents |
|---------|----------|
| **PCE** | PCE connection profiles, active PCE selection, API connection |
| **Channels** | Notification channel plugins (Slack, email, webhook, …) |
| **Display** | UI display preferences |
| **Security** | Web UI password, confirm-password field, TLS settings |

---

## Password / credentials

The **Security** sub-tab contains the web UI password section. As of commit
`2d99dc5`, a **Confirm New Password** field sits next to the New Password
field. Client-side validation rejects mismatches with a localised toast and
aborts the save before it reaches the server.

Key behaviour:
- Mismatch is caught on the client; no API call is made.
- i18n keys cover both the field label and the mismatch error message in
  English and zh_TW.
- The TLS toggle (enable/disable HTTPS) also lives in this sub-tab.

---

## PCE connection settings

The **PCE** sub-tab manages one or more PCE profiles. Each profile stores:

| Field | Notes |
|-------|-------|
| Profile Name | Display label |
| URL | e.g. `https://pce.example.com:8443` |
| Org ID | Default `1` |
| API Key | PCE API key ID |
| API Secret | PCE API secret (masked) |
| Verify SSL | Checkbox; uncheck only for self-signed certs in dev |

You can have multiple profiles and switch between them with the **Activate**
button. The active profile is shown with a green checkmark. Saving any PCE
sub-tab field updates the currently active profile.

See [Multi-PCE](multi-pce.md) for per-PCE scope and profile switching.

---

## Traffic sampling settings

Traffic sampling controls how many allowed flows the cache ingestor keeps.
It is configured in `config/config.json` under `pce_cache.traffic_sampling`
and is also editable from the Integrations page (Cache section).

| Field | Default | Notes |
|-------|---------|-------|
| `sample_ratio_allowed` | `1` (keep all) | Keep 1 in N allowed flows. Value `1` = no sampling; `10` = keep ~10 %. Uses a deterministic SHA-256 hash of the flow tuple so the same flow is always included or excluded across restarts. |
| `max_rows_per_batch` | `200000` | Hard cap on rows fetched per poll cycle. Prevents runaway API calls during high-traffic periods. |

> **Sampling only affects allowed flows.** Blocked flows and audit events are
> always ingested regardless of `sample_ratio_allowed`.

CLI help text added in commit `6c3382e` explains the deterministic hash
behaviour and batch-size guidance inline before each prompt.

---

## PCE cache — what it is

The PCE cache is an **optional** local SQLite database at `data/pce_cache.sqlite`
(path set by `pce_cache.db_path` in `config/config.json`; default shown).
The `data/` directory is created automatically on first start if absent.

It stores a rolling retention window of:
- **PCE audit events** — polled every `events_poll_interval_seconds` (default 300 s)
- **Traffic flows** — polled every `traffic_poll_interval_seconds` (default 3600 s)

Consumers of the cache:

| Consumer | How it uses the cache |
|----------|-----------------------|
| SIEM Forwarder | Reads rows from `pce_events` / `pce_traffic_flows_raw` via `CacheSubscriber`; advances a per-consumer cursor |
| Reports (Phase 14) | `CacheReader.cover_state()` decides full / partial / miss; avoids repeated PCE API calls |
| Alerts / Monitor (Phase 15) | Subscribes on a 30-second tick cadence |

The cache is **disabled by default** (`pce_cache.enabled = false`). All code
paths fall back to direct PCE API calls when disabled.

To enable, add to `config/config.json`:

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

The ingestor starts on the next `--monitor` or `--monitor-gui` launch. The
first poll may take several minutes depending on event volume.

---

## Cache refresh modes

The cache uses **incremental, watermark-based polling** — there is no manual
"full refresh" mode. Each source (`events`, `traffic`) has its own
`IngestionWatermark` row that records `last_timestamp` and `last_href`. On
each poll cycle the ingestor fetches only records newer than the watermark.

**Cache-miss semantics** (`CacheReader.cover_state()`):

| State | Meaning | Report behaviour |
|-------|---------|-----------------|
| `full` | Entire requested range is within retention window | Served from cache; no PCE API call |
| `partial` | Range start precedes retention cutoff | Falls back to PCE API for the full range |
| `miss` | Entire range predates retention window | Falls back to PCE API |

**On-demand backfill** — use `illumio-ops cache backfill` (see below) to
populate historical data outside the normal poll cycle.

**Retention purge** — a daily APScheduler job calls `RetentionWorker.run_once()`
to delete rows older than the configured TTLs. The `cache retention --run`
command triggers this on demand.

**Lag monitoring** — a separate job (`cache_lag_monitor`) runs every 60 s and
checks `ingestion_watermarks.last_sync_at`. It emits `WARNING` if the ingestor
has not synced within `3 × max(events_poll_interval, traffic_poll_interval)`
seconds, and `ERROR` at twice that threshold.

---

## Cache management CLI

The `illumio-ops cache` subcommand group provides all cache management
operations. Verified against commit `2437209`:

```
illumio-ops cache [OPTIONS] COMMAND [ARGS]...

  PCE cache management — backfill, status, retention.

Commands:
  backfill   Backfill the PCE cache from the API for a historical date range.
  retention  Show configured cache retention policy, or run it.
  status     Show cache row counts and last-sync timestamps.
```

### `illumio-ops cache status`

```bash
illumio-ops cache status
```

Displays row counts and last-ingested timestamps for each cache table
(`events`, `traffic_raw`, `traffic_agg`). Reads directly from the SQLite
database; does not require the daemon to be running.

### `illumio-ops cache backfill`

```bash
illumio-ops cache backfill --source events --since 2026-04-01
illumio-ops cache backfill --source traffic --since 2026-04-01 --until 2026-04-30
illumio-ops cache backfill --source events --since 2026-04-01 --json
```

| Option | Required | Notes |
|--------|----------|-------|
| `--source` | Yes | `events` or `traffic` |
| `--since` | Yes | Start date `YYYY-MM-DD` |
| `--until` | No | End date `YYYY-MM-DD`; defaults to today |
| `--json` | No | Emit result as JSON |

### `illumio-ops cache retention`

```bash
illumio-ops cache retention          # show policy only (read-only)
illumio-ops cache retention --run    # show policy + execute purge now
```

Default TTLs shown when the policy is displayed:

| Setting | Default |
|---------|---------|
| `events_retention_days` | 90 days |
| `traffic_raw_retention_days` | 7 days |
| `traffic_agg_retention_days` | 90 days |

---

## Cache schema overview

The database has six tables. Full column definitions live in
`src/pce_cache/models.py`. The database is opened in WAL mode
(`PRAGMA journal_mode = WAL`) with `PRAGMA foreign_keys = ON`.

| Table | Purpose | Retention |
|-------|---------|-----------|
| `pce_events` | Audit events; full JSON blob + indexed metadata | 90 days (`ingested_at`) |
| `pce_traffic_flows_raw` | One row per unique flow (src+dst+port); 7-day rolling window | 7 days (`ingested_at`) |
| `pce_traffic_flows_agg` | Daily rollup of raw flows; idempotent UPSERT | 90 days (`bucket_day`) |
| `ingestion_watermarks` | Per-source poll cursor (`last_timestamp`, `last_href`, `last_sync_at`) | Permanent |
| `siem_dispatch` | SIEM outbound queue; rows auto-age out after delivery | Auto |
| `dead_letter` | Failed SIEM sends after max retries | 30 days (`quarantined_at`) |

> **Tip:** `ingestion_cursors` is a separate table used by `CacheSubscriber`
> to track per-consumer read position within `pce_events` and
> `pce_traffic_flows_raw`. It is distinct from `ingestion_watermarks`.

For internal data-flow details see
[Architecture Overview](../architecture/overview.md).

---

## Backup & migration

The cache database is a standard SQLite file. To back it up or move it to
another host:

**Back up in place:**

```bash
# Safe hot copy using SQLite's backup API
sqlite3 data/pce_cache.sqlite ".backup data/pce_cache_backup.sqlite"
```

**Copy to another host:**

```bash
# Stop the daemon first to avoid a torn WAL
systemctl stop illumio-ops   # or your process manager
cp data/pce_cache.sqlite /mnt/backup/pce_cache_$(date +%Y%m%d).sqlite
systemctl start illumio-ops
```

**Move to a new host:**

1. Copy `data/pce_cache.sqlite` to the new host.
2. Update `pce_cache.db_path` in `config/config.json` if the path differs.
3. The application will call `init_schema()` on start, which is idempotent —
   it creates any missing tables but does not drop existing data.

**Changing the database path:**

```json
"pce_cache": {
  "db_path": "/opt/illumio-ops/cache/pce_cache.sqlite"
}
```

The parent directory is created automatically (`os.makedirs(..., exist_ok=True)`).

> **Note:** There is no built-in migration tool for schema upgrades. If a
> table structure changes between releases, drop and repopulate via backfill.
> Check release notes before upgrading.

---

## Related Docs

- [Getting Started](getting-started.md) — initial settings setup
- [Multi-PCE](multi-pce.md) — per-PCE settings scope
- [Architecture Overview](../architecture/overview.md) — internal data model (B2)
- [Troubleshooting](troubleshooting.md) — cache corruption / stale data
