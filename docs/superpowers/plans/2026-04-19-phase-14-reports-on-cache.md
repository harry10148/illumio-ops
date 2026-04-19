# Phase 14 Implementation Plan — Reports Read from PCE Cache

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate `AuditGenerator` (events) and `ReportGenerator` (traffic) to read from the PCE cache introduced in Phase 13 before falling back to the direct PCE API. When the requested time range falls outside local retention, surface a "backfill required" CTA instead of silently burning the API rate budget.

**Architecture:**
- Introduce a thin `CacheReader` façade (`src/pce_cache/reader.py`) that the two report generators consume. The reader returns `events | flows | None` depending on whether the requested range is fully within retention.
- `AuditGenerator.__init__` gains an optional `cache_reader` kwarg. When present and the range is in-retention, events are sourced from `pce_events`. Otherwise it falls through to `ApiClient.get_events()` with a logged INFO "cache-miss".
- `ReportGenerator` likewise consumes the cache reader — for trend summaries it prefers `pce_traffic_flows_agg`, for drill-downs it reads `pce_traffic_flows_raw`, and the API fallback stays intact for out-of-range windows.
- Add a backfill CLI + GUI flow: `illumio-ops cache backfill --source {events|traffic} --since YYYY-MM-DD --until YYYY-MM-DD` submits an async job (events: `Prefer: respond-async`; traffic: `/traffic_flows/async_queries`) and writes directly into cache, bypassing the normal ingestor loop. GUI shows a status modal that polls the job.

**Tech Stack:** No new deps. Re-uses Phase 13 SQLAlchemy models + `AsyncJobManager`.

**Branch:** `feature/phase-14-reports-cache` (from `main` after tag `v3.11.0-siem-cache`)

**Target tag on merge:** `v3.12.0-reports-cache`

**Baseline:** ≥ 470 passed (post-Phase 13). Target at merge: **≥ 495 passed** (+25 new tests).

---

## Pre-flight: confirm Phase 13 has shipped

- [ ] `git log --oneline main | head -5` shows the Phase 13 merge commit.
- [ ] `pytest -q` green on main before branching.
- [ ] `src/pce_cache/models.py` exists and `PceEvent` / `PceTrafficFlowRaw` / `PceTrafficFlowAgg` are importable.

If any of the above fails, stop — Phase 14 depends on Phase 13 being in main.

---

## File Structure

### Create

| File | Responsibility |
|---|---|
| `src/pce_cache/reader.py` | `CacheReader` façade — range-checked reads for events + traffic raw + traffic agg |
| `src/pce_cache/backfill.py` | `BackfillRunner` — submit async job, stream results into cache bypassing watermark |
| `src/cli/cache.py` | click subcommand `illumio-ops cache backfill|status|retention` |
| `src/templates/cache_backfill.html` | GUI modal for kicking off + polling a backfill |
| `tests/test_pce_cache_reader.py` | Range coverage, cache-hit / partial-hit / cache-miss |
| `tests/test_pce_cache_backfill.py` | Backfill writes bypass the ingestor's dedupe short-circuit |
| `tests/test_audit_generator_on_cache.py` | Audit report reads from cache when in range |
| `tests/test_report_generator_on_cache.py` | Traffic report reads from agg + raw |
| `tests/test_cache_cli.py` | click runner for `cache backfill|status|retention` |

### Modify

| File | Change |
|---|---|
| `src/report/audit_generator.py` | `__init__(..., cache_reader: CacheReader | None = None)`; `_fetch_events()` prefers cache when range in retention |
| `src/report/report_generator.py` | Same pattern for traffic; mod-level analysis stays behind the shim unchanged |
| `src/report_scheduler.py` | Inject `CacheReader` when `cm.models.pce_cache.enabled` |
| `src/cli/__init__.py` | Register `cache` click group |
| `src/gui.py` | Register `/api/cache/backfill` endpoint + status polling endpoint |
| `src/i18n_en.json` + `_ZH_EXPLICIT` | ~12 keys (`gui_backfill_*`, `cli_cache_*`, `cache_miss_notice`) |
| `docs/User_Manual.md` (+ `_zh.md`) | Document cache behaviour + backfill for report users |
| `docs/PCE_Cache.md` | Add "Cache-miss semantics" section |
| `Status.md` / `Task.md` | Phase 14 entry |

