# v6 P8 Upgrade and cutover

Roadmap row P8 (`2026-10-24-v6-roadmap.md`), spec §7 (upgrading from 5.x), §9 (verification). User 2026-11-01: 「繼續」
(start P8); Graylog 5516 is a temporary input, and cutover sends v6 to the existing 5514.

## 5.x facts this plan relies on (read from 5.x source, 2026-11-01)

- SIEM progress: `data/pce_cache.sqlite` (relative to the install root, `pce_cache.db_path`) has `siem_dispatch`
  (`source_table` `pce_events`|`pce_traffic_flows_raw`, `source_id` = row id, `destination` = destination **name**,
  `status` pending|sent|failed). Rows are enqueued per destination at ingest. Sent order is `queued_at`, not event time.
  Sent rows are deleted after 14 days.
- Event-alert progress: with the cache on, `ingestion_cursors(consumer='analyzer', source_table='pce_events')`
  `(last_ingested_at, last_row_id)` ordered by `(ingested_at, id)`. Without the cache, `logs/state.json`
  `event_watermark` (`%Y-%m-%dT%H:%M:%SZ`). SQLite datetimes are naive UTC.
- Install: root `/opt/illumio-ops`, unit `illumio-ops.service`, user `illumio-ops`, wrapper `/usr/local/bin/illumio-ops`;
  5.x is detected by `illumio-ops.py` at the root. .106 runs 5.x from `/root/illumio-ops` (git checkout and venv), the
  unit is still `illumio-ops`.

## Decisions

- **At least once over at most once.** For each migrated destination, the audit floor is the earliest timestamp still
  pending or failed minus 1 ms, or else the newest one sent. With no rows at all there is no floor: the destination
  starts at install and the report states the gap. SIEM delivery is already at least once; dedup uses externalId.
- The event-alert floor is the minimum event timestamp past the analyzer cursor, or else the newest one evaluated;
  `state.json` `event_watermark` is the fallback.
- Floors are read **after 5.x is stopped**, so they no longer move. The first events cycle reaches back to the earliest
  floor (capped at 7 days) so that the downtime is collected as live rows. Initial backfill never covers `[floor, now]`.
  Otherwise the gap would become backfill rows, which are never sent and never alerted.
- Only the audit source needs a floor. Alerts, detections and new connections are v6-native and start at install.
  5.x traffic → v6 new connections has no continuation; the report says so.
- The 5.x root is moved aside only when the v6 prefix is the same directory. `rollback.sh` restores it.
- The side-by-side `/opt/illumio-ops-v6` on .106 is stopped (not deleted) at cutover.

## Slices (each ships alone; ledger in `.superpowers/sdd/2026-11-01-v6-phase8-cutover/progress.md`)

**A. Handover continuity**
- Migrator write mode: `python -m illumio_ops.migrate --from DIR --write --root PREFIX [--lang]`.
  - It writes settings through the store, copies `config/tls/*` (keys 0600), and records the handover in the app-state
    DB (new migration).
  - Floors are read from the stopped 5.x. The report file goes to `PREFIX/logs/migration-report.txt`.
  - `migrate_siem` exposes destination name → v6 id.
- `siem_cursor.after_time`: the audit source advances past events at or before it without sending. They are counted as
  history, not dropped.
- Cursors of migrated destinations are placed at write time.
- Event alerts:
  - The watermark `t:<iso>` is applied once as a time filter, then replaced by the id.
  - The events cycle's first window reaches the earliest floor (at most 7 days).
  - Initial backfill ends where live collection began.
- Tests:
  - floors from a synthetic 5.x DB (pending, sent, failed, none) and from `state.json`
  - "backfill runs first; gap events still reach SIEM and alerts"
  - cursor history counting

**B. Installer upgrade mode**
- `install.sh --upgrade-from DIR` (auto-probe `PREFIX/illumio-ops.py`) with the flags:
  - `--report-only`
  - `--accept-report` (non-interactive)
  - `--lang`
  - `--old-service NAME` (default: the unit whose WorkingDirectory is DIR, else `illumio-ops`)
- Flow: report → confirm → stop and disable the old service → back up its unit and wrapper → move DIR aside if it
  equals PREFIX → install v6 → migrate write → render the unit. The service is not started.
- `rollback.sh` is shipped in the prefix:
  - stop and disable v6
  - move the v6 prefix to `*.v6-rolled-back-<stamp>`
  - restore the 5.x dir, unit and wrapper
  - enable and start 5.x
- Tests: shell-level tests with a fake 5.x tree and `--no-systemd`.

**C. Docs**
- `docs/guide/v6-installation.md`: fresh install, upgrade, rollback, the spec §5 hardware table.
- 5.x guides move to `docs/legacy-5.x/` (decided before D, to satisfy the `docs_check` `verified_against` gate).

**D. Repo cutover**
- Delete: `src/`, `tests/`, `deploy/`, `illumio-ops.py`, the 5.x scripts, the 5.x CI workflow, the 5.x-only `tools/`.
- Rename:
  - `tests_v6`→`tests`
  - `requirements-v6.*`→`requirements.*`
  - `scripts/v6/*`→`scripts/`
  - `ci-v6.yml`→`ci.yml`
  - `mypy-v6.ini`→`mypy.ini`
- Version 6.0.0. Grep every reference (workflows, bundle builder, gates, docs, the gates script).

**E. Acceptance**
1. Rehearsal on .106 against a copy of `/root/illumio-ops` with a scratch prefix and service name (not started).
2. Real cutover on .106:
   - before stopping, note the newest event href Graylog 5514 got from 5.x
   - upgrade
   - after the first cycles, every PCE event in `[stop, first v6 send]` reaches 5514 at least once, by href
   - `rollback.sh` → 5.x resumes → re-upgrade
3. .135 (5.x purged, nothing installed): fresh offline-bundle install pointed at NFR SaaS. This is also the NFR
   acceptance: collection, events, one alert, one report, SIEM reachability.
4. **Stop point:** the `v6.0.0` tag or release is pushed only after the user agrees.

Gates: `.superpowers/sdd/2026-10-31-v6-phase7-siem/gates.sh` (after D: renamed paths).