---

## Task 1 — Branch + baseline

- [ ] Branch:

```bash
git checkout main && git pull
git checkout -b feature/phase-14-reports-cache
```

- [ ] Baseline (expect ≥ 470 passed):

```bash
pytest -q
```

---

## Task 2 — CacheReader façade

**Files:** Create `src/pce_cache/reader.py`, `tests/test_pce_cache_reader.py`.

### Semantics

```
CacheReader.cover_state(source, start, end) -> Literal["full", "partial", "miss"]
   full    — [start, end] lies entirely within current retention AND last_sync_at >= end
   partial — start is before retention cutoff, but end lies within it
   miss    — end is before the retention cutoff
```

`CacheReader.read_events(start, end) -> list[dict]` and `read_flows(start, end) -> list[dict]` require `cover_state` in (`"full"`, `"partial"`). Partial state returns only the covered portion plus a flag so the caller knows to either backfill or fall back to API.

- [ ] **Step 2.1**: Tests (5 cases)

```python
# tests/test_pce_cache_reader.py
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import PceEvent


@pytest.fixture
def session_factory(tmp_path):
    from src.pce_cache.schema import init_schema
    engine = create_engine(f"sqlite:///{tmp_path/'c.sqlite'}")
    init_schema(engine)
    return sessionmaker(engine)


def _seed_event(sf, ts):
    with sf.begin() as s:
        s.add(PceEvent(
            pce_href=f"/orgs/1/events/{ts.isoformat()}",
            pce_event_id=ts.isoformat(), timestamp=ts,
            event_type="policy.update", severity="info", status="success",
            pce_fqdn="pce.example.com", raw_json="{}", ingested_at=ts,
        ))


def test_cover_state_full_when_range_in_retention(session_factory):
    from src.pce_cache.reader import CacheReader
    now = datetime.now(timezone.utc)
    _seed_event(session_factory, now - timedelta(days=1))
    rd = CacheReader(session_factory, events_retention_days=90, traffic_raw_retention_days=7)
    assert rd.cover_state("events", now - timedelta(days=2), now) == "full"


def test_cover_state_partial_when_start_before_cutoff(session_factory):
    from src.pce_cache.reader import CacheReader
    now = datetime.now(timezone.utc)
    rd = CacheReader(session_factory, events_retention_days=90, traffic_raw_retention_days=7)
    assert rd.cover_state("events", now - timedelta(days=120), now) == "partial"


def test_cover_state_miss_when_entirely_before_cutoff(session_factory):
    from src.pce_cache.reader import CacheReader
    now = datetime.now(timezone.utc)
    rd = CacheReader(session_factory, events_retention_days=90, traffic_raw_retention_days=7)
    assert rd.cover_state("events", now - timedelta(days=200),
                          now - timedelta(days=150)) == "miss"


def test_read_events_returns_dict_rows(session_factory):
    from src.pce_cache.reader import CacheReader
    now = datetime.now(timezone.utc)
    _seed_event(session_factory, now - timedelta(hours=1))
    rd = CacheReader(session_factory, events_retention_days=90, traffic_raw_retention_days=7)
    rows = rd.read_events(now - timedelta(hours=2), now)
    assert len(rows) == 1
    assert rows[0]["event_type"] == "policy.update"


def test_read_events_rejects_miss_range(session_factory):
    from src.pce_cache.reader import CacheReader
    now = datetime.now(timezone.utc)
    rd = CacheReader(session_factory, events_retention_days=90, traffic_raw_retention_days=7)
    with pytest.raises(ValueError, match="cache-miss"):
        rd.read_events(now - timedelta(days=200), now - timedelta(days=150))
```

- [ ] **Step 2.2**: Run — FAIL

- [ ] **Step 2.3**: Implement

```python
# src/pce_cache/reader.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

import orjson
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import PceEvent, PceTrafficFlowAgg, PceTrafficFlowRaw

CoverState = Literal["full", "partial", "miss"]


class CacheReader:
    def __init__(
        self,
        session_factory: sessionmaker,
        events_retention_days: int,
        traffic_raw_retention_days: int,
    ):
        self._sf = session_factory
        self._events_days = events_retention_days
        self._traffic_days = traffic_raw_retention_days

    def cover_state(self, source: str, start: datetime, end: datetime) -> CoverState:
        days = self._events_days if source == "events" else self._traffic_days
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        if end < cutoff:
            return "miss"
        if start < cutoff:
            return "partial"
        return "full"

    def read_events(self, start: datetime, end: datetime) -> list[dict]:
        state = self.cover_state("events", start, end)
        if state == "miss":
            raise ValueError("cache-miss: range entirely before retention cutoff")
        with self._sf() as s:
            q = (
                select(PceEvent)
                .where(PceEvent.timestamp >= start, PceEvent.timestamp <= end)
                .order_by(PceEvent.timestamp)
            )
            return [orjson.loads(r.raw_json) for r in s.execute(q).scalars()]

    def read_flows_raw(self, start: datetime, end: datetime) -> list[dict]:
        state = self.cover_state("traffic", start, end)
        if state == "miss":
            raise ValueError("cache-miss: range entirely before retention cutoff")
        with self._sf() as s:
            q = (
                select(PceTrafficFlowRaw)
                .where(
                    PceTrafficFlowRaw.last_detected >= start,
                    PceTrafficFlowRaw.last_detected <= end,
                )
                .order_by(PceTrafficFlowRaw.last_detected)
            )
            return [orjson.loads(r.raw_json) for r in s.execute(q).scalars()]

    def read_flows_agg(self, start: datetime, end: datetime) -> list[dict]:
        """For trend tables / pie charts — uses pce_traffic_flows_agg."""
        with self._sf() as s:
            q = (
                select(PceTrafficFlowAgg)
                .where(
                    PceTrafficFlowAgg.bucket_day >= start,
                    PceTrafficFlowAgg.bucket_day <= end,
                )
                .order_by(PceTrafficFlowAgg.bucket_day)
            )
            return [
                {
                    "bucket_day": row.bucket_day,
                    "src_workload": row.src_workload,
                    "dst_workload": row.dst_workload,
                    "port": row.port,
                    "protocol": row.protocol,
                    "action": row.action,
                    "flow_count": row.flow_count,
                    "bytes_total": row.bytes_total,
                }
                for row in s.execute(q).scalars()
            ]
```

- [ ] **Step 2.4**: Run — PASS (5 tests)

- [ ] **Step 2.5**: Commit

```bash
git add src/pce_cache/reader.py tests/test_pce_cache_reader.py
git commit -m "feat(phase-14): CacheReader facade with range-coverage semantics"
```

---

## Task 3 — AuditGenerator migration

**Files:** Modify `src/report/audit_generator.py`. Create `tests/test_audit_generator_on_cache.py`.

### Design

`AuditGenerator.__init__` gains `cache_reader: CacheReader | None = None`. Method `_fetch_events()` (currently a `self.api.get_events(...)` call) becomes:

```python
def _fetch_events(self, start, end):
    if self._cache is not None:
        state = self._cache.cover_state("events", start, end)
        if state == "full":
            logger.info("Audit report: events from cache ({}→{})", start, end)
            return self._cache.read_events(start, end)
        if state == "partial":
            logger.info("Audit report: partial cache hit; falling back to API for full range")
        else:
            logger.info("Audit report: cache miss; reading from API")
    return self.api.get_events(max_results=self._max_results, since=start.isoformat())
```

- [ ] **Step 3.1**: Test cases
  - `test_audit_generator_uses_cache_when_enabled`
  - `test_audit_generator_bypasses_cache_when_none`
  - `test_audit_generator_falls_back_on_partial`
  - `test_audit_generator_falls_back_on_miss`

- [ ] **Step 3.2**: Implement the `__init__` change + `_fetch_events` update.

- [ ] **Step 3.3**: Update `ReportScheduler` / CLI / GUI call sites that construct `AuditGenerator` to pass `cache_reader=CacheReader(...)` when `cm.models.pce_cache.enabled`.

- [ ] **Step 3.4**: Run — PASS

- [ ] **Step 3.5**: Commit

```bash
git add src/report/audit_generator.py src/report_scheduler.py src/gui.py src/cli \
        tests/test_audit_generator_on_cache.py
git commit -m "feat(phase-14): audit report reads from pce_cache when enabled"
```

---

## Task 4 — ReportGenerator (traffic) migration

**Files:** Modify `src/report/report_generator.py`. Create `tests/test_report_generator_on_cache.py`.

### Design

Traffic report has 15 analysis modules; most consume a flat `flows: list[dict]`. `_fetch_traffic()` becomes:

```python
def _fetch_traffic(self, start, end):
    if self._cache is not None:
        state = self._cache.cover_state("traffic", start, end)
        if state == "full":
            # Modules that only need summaries read from agg; drill-downs read raw
            return {
                "raw":  self._cache.read_flows_raw(start, end),
                "agg":  self._cache.read_flows_agg(start, end),
                "source": "cache",
            }
        if state == "partial":
            logger.info("Traffic report: partial cache hit, falling back to API for full range")
    flows = self.api.get_traffic_flows(start=start, end=end)
    return {"raw": flows, "agg": None, "source": "api"}
```

The 15 analysis modules continue to receive `flows` as before; the orchestrator passes `traffic["raw"]`. Modules that compute per-day aggregates already re-group client-side — they don't regress. Trend/KPI modules can optionally be updated in a later sweep to read `traffic["agg"]` directly (out of scope for Phase 14; documented as a follow-up).

- [ ] **Step 4.1**: Test cases (6 cases) — cache hit routes through `read_flows_raw`; cache miss routes through API; partial falls back to API; agg table populated on full hit.

- [ ] **Step 4.2**: Implement the `__init__` + `_fetch_traffic` change.

- [ ] **Step 4.3**: Verify the 15 mod's still receive a plain list (backward compat).

- [ ] **Step 4.4**: Run — PASS, including the existing 20 chart_spec regression tests from Phase 11.

- [ ] **Step 4.5**: Commit

```bash
git add src/report/report_generator.py tests/test_report_generator_on_cache.py
git commit -m "feat(phase-14): traffic report reads from pce_cache (raw + agg)"
```

---

## Task 5 — BackfillRunner + CLI + GUI

**Files:** Create `src/pce_cache/backfill.py`, `src/cli/cache.py`. Modify `src/gui.py`, `src/cli/__init__.py`, `src/templates/index.html` (add "Backfill" button on report pages). Create `tests/test_pce_cache_backfill.py`, `tests/test_cache_cli.py`.

### BackfillRunner API

```python
class BackfillRunner:
    def __init__(self, api, session_factory, rate_limit_per_minute):
        ...

    def run_events(self, since: datetime, until: datetime) -> BackfillResult:
        """Submit async events query, stream into pce_events, bypassing watermark.

        Does NOT advance the watermark — this is an out-of-band import.
        """

    def run_traffic(self, since: datetime, until: datetime,
                    filters: dict | None = None) -> BackfillResult:
        """Submit /traffic_flows/async_queries, stream into pce_traffic_flows_raw."""
```

`BackfillResult`: `{job_href, total_rows, inserted, duplicates, elapsed_seconds}`.

### CLI

```
illumio-ops cache backfill --source {events|traffic}
                           --since YYYY-MM-DD
                           --until YYYY-MM-DD
                           [--action blocked|allowed|... (traffic only, repeatable)]
illumio-ops cache status            # per-source: row count + retention + last_sync_at
illumio-ops cache retention         # human-readable summary of retention config
```

### GUI

- New button "Backfill cache" on the Audit Report + Traffic Report pages.
- Click opens a modal with date-range picker + source selector → POST `/api/cache/backfill`.
- Modal polls `GET /api/cache/backfill/<job_href>/status` every 5s until `completed` or `failed`.
- Result modal shows `inserted`, `duplicates`, `elapsed_seconds`.

- [ ] **Step 5.1**: Tests (8 unit + 4 CLI runner)
- [ ] **Step 5.2**: Implement `BackfillRunner` using `AsyncJobManager`
- [ ] **Step 5.3**: CLI subcommands
- [ ] **Step 5.4**: GUI modal + polling endpoint
- [ ] **Step 5.5**: i18n keys (~10)
- [ ] **Step 5.6**: Commit

```bash
git add src/pce_cache/backfill.py src/cli/cache.py src/cli/__init__.py src/gui.py \
        src/templates tests/test_pce_cache_backfill.py tests/test_cache_cli.py \
        src/i18n_en.json src/i18n.py
git commit -m "feat(phase-14): async backfill runner + CLI + GUI modal"
```

---

## Task 6 — Cache-source indicator in HTML reports

**Files:** Modify `src/report/exporters/audit_html_exporter.py`, `src/report/exporters/html_exporter.py`. Create `tests/test_cache_source_indicator.py`.

### UX

Every generated HTML report shows a small pill in the header:
- **"Data source: local cache (synced 2m ago)"** — green
- **"Data source: live PCE API"** — blue
- **"Data source: mixed (cache 2d → API for the earlier 5d)"** — yellow

Sourced from a `data_source` metadata field the generator now attaches to `report_metadata.py`.

- [ ] **Step 6.1**: Tests (3 cases)
- [ ] **Step 6.2**: Update `ReportMetadata` model to include `data_source: str`
- [ ] **Step 6.3**: Set it in both generators based on the branch taken in `_fetch_events`/`_fetch_traffic`
- [ ] **Step 6.4**: Render the pill in the two HTML exporters using `human_time_ago` (already imported)
- [ ] **Step 6.5**: i18n keys `rpt_data_source_cache` / `rpt_data_source_api` / `rpt_data_source_mixed`
- [ ] **Step 6.6**: Commit

```bash
git add src/report/exporters src/report/report_metadata.py tests/test_cache_source_indicator.py
git commit -m "feat(phase-14): HTML report header shows cache vs API data source"
```

---

## Task 7 — Docs + Status + final validation

**Files:** Modify `docs/User_Manual.md` + `docs/User_Manual_zh.md`, `docs/PCE_Cache.md`, `Status.md`, `Task.md`. Create `tests/test_phase_14_e2e.py`.

### E2E scenario

1. Phase 13 cache seeded with 2 days of events + flows.
2. Request a 1-day-ago-to-now report — asserts cache hit path, no API call (`FakeApiClient.sync_calls == 0`).
3. Request a 100-day-ago-to-now report — asserts partial → API fallback fires, metadata records `"mixed"`.
4. Run backfill for 30-day-ago-to-100-day-ago — asserts `inserted > 0`, cache `events_retention_days` is not violated (backfill writes but retention worker will purge on next tick — documented behaviour).

- [ ] **Step 7.1**: Write E2E test
- [ ] **Step 7.2**: User manual entries — new "Reporting from cached PCE data" section in both languages
- [ ] **Step 7.3**: Run full suite — expect **≥ 495 passed** (baseline 470 + 25 new)
- [ ] **Step 7.4**: i18n audit — 0 findings
- [ ] **Step 7.5**: Update Status.md + Task.md
- [ ] **Step 7.6**: PR + tag

```bash
git push -u origin feature/phase-14-reports-cache
gh pr create --title "feat(v3.12.0): Phase 14 — reports read from PCE cache" \
             --body "$(cat <<'EOF'
## Summary
- `CacheReader` facade with range-coverage semantics (full/partial/miss)
- `AuditGenerator` + `ReportGenerator` prefer cache when range in retention
- `BackfillRunner` + `illumio-ops cache backfill` CLI + GUI modal
- HTML report header shows "Data source: cache | API | mixed" pill

## Test plan
- [x] 495+ tests pass, 0 regressions
- [x] i18n audit 0 findings
- [x] E2E covers cache-hit / partial / miss / backfill
- [x] Manual: generate audit report with + without pce_cache.enabled, verify indicator
EOF
)"

# On merge
git tag v3.12.0-reports-cache && git push --tags
```

---

## Self-review checklist

- [ ] Default behaviour unchanged when `pce_cache.enabled = false` — reports call API as before.
- [ ] Cache-miss never silently triggers an API burst — either surfaces backfill CTA or falls through to a single API call for that report.
- [ ] Partial-range fallback fires exactly one API call, not one per sub-range.
- [ ] All 15 traffic analysis modules receive their existing `flows` shape — no regressions.
- [ ] Backfill writes bypass watermark but respect retention (retention purges them on next tick unless range is within retention).
- [ ] UDP warning from Phase 13 remains intact.
- [ ] HTML report pill renders in both EN and ZH.
